//! "Show the panel" between instances: a panel started while a game-launched (hidden) switcher runs signals it
//! instead of starting a second switcher. Named auto-reset event (per user session, + AOE4S_MUTEX_SUFFIX for tests).
#[link(name = "kernel32")] extern "system" {
    fn CreateEventW(a: *const u8, manual: i32, initial: i32, n: *const u16) -> isize;
    fn OpenEventW(access: u32, inherit: i32, n: *const u16) -> isize;
    fn SetEvent(h: isize) -> i32;
    fn WaitForSingleObject(h: isize, ms: u32) -> u32;
    fn CloseHandle(h: isize) -> i32;
}
fn name() -> Vec<u16> { format!("AoE4Spotify11ShowPanel{}", std::env::var("AOE4S_MUTEX_SUFFIX").unwrap_or_default()).encode_utf16().chain(Some(0)).collect() }
/// Running switcher: call `f` every time another instance asks for the panel (blocks; run on its own thread).
pub fn serve(f: impl Fn()) {
    let h = unsafe { CreateEventW(std::ptr::null(), 0, 0, name().as_ptr()) }; if h == 0 { return; }
    loop { if unsafe { WaitForSingleObject(h, 0xFFFF_FFFF) } == 0 { f(); } else { std::thread::sleep(std::time::Duration::from_millis(500)); } }
}
/// Second instance: ask the running one to show its panel. False when none is listening (e.g. a Tauri 1.1 switcher).
pub fn ask_show() -> bool {
    unsafe { let h = OpenEventW(0x0002, 0, name().as_ptr()); if h == 0 { return false; } let ok = SetEvent(h) != 0; CloseHandle(h); ok }   // EVENT_MODIFY_STATE
}
/// Show `h`, or restore it when it is minimized, then bring it forward.
pub fn reveal_hwnd(h: isize) {
    #[link(name = "user32")] extern "system" { fn IsIconic(h: isize) -> i32; fn ShowWindow(h: isize, c: i32) -> i32; fn SetForegroundWindow(h: isize) -> i32; }
    if h == 0 { return; }
    unsafe { if IsIconic(h) != 0 { ShowWindow(h, 9); } else { ShowWindow(h, 5); } SetForegroundWindow(h); }
}
/// Older switchers (Tauri 1.1) have a window titled "AoE4 Spotify": show it.
pub fn show_window_titled(t: &str) {
    #[link(name = "user32")] extern "system" { fn FindWindowW(c: *const u16, t: *const u16) -> isize; fn IsIconic(h: isize) -> i32; fn ShowWindow(h: isize, c: i32) -> i32; fn SetForegroundWindow(h: isize) -> i32; }
    let t: Vec<u16> = t.encode_utf16().chain(Some(0)).collect();
    unsafe { let h = FindWindowW(std::ptr::null(), t.as_ptr()); if h != 0 { if IsIconic(h) != 0 { ShowWindow(h, 9); } else { ShowWindow(h, 5); } SetForegroundWindow(h); } }
}
