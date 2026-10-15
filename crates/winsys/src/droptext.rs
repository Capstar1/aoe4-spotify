//! Text drops from other apps (Spotify drags song / playlist links as text). winit only reports file drops, so the
//! window's OLE drop target is replaced by this one: IDropTarget reading CF_UNICODETEXT / UniformResourceLocatorW.
#![cfg(windows)]
use std::{ffi::c_void, sync::atomic::{AtomicU32, Ordering}};

/// Drag events, delivered on the window's thread: Enter(text), Over, Leave, Drop(text).
pub enum Ev { Enter(String), Leave, Drop(String) }
type Cb = Box<dyn Fn(Ev)>;

#[repr(C)] struct Formatetc { cf: u16, ptd: *mut c_void, aspect: u32, lindex: i32, tymed: u32 }
#[repr(C)] struct Stgmedium { tymed: u32, h: *mut c_void, release: *mut c_void }
#[repr(C)] struct IDataObjectVtbl { qi: usize, add_ref: usize, release: usize, get_data: unsafe extern "system" fn(*mut c_void, *const Formatetc, *mut Stgmedium) -> i32 }
#[repr(C)] struct Vtbl {
    qi: unsafe extern "system" fn(*mut Target, *const [u8; 16], *mut *mut c_void) -> i32,
    add_ref: unsafe extern "system" fn(*mut Target) -> u32,
    release: unsafe extern "system" fn(*mut Target) -> u32,
    enter: unsafe extern "system" fn(*mut Target, *mut c_void, u32, u64, *mut u32) -> i32,
    over: unsafe extern "system" fn(*mut Target, u32, u64, *mut u32) -> i32,
    leave: unsafe extern "system" fn(*mut Target) -> i32,
    drop: unsafe extern "system" fn(*mut Target, *mut c_void, u32, u64, *mut u32) -> i32,
}
#[repr(C)] struct Target { vtbl: *const Vtbl, refs: AtomicU32, cb: Cb }

#[link(name = "ole32")] extern "system" { fn RegisterDragDrop(h: isize, t: *mut c_void) -> i32; fn RevokeDragDrop(h: isize) -> i32; fn ReleaseStgMedium(m: *mut Stgmedium); fn OleInitialize(r: *mut c_void) -> i32; }
#[link(name = "user32")] extern "system" { fn RegisterClipboardFormatW(n: *const u16) -> u32; }
#[link(name = "kernel32")] extern "system" { fn GlobalLock(h: *mut c_void) -> *const u16; fn GlobalUnlock(h: *mut c_void) -> i32; }

const IID_IUNKNOWN: [u8; 16] = [0, 0, 0, 0, 0, 0, 0, 0, 0xC0, 0, 0, 0, 0, 0, 0, 0x46];
const IID_IDROPTARGET: [u8; 16] = [0x22, 0x01, 0, 0, 0, 0, 0, 0, 0xC0, 0, 0, 0, 0, 0, 0, 0x46];

unsafe extern "system" fn qi(this: *mut Target, iid: *const [u8; 16], out: *mut *mut c_void) -> i32 {
    if *iid == IID_IUNKNOWN || *iid == IID_IDROPTARGET { *out = this as *mut c_void; add_ref(this); 0 } else { *out = std::ptr::null_mut(); 0x80004002u32 as i32 }
}
unsafe extern "system" fn add_ref(this: *mut Target) -> u32 { (*this).refs.fetch_add(1, Ordering::SeqCst) + 1 }
unsafe extern "system" fn release(this: *mut Target) -> u32 { let n = (*this).refs.fetch_sub(1, Ordering::SeqCst) - 1; if n == 0 { drop(Box::from_raw(this)); } n }
unsafe extern "system" fn enter(this: *mut Target, d: *mut c_void, _k: u32, _p: u64, eff: *mut u32) -> i32 { ((*this).cb)(Ev::Enter(text(d))); *eff = 1; 0 }
unsafe extern "system" fn over(_this: *mut Target, _k: u32, _p: u64, eff: *mut u32) -> i32 { *eff = 1; 0 }
unsafe extern "system" fn leave(this: *mut Target) -> i32 { ((*this).cb)(Ev::Leave); 0 }
unsafe extern "system" fn dropped(this: *mut Target, d: *mut c_void, _k: u32, _p: u64, eff: *mut u32) -> i32 { ((*this).cb)(Ev::Drop(text(d))); *eff = 1; 0 }
static VTBL: Vtbl = Vtbl { qi, add_ref, release, enter, over, leave, drop: dropped };

/// Unicode text of a drag: plain text first, else the URL format browsers / Spotify also offer.
unsafe fn text(d: *mut c_void) -> String {
    if d.is_null() { return String::new(); }
    let vt = *(d as *const *const IDataObjectVtbl);
    let url: Vec<u16> = "UniformResourceLocatorW".encode_utf16().chain(Some(0)).collect();
    for cf in [13u16, RegisterClipboardFormatW(url.as_ptr()) as u16] {
        let f = Formatetc { cf, ptd: std::ptr::null_mut(), aspect: 1, lindex: -1, tymed: 1 };
        let mut m = Stgmedium { tymed: 0, h: std::ptr::null_mut(), release: std::ptr::null_mut() };
        if ((*vt).get_data)(d, &f, &mut m) != 0 { continue; }
        let mut out = String::new();
        let p = GlobalLock(m.h); if !p.is_null() { let mut n = 0; while *p.add(n) != 0 && n < 1 << 20 { n += 1; } out = String::from_utf16_lossy(std::slice::from_raw_parts(p, n)); GlobalUnlock(m.h); }
        ReleaseStgMedium(&mut m);
        if !out.is_empty() { return out; }
    }
    String::new()
}

/// Replace the window's drop target (winit's file-drop one) with a text drop target calling `cb`.
pub fn register(hwnd: isize, cb: impl Fn(Ev) + 'static) -> bool {
    unsafe {
        OleInitialize(std::ptr::null_mut());   // already done by winit (S_FALSE); harmless otherwise
        RevokeDragDrop(hwnd);
        let t = Box::into_raw(Box::new(Target { vtbl: &VTBL, refs: AtomicU32::new(1), cb: Box::new(cb) }));
        let ok = RegisterDragDrop(hwnd, t as *mut c_void) == 0;
        release(t);   // OLE holds its own reference while registered
        ok
    }
}

// ---- test: drive a window's registered OLE drop target the way DoDragDrop does (DragEnter / DragOver / Drop with an
// IDataObject offering CF_UNICODETEXT), so the whole text path runs without moving the real mouse (hidden-desktop tests).
#[repr(C)] struct FakeVtbl { qi: unsafe extern "system" fn(*mut Fake, *const [u8; 16], *mut *mut c_void) -> i32, add_ref: unsafe extern "system" fn(*mut Fake) -> u32,
    release: unsafe extern "system" fn(*mut Fake) -> u32, get_data: unsafe extern "system" fn(*mut Fake, *const Formatetc, *mut Stgmedium) -> i32 }
#[repr(C)] struct Fake { vtbl: *const FakeVtbl, text: Vec<u16> }
unsafe extern "system" fn f_qi(this: *mut Fake, _i: *const [u8; 16], out: *mut *mut c_void) -> i32 { *out = this as *mut c_void; 0 }
unsafe extern "system" fn f_ref(_t: *mut Fake) -> u32 { 1 }
unsafe extern "system" fn f_get(this: *mut Fake, f: *const Formatetc, m: *mut Stgmedium) -> i32 {
    #[link(name = "kernel32")] extern "system" { fn GlobalAlloc(f: u32, n: usize) -> *mut c_void; }
    if (*f).cf != 13 || (*f).tymed & 1 == 0 { return 0x8004_0064u32 as i32; }   // DV_E_FORMATETC
    let t = &(*this).text; let h = GlobalAlloc(0x0002, t.len() * 2); if h.is_null() { return 0x8007_000Eu32 as i32; }
    let p = GlobalLock(h) as *mut u16; std::ptr::copy_nonoverlapping(t.as_ptr(), p, t.len()); GlobalUnlock(h);
    (*m).tymed = 1; (*m).h = h; (*m).release = std::ptr::null_mut(); 0
}
static FAKE_VTBL: FakeVtbl = FakeVtbl { qi: f_qi, add_ref: f_ref, release: f_ref, get_data: f_get };

/// Enter (+ Over) and then Drop (`drop`) or Leave on the target registered for `hwnd`. false = no drop target registered.
pub fn simulate(hwnd: isize, text: &str, drop: bool) -> bool {
    #[link(name = "user32")] extern "system" { fn GetPropW(h: isize, n: *const u16) -> *mut c_void; }
    let n: Vec<u16> = "OleDropTargetInterface".encode_utf16().chain(Some(0)).collect();
    unsafe {
        let t = GetPropW(hwnd, n.as_ptr()) as *mut Target; if t.is_null() { return false; }
        let vt = &*(*(t as *const *const Vtbl));
        let mut fake = Fake { vtbl: &FAKE_VTBL, text: text.encode_utf16().chain(Some(0)).collect() };
        let d = &mut fake as *mut Fake as *mut c_void; let mut eff = 0u32;
        (vt.enter)(t, d, 1, 0, &mut eff); (vt.over)(t, 1, 0, &mut eff);
        if drop { (vt.drop)(t, d, 0, 0, &mut eff); } else { (vt.leave)(t); }
        eff == 1
    }
}
