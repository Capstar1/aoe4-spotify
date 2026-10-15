//! No white first frame: Windows drops what Slint pre-renders into the still-hidden window, so DWM would show an
//! unpainted (white) surface for a frame. The panel is cloaked the moment it is shown (WM_SHOWWINDOW, caught by a
//! thread hook), painted synchronously at its final place and size, and only then uncloaked.
use std::cell::Cell;
#[repr(C)] struct Cwp { lp: isize, wp: usize, msg: u32, h: isize }
#[link(name = "user32")] extern "system" {
    fn SetWindowsHookExW(id: i32, f: unsafe extern "system" fn(i32, usize, isize) -> isize, m: isize, t: u32) -> isize;
    fn UnhookWindowsHookEx(h: isize) -> i32; fn CallNextHookEx(h: isize, c: i32, w: usize, l: isize) -> isize;
    fn RedrawWindow(h: isize, r: *const crate::geom::Rect, rgn: isize, f: u32) -> i32; fn GetParent(h: isize) -> isize;
}
#[link(name = "kernel32")] extern "system" { fn GetCurrentThreadId() -> u32; }
#[link(name = "dwmapi")] extern "system" { fn DwmSetWindowAttribute(h: isize, a: u32, v: *const u32, n: u32) -> i32; fn DwmFlush() -> i32; }
thread_local! { static HOOK: Cell<isize> = const { Cell::new(0) }; static WIN: Cell<isize> = const { Cell::new(0) }; }
fn cloak(h: isize, on: bool) { let v: u32 = on as u32; unsafe { DwmSetWindowAttribute(h, 13, &v, 4) }; }   // DWMWA_CLOAK
unsafe extern "system" fn proc(c: i32, w: usize, l: isize) -> isize {
    if c >= 0 { let m = &*(l as *const Cwp); if m.msg == 0x18 && m.wp != 0 && GetParent(m.h) == 0 && WIN.with(|x| x.get()) == 0 { cloak(m.h, true); WIN.with(|x| x.set(m.h)); slint::Timer::single_shot(std::time::Duration::ZERO, reveal); } }
    CallNextHookEx(0, c, w, l)
}
/// Before the first show(): cloak whatever top-level window this thread shows next.
pub fn arm() { let h = unsafe { SetWindowsHookExW(4, proc, 0, GetCurrentThreadId()) }; HOOK.with(|x| x.set(h)); }   // WH_CALLWNDPROC
/// Right after the window became visible (cloaked; Slint creates it lazily once the event loop runs): paint now (synchronous WM_PAINT -> Slint renders), wait for DWM to take it, uncloak.
fn reveal() {
    let k = HOOK.with(|x| x.replace(0)); if k != 0 { unsafe { UnhookWindowsHookEx(k) }; }
    let h = WIN.with(|x| x.get()); if h == 0 { return; }
    unsafe { RedrawWindow(h, std::ptr::null(), 0, 0x1 | 0x100); DwmFlush(); }   // RDW_INVALIDATE | RDW_UPDATENOW
    cloak(h, false);
    if std::env::var_os("AOE4S_TIMING").is_some() { aoe4engine::sys::log("timing: first frame painted before uncloak"); }
}
