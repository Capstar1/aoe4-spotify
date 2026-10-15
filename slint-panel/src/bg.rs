//! Headless switcher (Steam launch and `--attach`). No window. The panel never starts the watcher.
//! `AOE4S_NOWATCH` is a panel test switch and is ignored here: a child inherits the panel's environment.
use aoe4core::switcher::Action;
use aoe4engine::{run::WatchOpts, updater, Engine};
use aoe4winsys::launcher;
use std::path::Path;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime};

/// Follow one game session, then hand Spotify back, restore the game-music mute, and install a pending update.
/// The switcher mutex is already held (startup / start_game). Do not take it again.
pub fn run(dir: &Path, attach: bool) {
    aoe4core::appvol::restore_after_crash();
    let (eng, rx, log_path) = Engine::new(dir.to_path_buf());
    let logged = eng.spotify.lock().unwrap().logged_in();
    if attach {
        if !launcher::aoe_running() { return; }
        if !logged {
            launcher::log("Age of Empires IV is running but you are not logged in to Spotify - switcher not attached");
            return;
        }
        launcher::log("Age of Empires IV already running - attaching the music switcher");
    } else if !logged {
        launcher::log("Not logged in to Spotify - log in from the AoE4 Spotify panel and the music will follow");
    }
    // Steam sets this before the game process is up: a log older than launched_at belongs to the previous session.
    let skip = if attach { None } else { Some(SystemTime::now().checked_sub(Duration::from_secs(2)).unwrap_or(SystemTime::UNIX_EPOCH)) };
    let t0 = Instant::now();
    while !launcher::aoe_running() {
        if t0.elapsed().as_secs() > 300 { launcher::log("Age of Empires IV did not start within 5 minutes - exiting"); return; }
        std::thread::sleep(Duration::from_secs(3));
    }
    launcher::log("Age of Empires IV is running");
    let e = eng.clone();
    std::thread::spawn(move || { std::thread::sleep(Duration::from_secs(8)); updater::auto_update(e); });
    eng.start(rx, log_path, WatchOpts { skip_older_than: skip });
    while launcher::aoe_running() { std::thread::sleep(Duration::from_secs(3)); }
    launcher::log("Age of Empires IV closed - exiting");
    eng.stop.store(true, Ordering::Relaxed);
    std::thread::sleep(Duration::from_millis(600));
    {
        let mut s = eng.status.lock().unwrap();
        s.in_match = false; s.age = None; s.playing = None;
    }
    aoe4core::userstore::clear_now(&eng.dir);
    eng.restore_done.store(false, Ordering::SeqCst);
    if eng.tx.lock().unwrap().send(Action::Restore).is_ok() {
        // 5 s each way, plus a switch already in flight, fits under this. A stuck call still lets the process exit.
        let t0 = Instant::now();
        while !eng.restore_done.load(Ordering::SeqCst) && t0.elapsed() < Duration::from_secs(30) {
            std::thread::sleep(Duration::from_millis(50));
        }
    }
    launcher::music_sync(launcher::enabled_now());
    std::thread::sleep(Duration::from_secs(3));
    eng.status.lock().unwrap().in_match = false;
    aoe4core::userstore::clear_now(&eng.dir);
    updater::install_pending(&eng);
}

static PANEL_VISIBLE: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
/// The panel window is on screen (shown, and not minimized). The attach check reads this from its own thread.
pub fn set_panel_visible(on: bool) { PANEL_VISIBLE.store(on, Ordering::Relaxed); }

/// While the panel process is alive: if the game is up, enabled, and logged in, and no switcher is listening, spawn `--attach`.
/// One try per game session (a failed attach is not respawned until the game process is gone).
/// The process snapshot runs only while the panel is visible.
pub fn panel_attach(eng: Arc<Engine>) {
    let mut spawned = false;
    // The Steam launch takes the switcher mutex just after the game process appears. Wait one pass
    // so that launch wins, and only then spawn --attach if nobody is listening.
    let mut armed = false;
    loop {
        if PANEL_VISIBLE.load(Ordering::Relaxed) {
            if !launcher::aoe_running() {
                spawned = false; armed = false;
            } else if launcher::switcher_running() {
                spawned = true; armed = true;
            } else if !spawned && !armed {
                armed = true;
            } else if !spawned {
                let enabled = eng.settings.lock().unwrap().enabled;
                let logged = match eng.spotify.try_lock() { Ok(s) => s.logged_in(), Err(_) => eng.logged.load(Ordering::SeqCst) };
                if enabled && logged && spawn_attach() { spawned = true; }
            }
        }
        std::thread::sleep(Duration::from_secs(3));
    }
}

fn spawn_attach() -> bool {
    let Ok(exe) = std::env::current_exe() else { return false };
    use std::os::windows::process::CommandExt;
    std::process::Command::new(exe).arg("--attach").creation_flags(0x0800_0000).spawn().is_ok()
}
