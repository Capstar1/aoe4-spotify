//! Platform seam: Windows uses aoe4winsys (Steam, registry, processes, game config); elsewhere harmless stand-ins
//! so the engine builds and its tests run on any OS.
use std::path::PathBuf;
pub fn data_dir() -> PathBuf { aoe4core::userstore::data_dir() }
/// %APPDATA%\AoE4Spotify-1.1\aoe4_spotify.log (1.0.9: the app's own log file).
pub fn log(m: &str) {
    #[cfg(windows)] { aoe4winsys::launcher::log(m) }
    #[cfg(not(windows))] { use std::io::Write; let d = data_dir(); let _ = std::fs::create_dir_all(&d);
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(d.join("aoe4_spotify.log")) { let _ = writeln!(f, "{m}"); } }
}
pub fn test_env(name: &str) -> Option<String> { if std::env::var("AOE4S_TEST").ok().as_deref() != Some("1") { return None; } std::env::var(name).ok().filter(|s| !s.is_empty()) }
pub fn install_dir() -> PathBuf { std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())).unwrap_or_default() }
pub fn aoe_running() -> bool { #[cfg(windows)] { aoe4winsys::launcher::aoe_running() } #[cfg(not(windows))] { false } }
pub fn music_sync(_on: bool) { #[cfg(windows)] { aoe4winsys::launcher::music_sync(_on); } }
pub fn installed() -> bool { #[cfg(windows)] { aoe4winsys::launcher::installed() } #[cfg(not(windows))] { false } }
/// Open a URL / file / spotify: URI (AOE4S_DRYOPEN=<file>: only note it there - tests).
pub fn open_path(p: &str) {
    if let Some(f) = std::env::var_os("AOE4S_DRYOPEN") { use std::io::Write; if let Ok(mut h) = std::fs::OpenOptions::new().create(true).append(true).open(f) { let _ = writeln!(h, "{p}"); } return; }
    let _ = aoe4core::os::open(p);
}
/// Message box (Windows), stderr elsewhere.
pub fn msgbox(text: &str, title: &str) {
    #[cfg(windows)] {
        #[link(name = "user32")] extern "system" { fn MessageBoxW(h: isize, t: *const u16, c: *const u16, f: u32) -> i32; }
        let w = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
        unsafe { MessageBoxW(0, w(text).as_ptr(), w(title).as_ptr(), 0x40 | 0x40000); }
    }
    #[cfg(not(windows))] { eprintln!("{title}: {text}"); }
}
