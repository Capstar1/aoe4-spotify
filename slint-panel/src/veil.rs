//! Page-switch resize with zero stale frames. DWM composes a moved/resized window with its OLD surface until the
//! new-size frame is presented, so any in-place resize shows one warped/shifted frame. Instead:
//!  1. "veil": a topmost, click-through layered copy of the screen over the area that will change (old + new rect
//!     and the shadow margin) - pixel-identical to what is already on screen, so nothing visibly changes;
//!  2. the panel is DWM-cloaked under it, moved + resized, its new frame rendered synchronously, DwmFlush;
//!  3. uncloak, then remove the veil in the same breath, DwmFlush.
//! Every composed frame is either the old screen (the veil) or the finished new panel; the bad frame happens hidden.
use crate::geom::Rect;
use std::ffi::c_void;
#[repr(C)] struct Bih { size: u32, w: i32, h: i32, planes: u16, bits: u16, comp: u32, img: u32, xp: i32, yp: i32, used: u32, imp: u32, mask: [u32; 4] }
#[repr(C)] struct Pt { x: i32, y: i32 }
#[repr(C)] struct Sz { cx: i32, cy: i32 }
#[repr(C)] struct Blend { op: u8, flags: u8, alpha: u8, fmt: u8 }
#[repr(C)] struct Wc { size: u32, style: u32, proc_: unsafe extern "system" fn(isize, u32, usize, isize) -> isize, cls: i32, wnd: i32, inst: isize, icon: isize, cur: isize, bg: isize, menu: *const u16, name: *const u16, sm: isize }
#[link(name = "user32")] extern "system" {
    fn GetDC(h: isize) -> isize; fn ReleaseDC(h: isize, dc: isize) -> i32;
    fn RegisterClassExW(w: *const Wc) -> u16; fn DefWindowProcW(h: isize, m: u32, w: usize, l: isize) -> isize;
    fn CreateWindowExW(ex: u32, cls: *const u16, name: *const u16, st: u32, x: i32, y: i32, w: i32, h: i32, p: isize, m: isize, i: isize, lp: *const c_void) -> isize;
    fn UpdateLayeredWindow(h: isize, dst: isize, pt: *const Pt, sz: *const Sz, src: isize, spt: *const Pt, key: u32, b: *const Blend, f: u32) -> i32;
    fn ShowWindow(h: isize, c: i32) -> i32; fn DestroyWindow(h: isize) -> i32;
    fn SetWindowPos(h: isize, after: isize, x: i32, y: i32, w: i32, h2: i32, f: u32) -> i32;
    fn RedrawWindow(h: isize, r: *const Rect, rgn: isize, f: u32) -> i32;
    fn GetCursorPos(p: *mut Pt) -> i32; fn SetCursorPos(x: i32, y: i32) -> i32;
}
#[link(name = "gdi32")] extern "system" {
    fn CreateCompatibleDC(dc: isize) -> isize; fn DeleteDC(dc: isize) -> i32; fn SelectObject(dc: isize, o: isize) -> isize; fn DeleteObject(o: isize) -> i32;
    fn CreateDIBSection(dc: isize, b: *const Bih, u: u32, bits: *mut *mut u8, s: isize, o: u32) -> isize;
    fn BitBlt(d: isize, x: i32, y: i32, w: i32, h: i32, s: isize, sx: i32, sy: i32, rop: u32) -> i32;
}
#[link(name = "kernel32")] extern "system" { fn GetModuleHandleW(n: *const u16) -> isize; }
#[link(name = "dwmapi")] extern "system" { fn DwmSetWindowAttribute(h: isize, a: u32, v: *const u32, n: u32) -> i32; fn DwmFlush() -> i32; }

fn wide(s: &str) -> Vec<u16> { s.encode_utf16().chain(Some(0)).collect() }
fn cloak(h: isize, on: bool) { let v = on as u32; unsafe { DwmSetWindowAttribute(h, 13, &v, 4) }; }

/// A topmost, click-through, non-activating copy of the screen rect r (None if anything fails).
fn veil(r: Rect) -> Option<isize> {
    let (w, h) = (r.r - r.l, r.b - r.t); if w <= 0 || h <= 0 { return None; }
    unsafe {
        let cls = wide("AoE4SpotifyVeil");
        let wc = Wc { size: std::mem::size_of::<Wc>() as u32, style: 0, proc_: DefWindowProcW, cls: 0, wnd: 0, inst: GetModuleHandleW(std::ptr::null()), icon: 0, cur: 0, bg: 0, menu: std::ptr::null(), name: cls.as_ptr(), sm: 0 };
        RegisterClassExW(&wc);   // (already registered on later calls: fine)
        // WS_EX_LAYERED|TOPMOST|TOOLWINDOW|NOACTIVATE, WS_POPUP. NOT click-through: while the panel is cloaked the veil takes
        // the mouse, so the window behind never gets hover for those frames.
        let hw = CreateWindowExW(0x80000 | 0x8 | 0x80 | 0x0800_0000, cls.as_ptr(), cls.as_ptr(), 0x8000_0000, r.l, r.t, w, h, 0, 0, wc.inst, std::ptr::null());
        if hw == 0 { return None; }
        let scr = GetDC(0); let mem = CreateCompatibleDC(scr);
        let bih = Bih { size: 40, w, h: -h, planes: 1, bits: 32, comp: 0, img: 0, xp: 0, yp: 0, used: 0, imp: 0, mask: [0; 4] };
        let mut bits: *mut u8 = std::ptr::null_mut();
        let bmp = CreateDIBSection(mem, &bih, 0, &mut bits, 0, 0);
        let ok = bmp != 0 && !bits.is_null() && { let old = SelectObject(mem, bmp);
            let ok = BitBlt(mem, 0, 0, w, h, scr, r.l, r.t, 0x00CC_0020 | 0x4000_0000) != 0;   // SRCCOPY | CAPTUREBLT
            if ok { for i in 0..(w * h) as usize { *bits.add(i * 4 + 3) = 255; } }       // opaque
            let ok = ok && UpdateLayeredWindow(hw, scr, &Pt { x: r.l, y: r.t }, &Sz { cx: w, cy: h }, mem, &Pt { x: 0, y: 0 }, 0, &Blend { op: 0, flags: 0, alpha: 255, fmt: 1 }, 2) != 0;
            SelectObject(mem, old); ok };
        if bmp != 0 { DeleteObject(bmp); } DeleteDC(mem); ReleaseDC(0, scr);
        if !ok { DestroyWindow(hw); return None; }
        ShowWindow(hw, 4);   // SW_SHOWNOACTIVATE
        Some(hw)
    }
}

/// Move + resize the panel to (x, y, w, hh) with no stale frame ever composed (see module doc).
pub fn place(h: isize, old: Rect, x: i32, y: i32, w: i32, hh: i32) {
    const M: i32 = 40;   // DWM shadow margin
    let u = Rect { l: old.l.min(x) - M, t: old.t.min(y) - M, r: old.r.max(x + w) + M, b: old.b.max(y + hh) + M };
    let v = veil(u);
    unsafe {
        if v.is_some() { DwmFlush(); cloak(h, true); }
        SetWindowPos(h, 0, x, y, w, hh, 0x4 | 0x10 | 0x100 | 0x8);           // NOZORDER|NOACTIVATE|NOCOPYBITS|NOREDRAW
        RedrawWindow(h, std::ptr::null(), 0, 0x1 | 0x100 | 0x400);          // paint the new page now
        DwmFlush();
        if let Some(v) = v { cloak(h, false); DestroyWindow(v); DwmFlush();
            // fresh mouse move at the same spot: the panel's hover state is right at once
            let mut p = Pt { x: 0, y: 0 }; if GetCursorPos(&mut p) != 0 { SetCursorPos(p.x, p.y); } }
    }
}
