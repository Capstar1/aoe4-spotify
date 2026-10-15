//! Start-up modes, exactly as the Tauri 1.1 main(): Steam launch (%command%), --set/--remove-launch-option,
//! --uninstall, --attach, --migrate-109, --updated, --panel; one switcher per user; 1.0.9 import on every start.
use std::path::Path;

pub struct Start { pub hidden: bool, pub login_first: bool, pub attach: bool }

/// None = this process is done (mode handled, or another instance took over).
pub fn startup(dir: &Path) -> Option<Start> {
    if std::env::args().nth(1).as_deref() != Some("--migrate-109") { aoe4engine::data::import_109(dir); }
    let login_first = std::env::args().nth(1).is_none();   // started by hand / installer Finish: log in first, then "You're good to go"
    #[cfg(windows)] {
        use aoe4winsys::{launcher, signal};
        let settings = aoe4core::settings::load_own(dir);
        let mut hidden = false;
        let mut attach = false;
        match launcher::mode(settings.enabled) {
            launcher::Mode::Done => return None,
            launcher::Mode::Migrate(inst, cleanup) => { std::process::exit(if aoe4engine::data::migrate_109(dir, inst, cleanup).is_ok() { 0 } else { 2 }); }
            launcher::Mode::Attach => { if !launcher::aoe_running() || !settings.enabled || !launcher::single_instance() { return None; } hidden = true; attach = true; }
            launcher::Mode::Game(args) => {
                if !launcher::start_game(&args, settings.enabled) { return None; }
                hidden = true;     // headless switcher: no window. The panel is a separate process.
                for (k, _) in std::env::vars() { let l = k.to_lowercase(); if l.starts_with("steam") || l.starts_with("enable_vk_layer_valve") { std::env::remove_var(k); } }   // only the game gets Steam's variables
            }
            launcher::Mode::Panel => { if !launcher::panel_lock() { if !signal::ask_show() { signal::show_window_titled("AoE4 Spotify"); } return None; } launcher::register_uninstall(); }
        }
        Some(Start { hidden, login_first, attach })
    }
    #[cfg(not(windows))] { Some(Start { hidden: false, login_first, attach: false }) }
}
