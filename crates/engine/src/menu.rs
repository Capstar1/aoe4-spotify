//! Cog menu rows (1.0.9 behaviour, Tauri 1.1 `menu`).
use crate::{Engine, sys};
use std::sync::atomic::Ordering;
use std::time::Duration;

/// kind: pl:<22-char id> | github | dashboard | account | log | replays | uninstall. Returns a message to show ("" = none).
pub fn menu(app: &Engine, kind: &str) -> String {
    match kind {
        k if k.starts_with("pl:") => { let id: String = k[3..].chars().filter(|c| c.is_ascii_alphanumeric()).collect(); if id.len() == 22 { sys::open_path(&format!("spotify:playlist:{id}")); } String::new() }
        "github" => { sys::open_path("https://github.com/Capstar1/aoe4-spotify"); String::new() }
        "dashboard" => { sys::open_path("https://developer.spotify.com/dashboard"); String::new() }
        "account" => { sys::open_path("https://www.spotify.com/account/overview/"); String::new() }
        "log" => { let p = app.dir.join("aoe4_spotify.log"); let _ = std::fs::create_dir_all(&app.dir);
                   if !p.exists() { let _ = std::fs::write(&p, ""); } sys::open_path(&p.display().to_string()); String::new() }
        "replays" => { let v = !app.replays.load(Ordering::SeqCst); app.replays.store(v, Ordering::SeqCst); aoe4core::userstore::set_replays(&app.dir, v); String::new() }
        "finish" => { let v = !app.finish.load(Ordering::SeqCst); app.finish.store(v, Ordering::SeqCst); aoe4core::userstore::set_finish_song(&app.dir, v); String::new() }
        "uninstall" => {
            let dry = std::env::var_os("AOE4S_DRYOPEN").is_some();
            let unins = sys::install_dir().join("unins000.exe");
            if unins.is_file() && !dry { let _ = std::process::Command::new(&unins).spawn(); return String::new(); }
            if sys::installed() && !dry {
                if let Ok(exe) = std::env::current_exe() { let _ = std::process::Command::new(exe).arg("--uninstall").spawn(); std::thread::spawn(|| { std::thread::sleep(Duration::from_millis(300)); std::process::exit(0) }); }
                return String::new();
            }
            let msg = "Uninstaller not found (not installed?).";
            if !dry { std::thread::spawn(move || sys::msgbox(msg, "Uninstall")); }
            msg.into()
        }
        _ => String::new(),
    }
}
