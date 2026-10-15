//! Panel placement: centred on the screen when it opens, and page switches (main <-> Age Intros) that grow or shrink
//! the window around its horizontal centre (1.0.9 / Tauri 1.1 behaviour), always inside the monitor's work area.
//! The maths is pure (unit-tested); the Win32 calls apply it.

/// A screen rectangle in physical pixels: left, top, right, bottom.
#[repr(C)] #[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Rect { pub l: i32, pub t: i32, pub r: i32, pub b: i32 }

/// Keep a w x h window inside the work area (top-left wins when it is bigger than the area).
fn clamp(x: i32, y: i32, w: i32, h: i32, wa: Rect) -> (i32, i32) { (x.min(wa.r - w).max(wa.l), y.min(wa.b - h).max(wa.t)) }

/// Top-left that centres a w x h window in the work area.
pub fn centred(w: i32, h: i32, wa: Rect) -> (i32, i32) { clamp(wa.l + (wa.r - wa.l - w) / 2, wa.t + (wa.b - wa.t - h) / 2, w, h, wa) }

/// Top-left after resizing the window `old` to w x h: same horizontal centre, same top.
pub fn regrow(old: Rect, w: i32, h: i32, wa: Rect) -> (i32, i32) {
    let cx2 = old.l + old.r;   // twice the centre: no rounding drift when toggling back and forth
    clamp((cx2 - w).div_euclid(2), old.t, w, h, wa)
}

#[cfg(windows)]
mod win {
    use super::Rect;
    #[repr(C)] struct Mi { size: u32, mon: Rect, work: Rect, flags: u32 }
    #[repr(C)] struct Pt { x: i32, y: i32 }
    #[link(name = "user32")] extern "system" {
        fn GetCursorPos(p: *mut Pt) -> i32; fn MonitorFromPoint(p: Pt, f: u32) -> isize; fn MonitorFromWindow(h: isize, f: u32) -> isize;
        fn GetMonitorInfoW(m: isize, i: *mut Mi) -> i32; fn GetWindowRect(h: isize, r: *mut Rect) -> i32;
        fn SetWindowPos(h: isize, after: isize, x: i32, y: i32, w: i32, h2: i32, f: u32) -> i32;
    }
    #[link(name = "shcore")] extern "system" { fn GetDpiForMonitor(m: isize, t: u32, x: *mut u32, y: *mut u32) -> i32; }
    fn info(m: isize) -> Option<(Rect, f32)> {
        let mut i = Mi { size: std::mem::size_of::<Mi>() as u32, mon: Rect { l: 0, t: 0, r: 0, b: 0 }, work: Rect { l: 0, t: 0, r: 0, b: 0 }, flags: 0 };
        if m == 0 || unsafe { GetMonitorInfoW(m, &mut i) } == 0 { return None; }
        let (mut dx, mut dy) = (96u32, 96u32);
        let s = if unsafe { GetDpiForMonitor(m, 0, &mut dx, &mut dy) } == 0 && dx > 0 { dx as f32 / 96.0 } else { 1.0 };
        Some((i.work, s))
    }
    /// Work area and DPI scale of the monitor under the cursor (else the primary one).
    pub fn cursor_monitor() -> Option<(Rect, f32)> {
        let mut p = Pt { x: 0, y: 0 }; unsafe { GetCursorPos(&mut p) };
        info(unsafe { MonitorFromPoint(p, 1) })   // MONITOR_DEFAULTTOPRIMARY
    }
    pub fn window_rect(h: isize) -> Option<(Rect, Rect)> {
        let mut r = Rect { l: 0, t: 0, r: 0, b: 0 };
        if h == 0 || unsafe { GetWindowRect(h, &mut r) } == 0 { return None; }
        Some((r, info(unsafe { MonitorFromWindow(h, 2) })?.0))   // MONITOR_DEFAULTTONEAREST
    }
    /// Move and size in one step (no frame at the old place with the new size).
    pub fn place(h: isize, x: i32, y: i32, w: i32, hh: i32) { unsafe { SetWindowPos(h, 0, x, y, w, hh, 0x4 | 0x10) }; }   // NOZORDER | NOACTIVATE
}

/// Before the panel's first show: centre it on the cursor's (or the primary) monitor at that monitor's DPI.
#[cfg(windows)]
pub fn centre_panel(ui: &crate::Panel) {
    use slint::ComponentHandle;
    let Some((wa, s)) = win::cursor_monitor() else { return };
    let (w, h) = ((ui.get_win_w() * s).round() as i32, (ui.get_win_h() * s).round() as i32);
    let (x, y) = centred(w, h, wa);
    ui.window().set_position(slint::PhysicalPosition::new(x, y));
}
#[cfg(not(windows))]
pub fn centre_panel(_: &crate::Panel) {}

/// After a page switch: if the panel's size changes, resize it around its horizontal centre in one native step.
#[cfg(windows)]
pub fn regrow_panel(ui: &crate::Panel) {
    use slint::ComponentHandle;
    let Some((old, wa)) = win::window_rect(crate::panel_hwnd()) else { return };
    let s = ui.window().scale_factor();
    let (w, h) = ((ui.get_win_w() * s).round() as i32, (ui.get_win_h() * s).round() as i32);
    if w == old.r - old.l && h == old.b - old.t { return; }
    let (x, y) = regrow(old, w, h, wa);
    win::place(crate::panel_hwnd(), x, y, w, h);
}
#[cfg(not(windows))]
pub fn regrow_panel(_: &crate::Panel) {}

#[cfg(test)]
mod tests {
    use super::*;
    const WA: Rect = Rect { l: 0, t: 0, r: 1920, b: 1040 };
    #[test] fn centres() { assert_eq!(centred(432, 900, WA), (744, 70)); assert_eq!(centred(432, 2000, WA), (744, 0)); }
    #[test] fn centres_on_second_monitor() { let wa = Rect { l: 1920, t: 0, r: 4480, b: 1400 }; assert_eq!(centred(648, 1200, wa), (1920 + 956, 100)); }
    #[test] fn grows_and_shrinks_around_centre() {
        let a = Rect { l: 700, t: 50, r: 1132, b: 950 };
        let (x, y) = regrow(a, 522, 980, WA); assert_eq!((x, y), (655, 50));
        let b = Rect { l: x, t: y, r: x + 522, b: y + 980 };
        assert_eq!(regrow(b, 432, 900, WA), (700, 50));   // back where it was
    }
    #[test] fn stays_in_work_area() {
        assert_eq!(regrow(Rect { l: 0, t: 50, r: 432, b: 950 }, 522, 980, WA), (0, 50));
        assert_eq!(regrow(Rect { l: 1488, t: 100, r: 1920, b: 1000 }, 522, 1000, WA), (1398, 40));
    }
}
