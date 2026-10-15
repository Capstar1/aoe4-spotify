//! Drop shadow for the borderless window: a separate click-through layered window (WS_EX_LAYERED|TRANSPARENT)
//! kept directly behind the panel. The panel's own window region stays exactly the drawn frame, so nothing
//! outside the visible page takes input, yet the frame still gets a soft Windows-11-like shadow.
use std::sync::atomic::{AtomicIsize, Ordering};
use std::sync::Mutex;

static MAIN: AtomicIsize = AtomicIsize::new(0);
static SHADOW: AtomicIsize = AtomicIsize::new(0);
static FRAME: Mutex<(i32, i32, i32, i32, i32)> = Mutex::new((0, 0, 0, 0, 0)); // x,y,w,h in client px, margin

#[repr(C)] struct Wc { style: u32, proc_: usize, cls: i32, wnd: i32, inst: isize, icon: isize, cur: isize, bg: isize, menu: *const u16, name: *const u16 }
#[repr(C)] struct Rect { l: i32, t: i32, r: i32, b: i32 }
#[repr(C)] struct Pt { x: i32, y: i32 }
#[repr(C)] struct Bih { size: u32, w: i32, h: i32, planes: u16, bits: u16, comp: u32, img: u32, xp: i32, yp: i32, used: u32, imp: u32, pal: u32 }
#[repr(C)] struct Blend { op: u8, flags: u8, alpha: u8, fmt: u8 }
#[link(name = "user32")] extern "system" {
    fn RegisterClassW(c: *const Wc) -> u16; fn DefWindowProcW(h: isize, m: u32, w: usize, l: isize) -> isize;
    fn CreateWindowExW(ex: u32, cls: *const u16, n: *const u16, st: u32, x: i32, y: i32, w: i32, h: i32, p: isize, m: isize, i: isize, a: isize) -> isize;
    fn SetWindowPos(h: isize, after: isize, x: i32, y: i32, w: i32, h2: i32, f: u32) -> i32; fn GetWindowRect(h: isize, r: *mut Rect) -> i32;
    fn IsIconic(h: isize) -> i32; fn IsWindowVisible(h: isize) -> i32; fn ShowWindow(h: isize, c: i32) -> i32;
    fn UpdateLayeredWindow(h: isize, dd: isize, pd: *const Pt, sz: *const Pt, ds: isize, ps: *const Pt, key: u32, b: *const Blend, f: u32) -> i32;
}
#[link(name = "gdi32")] extern "system" {
    fn CreateCompatibleDC(d: isize) -> isize; fn DeleteDC(d: isize) -> i32; fn SelectObject(d: isize, o: isize) -> isize; fn DeleteObject(o: isize) -> i32;
    fn CreateDIBSection(d: isize, bi: *const Bih, u: u32, bits: *mut *mut u8, s: isize, o: u32) -> isize;
}
#[link(name = "comctl32")] extern "system" {
    fn SetWindowSubclass(h: isize, p: usize, id: usize, data: usize) -> i32; fn DefSubclassProc(h: isize, m: u32, w: usize, l: isize) -> isize;
}
#[link(name = "kernel32")] extern "system" { fn GetModuleHandleW(n: *const u16) -> isize; }

fn w(s: &str) -> Vec<u16> { s.encode_utf16().chain(Some(0)).collect() }

unsafe extern "system" fn sub(h: isize, m: u32, wp: usize, lp: isize, _: usize, _: usize) -> isize {
    let r = DefSubclassProc(h, m, wp, lp);
    if m == 0x0047 { sync(); } // WM_WINDOWPOSCHANGED: follow moves, z-order, minimise/restore
    r
}

/// Call on the UI thread once the main window exists.
pub fn init(main: isize) {
    unsafe {
        let cls = w("AoE4SpotifyShadow");
        let wc = Wc { style: 0, proc_: DefWindowProcW as *const () as usize, cls: 0, wnd: 0, inst: GetModuleHandleW(std::ptr::null()), icon: 0, cur: 0, bg: 0, menu: std::ptr::null(), name: cls.as_ptr() };
        RegisterClassW(&wc);
        // LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE, WS_POPUP
        let sh = CreateWindowExW(0x80000 | 0x20 | 0x80 | 0x0800_0000, cls.as_ptr(), w("").as_ptr(), 0x8000_0000, 0, 0, 1, 1, 0, 0, wc.inst, 0);
        MAIN.store(main, Ordering::SeqCst); SHADOW.store(sh, Ordering::SeqCst);
        SetWindowSubclass(main, sub as *const () as usize, 1, 0);
    }
}

fn sync() {
    let (m, sh) = (MAIN.load(Ordering::SeqCst), SHADOW.load(Ordering::SeqCst));
    if m == 0 || sh == 0 { return; }
    let (x, y, fw, _, mg) = *FRAME.lock().unwrap();
    unsafe {
        if fw == 0 || IsIconic(m) != 0 || IsWindowVisible(m) == 0 { ShowWindow(sh, 0); return; }
        let mut r = Rect { l: 0, t: 0, r: 0, b: 0 }; GetWindowRect(m, &mut r);
        // directly behind the panel; NOSIZE|NOACTIVATE|SHOWWINDOW|NOOWNERZORDER
        SetWindowPos(sh, m, r.l + x - mg, r.t + y - mg, 0, 0, 0x1 | 0x10 | 0x40 | 0x200);
    }
}

fn erfc(x: f64) -> f64 { // Abramowitz-Stegun 7.1.26
    let z = x.abs(); let t = 1.0 / (1.0 + 0.3275911 * z);
    let y = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * (-z * z).exp();
    if x >= 0.0 { y } else { 2.0 - y }
}

/// New frame rect (client physical px) + scale; repaints the shadow bitmap when the size changes.
pub fn set_frame(x: i32, y: i32, fw: i32, fh: i32, k: f64) {
    let sh = SHADOW.load(Ordering::SeqCst); if sh == 0 { return; }
    let mg = (24.0 * k).round() as i32;
    let changed = { let mut f = FRAME.lock().unwrap(); let c = f.2 != fw || f.3 != fh || f.4 != mg; *f = (x, y, fw, fh, mg); c };
    if changed {
        let (bw, bh) = (fw + 2 * mg, fh + 2 * mg);
        let (sig, dy, rad, a0) = (7.0 * k, 3.0 * k, 8.0 * k, 0.30);
        let (cx, cy) = (bw as f64 / 2.0, bh as f64 / 2.0 + dy);
        let (hx, hy) = (fw as f64 / 2.0 - rad, fh as f64 / 2.0 - rad);
        unsafe {
            let dc = CreateCompatibleDC(0);
            let bi = Bih { size: 40, w: bw, h: -bh, planes: 1, bits: 32, comp: 0, img: 0, xp: 0, yp: 0, used: 0, imp: 0, pal: 0 };
            let mut bits: *mut u8 = std::ptr::null_mut();
            let bmp = CreateDIBSection(dc, &bi, 0, &mut bits, 0, 0);
            if bmp != 0 && !bits.is_null() {
                let px = std::slice::from_raw_parts_mut(bits, (bw * bh * 4) as usize);
                for j in 0..bh { for i in 0..bw {
                    let inside = i >= mg && i < mg + fw && j >= mg && j < mg + fh;
                    let a = if inside { 0.0 } else {
                        let qx = ((i as f64 + 0.5) - cx).abs() - hx; let qy = ((j as f64 + 0.5) - cy).abs() - hy;
                        let d = (qx.max(0.0).powi(2) + qy.max(0.0).powi(2)).sqrt() + qx.max(qy).min(0.0) - rad;
                        a0 * 0.5 * erfc(d / (sig * std::f64::consts::SQRT_2))
                    };
                    let o = ((j * bw + i) * 4) as usize; px[o] = 0; px[o + 1] = 0; px[o + 2] = 0; px[o + 3] = (a * 255.0).round() as u8;
                }}
                let old = SelectObject(dc, bmp);
                let sz = Pt { x: bw, y: bh }; let z = Pt { x: 0, y: 0 }; let bl = Blend { op: 0, flags: 0, alpha: 255, fmt: 1 };
                UpdateLayeredWindow(sh, 0, std::ptr::null(), &sz, dc, &z, 0, &bl, 2);
                SelectObject(dc, old); DeleteObject(bmp);
            }
            DeleteDC(dc);
        }
    }
    sync();
}