#![windows_subsystem = "windows"]
//! M1 shell: one fixed-size window; the core follows the game log. Real playback is OFF by default (dry run)
//! so 1.1 never fights the 1.0.9 app over Spotify; the toggle is saved in %APPDATA%\AoE4Spotify-1.1.
use aoe4core::aoe4::Aoe4;
use aoe4core::game::{GameAdapter, GameEvent};
use aoe4core::logtail::{Poll, Tail};
use aoe4core::settings::{self, Settings};
use aoe4core::switcher::{Action, Switcher};
use aoe4core::spotify::Spotify;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Sender};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Default, serde::Serialize, Clone)]
struct Status { game: String, log_path: String, watching: bool, in_match: bool, age: Option<String>, playing: Option<String>, log: Vec<String> }

struct AppState { settings: Settings, ages: Vec<(String, String)>, status: Mutex<Status>, real: AtomicBool, replays: AtomicBool, busy: AtomicBool, spotify: Mutex<Spotify>, tx: Mutex<Sender<Action>>, dir: PathBuf }

fn save_prefs(app: &AppState) {
    let _ = std::fs::create_dir_all(&app.dir);
    let _ = std::fs::write(app.dir.join("settings.json"), serde_json::json!({ "real_playback": app.real.load(Ordering::SeqCst), "music_in_replays": app.replays.load(Ordering::SeqCst) }).to_string());
}

/// Spotify worker: actions run one after another so fades never overlap and the log watcher never blocks.
fn player(app: Arc<AppState>, rx: std::sync::mpsc::Receiver<Action>) {
    for a in rx {
        let r = { let mut sp = app.spotify.lock().unwrap(); match &a {
            Action::Play { age, uri, fade_s } => sp.play_age(uri, *fade_s).map(|_| format!("playing {uri} for {age}")),
            Action::Restore => sp.restore(app.settings.fade_seconds),
        } };
        push(&app.status, match r { Ok(m) => format!("Spotify: {m}"), Err(e) => format!("Spotify error: {e}") });
    }
}

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
                    GameEvent::MatchResult { result } => push(&app.status, (if *result == 1 { "Result: victory" } else { "Result: defeat" }).into()),
                    GameEvent::MatchEnd { .. } | GameEvent::Replay => { let mut s = app.status.lock().unwrap(); s.in_match = false; s.age = None; }
                    GameEvent::Age { key, .. } => app.status.lock().unwrap().age = Some(key.clone()),
                    _ => {}
                }
                for a in sw.on_event(&ev) {
                    match a {
                        Action::Play { age, uri, fade_s } => {
                            app.status.lock().unwrap().playing = Some(uri.clone());
                            if app.real.load(Ordering::SeqCst) { let _ = app.tx.lock().unwrap().send(Action::Play { age, uri, fade_s }); }
                            else { push(&app.status, format!("would play {uri} for {age} (fade {fade_s}s) [dry run]")); }
                        }
                        Action::Restore => {
                            app.status.lock().unwrap().playing = None;
                            if app.real.load(Ordering::SeqCst) { let _ = app.tx.lock().unwrap().send(Action::Restore); }
                            else { push(&app.status, "would restore your previous music [dry run]".into()); }
                        }
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
    let logged_in = app.spotify.lock().map(|s| s.logged_in()).ok();
    let keys: Vec<String> = app.ages.iter().map(|(k, _)| k.clone()).collect();
    serde_json::json!({ "settings": app.settings, "ages": app.ages, "status": st, "intros": aoe4core::intros::overview(&app.settings, &keys),
        "spotify": { "logged_in": logged_in, "real": app.real.load(Ordering::SeqCst), "replays": app.replays.load(Ordering::SeqCst), "busy": app.busy.load(Ordering::SeqCst) } })
}

mod win {
    #[repr(C)] #[derive(Default, Clone, Copy)] pub struct Rect { pub l: i32, pub t: i32, pub r: i32, pub b: i32 }
    #[link(name = "user32")] extern "system" {
        pub fn GetWindowRect(h: isize, r: *mut Rect) -> i32;
        pub fn GetClientRect(h: isize, r: *mut Rect) -> i32;
        pub fn SetWindowPos(h: isize, after: isize, x: i32, y: i32, w: i32, hh: i32, f: u32) -> i32;
    }
}

/// Page switch resize, 1.0.9 rules: client becomes w x h (logical px), centred horizontally, title bar stays put.
/// One SetWindowPos so size and position change in the same step.
#[tauri::command]
fn resize(window: tauri::WebviewWindow, w: f64, h: f64) {
    let hwnd = window.hwnd().map(|x| x.0 as isize).unwrap_or(0);
    let k = window.scale_factor().unwrap_or(1.0) * zoom();
    let (mut o, mut c) = (win::Rect::default(), win::Rect::default());
    unsafe { win::GetWindowRect(hwnd, &mut o); win::GetClientRect(hwnd, &mut c); }
    let (bw, bh) = ((o.r - o.l) - c.r, (o.b - o.t) - c.b);
    let (nw, nh) = ((w * k).round() as i32 + bw, (h * k).round() as i32 + bh);
    let x = o.l + ((o.r - o.l) - nw) / 2;
    unsafe { win::SetWindowPos(hwnd, 0, x, o.t, nw, nh, 0x0004 | 0x0010); }   // NOZORDER | NOACTIVATE
}

fn zoom() -> f64 { std::env::var("AOE4S_ZOOM").ok().and_then(|s| s.parse().ok()).unwrap_or(1.0) }

fn wall() -> f64 { SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0) }

/// AOE4S_SWITCHTEST=<dir>: drive N page switches for the frame-capture harness, then quit.
fn switch_test(win_: tauri::WebviewWindow, dir: PathBuf) {
    let _ = win_.set_always_on_top(true);
    let _ = win_.set_position(tauri::PhysicalPosition::new(0, 60));   // screen-left: away from other windows
    let _ = win_.eval("document.body.style.pointerEvents=\"none\"");      // test: no hover effects from a resting mouse
    std::thread::sleep(Duration::from_secs(3));
    let hwnd = win_.hwnd().map(|x| x.0 as isize).unwrap_or(0);
    let mut o = win::Rect::default(); unsafe { win::GetWindowRect(hwnd, &mut o); }
    let _ = std::fs::write(dir.join("rect.json"), format!("{{\"x\": {}, \"y\": {}}}", o.l, o.t));
    let _ = std::fs::write(dir.join("ready"), "");
    std::thread::sleep(Duration::from_millis(700));
    let n: usize = std::env::var("AOE4S_N").ok().and_then(|s| s.parse().ok()).unwrap_or(60);
    let mut ev = vec![];
    for i in 0..n {
        let name = if i % 2 == 0 { "open" } else { "close" };
        let t0 = wall();
        let _ = win_.eval(if i % 2 == 0 { "go(\"intros\")" } else { "go(\"main\")" });
        std::thread::sleep(Duration::from_millis(60));
        ev.push(format!("[\"{name}\", {t0}]")); ev.push(format!("[\"{name}_end\", {}]", t0 + 0.06));
        std::thread::sleep(Duration::from_millis(390));
    }
    {
        #[repr(C)] struct P { x: i32, y: i32 }
        #[link(name = "user32")] extern "system" { fn WindowFromPoint(p: P) -> isize; fn GetAncestor(h: isize, f: u32) -> isize; }
        let mut o = win::Rect::default(); unsafe { win::GetWindowRect(hwnd, &mut o); }
        let probe = |x: i32, y: i32| unsafe { GetAncestor(WindowFromPoint(P { x: o.l + x, y: o.t + y }), 2) == hwnd };
        let _ = std::fs::write(dir.join("clickthrough.txt"), format!("margin(8,300) ours={} inside(100,300) ours={} right-margin(545,300) ours={}", probe(8, 300), probe(100, 300), probe(545, 300)));
    }
    let _ = std::fs::write(dir.join("events.json"), format!("[{}]", ev.join(",")));
    let _ = std::fs::write(dir.join("done"), "");
    std::thread::sleep(Duration::from_millis(800));
    std::process::exit(0);
}

#[tauri::command]
fn login(app: tauri::State<Arc<AppState>>) {
    if app.busy.swap(true, Ordering::SeqCst) { return; }
    let a = app.inner().clone();
    std::thread::spawn(move || {
        push(&a.status, "Spotify: opening login in your browser...".into());
        let r = a.spotify.lock().unwrap().login();
        push(&a.status, match r { Ok(_) => "Spotify: logged in (1.1 has its own login)".into(), Err(e) => format!("Spotify login: {e}") });
        a.busy.store(false, Ordering::SeqCst);
    });
}

/// Cached 1.0.9 cover (playlist <id>_<snapshot>.jpg newest, or track_<id>.jpg) as a data URL; None if missing.
#[tauri::command]
fn cover(uri: String) -> Option<String> {
    use base64::Engine;
    let dir = PathBuf::from(std::env::var("APPDATA").ok()?).join(r"AoE4Spotify\covers");
    let id = uri.rsplit(':').next()?.to_string();
    if uri.contains(":list:") { let b = std::fs::read(dir.join(format!("list_{id}.png"))).ok()?; return Some(format!("data:image/png;base64,{}", base64::engine::general_purpose::STANDARD.encode(b))); }
    let path = if uri.starts_with("spotify:track:") { dir.join(format!("track_{id}.jpg")) } else {
        std::fs::read_dir(&dir).ok()?.flatten().filter(|e| e.file_name().to_string_lossy().starts_with(&format!("{id}_")))
            .max_by_key(|e| e.metadata().and_then(|m| m.modified()).ok())?.path() };
    let b = std::fs::read(path).ok()?;
    Some(format!("data:image/jpeg;base64,{}", base64::engine::general_purpose::STANDARD.encode(b)))
}

/// Visible part of the (fixed, transparent, borderless) window: everything outside is clipped away and clicks pass through.
#[tauri::command]
fn region(window: tauri::WebviewWindow, x: f64, y: f64, w: f64, h: f64) {
    #[link(name = "gdi32")] extern "system" { fn CreateRectRgn(a: i32, b: i32, c: i32, d: i32) -> isize; }
    #[link(name = "user32")] extern "system" { fn SetWindowRgn(h: isize, r: isize, redraw: i32) -> i32; }
    let hwnd = window.hwnd().map(|v| v.0 as isize).unwrap_or(0);
    let k = window.scale_factor().unwrap_or(1.0) * zoom();
    let r = |v: f64| (v * k).round() as i32;
    unsafe { let rg = CreateRectRgn(r(x), r(y), r(x + w), r(y + h)); SetWindowRgn(hwnd, rg, 1); }
}

#[tauri::command]
fn dbg(window: tauri::WebviewWindow, s: String) {
    let o = window.outer_position().ok(); let i = window.inner_position().ok(); let os = window.outer_size().ok(); let is = window.inner_size().ok();
    let _ = std::fs::write(std::env::temp_dir().join("aoe4s_dbg.txt"), format!("{s}\nouter {o:?} {os:?}\ninner {i:?} {is:?} scale {:?}", window.scale_factor()));
}

fn open_path(p: &str) { use std::os::windows::process::CommandExt; let _ = std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", p]).creation_flags(0x0800_0000).spawn(); }

/// Cog menu rows (1.0.9 behaviour; 1.1 keeps its own files and never writes the 1.0.9 settings).
#[tauri::command]
fn menu(app: tauri::State<Arc<AppState>>, kind: String) -> String {
    match kind.as_str() {
        "github" => { open_path("https://github.com/Capstar1/aoe4-spotify"); String::new() }
        "log" => { let p = app.dir.join("aoe4_spotify_1.1.log"); let _ = std::fs::create_dir_all(&app.dir);
                   let _ = std::fs::write(&p, app.status.lock().unwrap().log.join("\r\n")); open_path(&p.display().to_string()); String::new() }
        "replays" => { let v = !app.replays.load(Ordering::SeqCst); app.replays.store(v, Ordering::SeqCst); save_prefs(&app); String::new() }
        "uninstall" => "Uninstaller not found (not installed?).".into(),   // the 1.1 preview runs from its folder
        _ => String::new(),
    }
}

/// "Check for updates": latest GitHub release vs this version (same endpoint 1.0.9 uses).
#[tauri::command]
async fn check_update() -> String {
    let r = ureq::get("https://api.github.com/repos/Capstar1/aoe4-spotify/releases/latest").set("User-Agent", "aoe4-spotify-1.1").timeout(Duration::from_secs(8)).call();
    let Ok(r) = r else { return "Couldn't check".into() };
    let v: serde_json::Value = r.into_json().unwrap_or_default();
    let tag = v["tag_name"].as_str().unwrap_or("").trim_start_matches(['v', 'V']).to_string();
    let num = |s: &str| s.split('.').map(|x| x.parse::<u32>().unwrap_or(0)).collect::<Vec<_>>();
    if !tag.is_empty() && num(&tag) > num(env!("CARGO_PKG_VERSION")) { format!("\u{2193} Update {tag}") } else { "Up to date".into() }
}

#[tauri::command]
fn cfg() -> serde_json::Value { serde_json::json!({ "order": std::env::var("AOE4S_ORDER").unwrap_or_default(), "pl_closed": std::env::var_os("AOE4S_PL_CLOSED").is_some() }) }

#[tauri::command]
fn logout(app: tauri::State<Arc<AppState>>) { app.real.store(false, Ordering::SeqCst); save_prefs(&app); app.spotify.lock().unwrap().logout(); push(&app.status, "Spotify: logged out, real playback off".into()); }

#[tauri::command]
fn set_real(app: tauri::State<Arc<AppState>>, on: bool) {
    app.real.store(on, Ordering::SeqCst); save_prefs(&app);
    push(&app.status, if on { "Real playback ON - 1.1 now controls Spotify. Turn off auto-switching in 1.0.9 (or close it) so they do not fight.".into() } else { "Real playback OFF (dry run)".into() });
}

fn main() {
    let settings = settings::load_installed();
    let probe = Aoe4::new(Box::new(|_, _| None));
    let path = settings.log_path.clone().map(PathBuf::from).or_else(|| probe.default_log_path()).unwrap_or_default();
    let ages = probe.ages().iter().map(|(k, l)| (k.to_string(), l.to_string())).collect();
    let status = Status { game: probe.label().into(), log_path: path.display().to_string(), ..Default::default() };
    let dir = PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify-1.1");
    let prefs: serde_json::Value = std::fs::read_to_string(dir.join("settings.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    let spotify = Spotify::new(settings.client_id.clone(), dir.join("token.json"));
    let (tx, rx) = channel(); let replays0 = prefs["music_in_replays"].as_bool().unwrap_or(settings.music_in_replays);
    let app = Arc::new(AppState { settings, ages, status: Mutex::new(status), real: AtomicBool::new(prefs["real_playback"].as_bool() == Some(true)),
        replays: AtomicBool::new(replays0), busy: AtomicBool::new(false), spotify: Mutex::new(spotify), tx: Mutex::new(tx), dir });
    let a2 = app.clone(); std::thread::spawn(move || watch(a2, path));
    let a3 = app.clone(); std::thread::spawn(move || player(a3, rx));
    tauri::Builder::default()
        .manage(app)
        .setup(|a| { use tauri::Manager; if zoom() != 1.0 { let w = a.get_webview_window("main").unwrap(); let _ = w.set_zoom(zoom()); let _ = w.set_size(tauri::LogicalSize::new(554.0 * zoom(), 880.0 * zoom())); }
            if let Some(d) = std::env::var_os("AOE4S_SWITCHTEST") { use tauri::Manager; let w = a.get_webview_window("main").unwrap(); std::thread::spawn(move || switch_test(w, PathBuf::from(d))); } Ok(()) })
        .invoke_handler(tauri::generate_handler![get_state, login, logout, set_real, resize, cfg, cover, region, dbg, menu, check_update])
        .run(tauri::generate_context!())
        .expect("error while running AoE4 Spotify");
}