#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
//! M1 shell: one fixed-size window; the core follows the game log and logs what it WOULD play (dry run).
use aoe4core::aoe4::Aoe4;
use aoe4core::game::{GameAdapter, GameEvent};
use aoe4core::logtail::{Poll, Tail};
use aoe4core::settings::{self, Settings};
use aoe4core::switcher::{Action, Switcher};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Default, serde::Serialize, Clone)]
struct Status { game: String, log_path: String, watching: bool, in_match: bool, age: Option<String>, playing: Option<String>, log: Vec<String> }

struct AppState { settings: Settings, ages: Vec<(String, String)>, status: Mutex<Status> }

fn now() -> String {
    let s = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) + 2 * 3600;   // Oslo summer time (M1)
    format!("{:02}:{:02}:{:02}", (s / 3600) % 24, (s / 60) % 60, s % 60)
}

fn push(st: &Mutex<Status>, line: String) {
    let mut s = st.lock().unwrap(); s.log.push(format!("{} {}", now(), line));
    let n = s.log.len(); if n > 200 { s.log.drain(..n - 200); }
}

fn watch(app: Arc<AppState>, path: PathBuf) {
    let la = std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap_or_default();
    let crc = la.join(r"Documents\My Games\Age of Empires IV\LogFiles");
    let mut game = Aoe4::new(Aoe4::datacrc_resolver(crc));
    let s = &app.settings;
    let mut sw = Switcher::new(s.enabled, s.fade_seconds, s.playlists.clone());
    let mut tail = Tail::new(path.clone());
    // catch-up: read what is already there silently (learn who you are), act only on new lines
    let mut catching = true;
    loop {
        let (lines, restarted) = match tail.poll() {
            Poll::Lines(v) => (v, false), Poll::Restarted(v) => (v, true),
            Poll::Missing => { app.status.lock().unwrap().watching = false; std::thread::sleep(Duration::from_secs(2)); continue; }
        };
        if restarted { game.reset_session(); push(&app.status, "Game log recreated (new game session)".into()); }
        app.status.lock().unwrap().watching = true;
        for l in lines {
            for ev in game.feed(&l) {
                if catching { continue; }
                push(&app.status, format!("event: {}", serde_json::to_string(&ev).unwrap_or_default()));
                match &ev {
                    GameEvent::MatchStart { .. } => app.status.lock().unwrap().in_match = true,
                    GameEvent::MatchEnd { .. } | GameEvent::Replay => { let mut s = app.status.lock().unwrap(); s.in_match = false; s.age = None; }
                    GameEvent::Age { key, .. } => app.status.lock().unwrap().age = Some(key.clone()),
                    _ => {}
                }
                for a in sw.on_event(&ev) {
                    match a {
                        Action::Play { age, uri, fade_s } => { push(&app.status, format!("would play {uri} for {age} (fade {fade_s}s) [dry run]")); app.status.lock().unwrap().playing = Some(uri); }
                        Action::Restore => { push(&app.status, "would restore your previous music [dry run]".into()); app.status.lock().unwrap().playing = None; }
                    }
                }
            }
        }
        if catching { catching = false; push(&app.status, format!("Watching {}", path.display())); }
        std::thread::sleep(Duration::from_millis(250));
    }
}

#[tauri::command]
fn get_state(app: tauri::State<Arc<AppState>>) -> serde_json::Value {
    let st = app.status.lock().unwrap().clone();
    serde_json::json!({ "settings": app.settings, "ages": app.ages, "status": st })
}

fn main() {
    let settings = settings::load_installed();
    let probe = Aoe4::new(Box::new(|_, _| None));
    let path = settings.log_path.clone().map(PathBuf::from).or_else(|| probe.default_log_path()).unwrap_or_default();
    let ages = probe.ages().iter().map(|(k, l)| (k.to_string(), l.to_string())).collect();
    let status = Status { game: probe.label().into(), log_path: path.display().to_string(), ..Default::default() };
    let app = Arc::new(AppState { settings, ages, status: Mutex::new(status) });
    let a2 = app.clone(); std::thread::spawn(move || watch(a2, path));
    tauri::Builder::default()
        .manage(app)
        .invoke_handler(tauri::generate_handler![get_state])
        .run(tauri::generate_context!())
        .expect("error while running AoE4 Spotify");
}