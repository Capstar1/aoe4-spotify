#![windows_subsystem = "windows"]
#![deny(warnings)]
//! M1 shell: one fixed-size window; the core follows the game log. Playback is always real, as in 1.0.9 (no dry-run switch)
//! so 1.1 never fights the 1.0.9 app over Spotify; the toggle is saved in %APPDATA%\AoE4Spotify-1.1.
mod shadow;
mod launcher;
mod data;
mod engine;
mod picker;
mod guides;
mod updater;
use data::*;
use engine::*;
use picker::*;
use guides::*;
use updater::*;
use aoe4core::aoe4::Aoe4;
use aoe4core::game::{GameAdapter, GameEvent};
use aoe4core::logtail::{Poll, Tail};
use aoe4core::settings::{self, Settings};
use aoe4core::switcher::{Action, Switcher};
use aoe4core::spotify::Spotify;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Sender};
use std::path::PathBuf;
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

#[derive(Default, serde::Serialize, Clone)]
struct Status { result: Option<i32>, match_n: u64, game: String, log_path: String, watching: bool, in_match: bool, age: Option<String>, playing: Option<String>, log: Vec<String> }

struct AppState { pick: Mutex<serde_json::Value>, gtg: Mutex<serde_json::Value>, settings: Mutex<Settings>, ver: std::sync::atomic::AtomicU64, upd: Mutex<serde_json::Value>, ages: Vec<(String, String)>, status: Mutex<Status>, cv: Condvar, logged: AtomicBool, stat: Mutex<Option<(u64, serde_json::Value)>>, replays: AtomicBool, busy: AtomicBool, spotify: Mutex<Spotify>, tx: Mutex<Sender<Action>>, dir: PathBuf, ed: Mutex<serde_json::Value> }

/// Settings-side part of the state (settings, your lists / after match, intros, age data, edits): built once per
/// settings version (`ver`, bumped on every settings / intros change) and reused.
fn static_state(app: &AppState) -> (u64, serde_json::Value) {
    let v = app.ver.load(Ordering::SeqCst);
    let mut c = app.stat.lock().unwrap();
    if let Some((k, s)) = c.as_ref() { if *k == v { return (v, s.clone()); } }
    let keys: Vec<String> = app.ages.iter().map(|(k, _)| k.clone()).collect();
    let ed = app.ed.lock().unwrap().clone(); let set = app.settings.lock().unwrap().clone(); let es = with_ed(&set, &ed);
    let user = read_user(&app.dir);
    let s = serde_json::json!({ "settings": set, "user": { "custom_lists": user["custom_lists"], "after_match": user["after_match"], "fade_seconds": user["fade_seconds"] }, "ages": app.ages, "intros": aoe4core::intros::overview(&es, &keys), "agedata": aoe4core::intros::age_data(&es, &keys), "ed": ed });
    *c = Some((v, s.clone())); (v, s)
}
fn live_state(app: &AppState) -> serde_json::Value {
    let st = app.status.lock().unwrap().clone();
    // never wait for the Spotify lock here (a fade / after-match step holds it): use the last known state then
    let logged_in = match app.spotify.try_lock() { Ok(s) => { let v = s.logged_in(); app.logged.store(v, Ordering::SeqCst); v } Err(_) => app.logged.load(Ordering::SeqCst) };
    serde_json::json!({ "upd": app.upd.lock().unwrap().clone(), "status": st, "spotify": { "logged_in": logged_in, "replays": app.replays.load(Ordering::SeqCst), "busy": app.busy.load(Ordering::SeqCst) } })
}
/// Panel state. `since` = the settings version the panel already has: then the settings-side part is left out
/// (the panel keeps its copy); "skey" says which version the answer belongs to.
#[tauri::command]
fn get_state(app: tauri::State<Arc<AppState>>, since: Option<u64>) -> serde_json::Value {
    let mut out = live_state(&app);
    let (k, s) = static_state(&app);
    if since != Some(k) { if let (Some(o), Some(m)) = (out.as_object_mut(), s.as_object()) { for (a, b) in m { o.insert(a.clone(), b.clone()); } } }
    out["skey"] = serde_json::json!(k); out
}
/// Push instead of the panel's poll: "state-changed" goes out when anything the panel shows changes (checked
/// every 250 ms here, in-process); the panel then fetches. The panel keeps a slow 5 s poll as a fallback.
fn notifier(h: tauri::AppHandle, app: Arc<AppState>) {
    use tauri::Emitter;
    let mut last = String::new();
    loop {
        std::thread::sleep(Duration::from_millis(250));
        let st = app.status.lock().unwrap().clone();
        let f = serde_json::json!([app.ver.load(Ordering::SeqCst), app.upd.lock().unwrap().clone(), st.in_match, st.age, st.watching, st.playing, st.result, st.match_n,
            app.logged.load(Ordering::SeqCst), app.replays.load(Ordering::SeqCst), app.busy.load(Ordering::SeqCst)]).to_string();
        if f != last { last = f; let _ = h.emit("state-changed", ()); }
    }
}
/// WebView2 switches for every window (all windows share one WebView2 environment, so they must be identical;
/// main's copy is in tauri.conf.json). Tauri's defaults plus: no translate / autofill / hints / cast / sync / background traffic.
pub const WV_ARGS: &str = "--disable-features=msWebOOUI,msPdfOOUI,msSmartScreenProtection,Translate,AutofillServerCommunication,OptimizationHints,MediaRouter,SpareRendererForSitePerProcess --disable-background-networking --disable-component-update --disable-sync --disable-default-apps --no-pings";
#[cfg(test)]
mod tests { #[test] fn webview_args_match_conf() { assert!(include_str!("../tauri.conf.json").contains(&format!("\"additionalBrowserArgs\": \"{}\"", super::WV_ARGS))); }
    #[test] fn import_check_and_timestamp() {
        use serde_json::json; use super::data::{covered, iso_now};
        assert!(covered(&json!(null), &json!({ "a": 1 })) && covered(&json!({}), &json!({ "a": 1 })) && covered(&json!({ "a": 1 }), &json!({ "a": 2, "b": 3 })));
        assert!(!covered(&json!({ "a": 1, "c": 1 }), &json!({ "a": 1 })) && covered(&json!([1, 2]), &json!([2, 1, 3])) && !covered(&json!([4]), &json!([1])));
        let t = iso_now(); assert!(t.len() == 20 && t.starts_with("20") && t.ends_with('Z') && &t[10..11] == "T", "{t}");
    } }

mod win {
    #[link(name = "user32")] extern "system" { fn FindWindowW(c: *const u16, t: *const u16) -> isize; fn ShowWindow(h: isize, c: i32) -> i32; fn SetForegroundWindow(h: isize) -> i32; fn IsWindowVisible(h: isize) -> i32; }
    /// Panel opened while a game-launched 1.1 runs hidden: show that one instead of starting a second switcher.
    pub fn show_existing() { let t: Vec<u16> = "AoE4 Spotify".encode_utf16().chain(Some(0)).collect(); unsafe { let h = FindWindowW(std::ptr::null(), t.as_ptr()); if h != 0 { ShowWindow(h, 5); ShowWindow(h, 9); SetForegroundWindow(h); } } }
    pub fn visible(h: isize) -> bool { unsafe { IsWindowVisible(h) != 0 } }
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

/// Covers already served (data URLs), cleared whenever a cover is written or removed and when the covers folder
/// changes; misses are not remembered (a cover can arrive any moment).
static COVERS: Mutex<Option<(Option<SystemTime>, std::collections::HashMap<String, String>)>> = Mutex::new(None);
pub(crate) fn covers_changed() { *COVERS.lock().unwrap() = None; }
/// Cached 1.0.9 cover (playlist <id>_<snapshot>.jpg newest, or track_<id>.jpg) as a data URL; None if missing.
#[tauri::command]
fn cover(uri: String) -> Option<String> {
    let dir = PathBuf::from(std::env::var("APPDATA").ok()?).join(r"AoE4Spotify-1.1\covers");
    let m = std::fs::metadata(&dir).and_then(|m| m.modified()).ok();
    { let mut c = COVERS.lock().unwrap(); if c.as_ref().map_or(true, |(t, map)| *t != m || map.len() > 600) { *c = Some((m, Default::default())); }
      if let Some(v) = c.as_ref().and_then(|(_, map)| map.get(&uri)) { return Some(v.clone()); } }
    let v = read_cover(&dir, &uri)?;
    if let Some((t, map)) = COVERS.lock().unwrap().as_mut() { if *t == m { map.insert(uri, v.clone()); } }
    Some(v)
}
fn read_cover(dir: &std::path::Path, uri: &str) -> Option<String> {
    use base64::Engine;
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
    #[link(name = "gdi32")] extern "system" { fn CreateRoundRectRgn(a: i32, b: i32, c: i32, d: i32, w: i32, h: i32) -> isize; }
    #[link(name = "user32")] extern "system" { fn SetWindowRgn(h: isize, r: isize, redraw: i32) -> i32; }
    let hwnd = window.hwnd().map(|v| v.0 as isize).unwrap_or(0);
    let k = window.scale_factor().unwrap_or(1.0) * zoom();
    let r = |v: f64| (v * k).round() as i32;
    // Clip to #frame's 8px CSS radius (in device px) so nothing outside the rounded corners is ever shown: the
    // transparent pixels there were left white/stale by WebView2 (the "notches"). GDI round-rect: right/bottom are
    // exclusive and need +1; ellipse diameter = 2 * radius.
    let d = (16.0 * k).round() as i32;
    unsafe { let rg = CreateRoundRectRgn(r(x), r(y), r(x + w) + 1, r(y + h) + 1, d, d); SetWindowRgn(hwnd, rg, 1); }
}

#[tauri::command]
fn shadow(window: tauri::WebviewWindow, x: f64, y: f64, w: f64, h: f64) {
    let k = window.scale_factor().unwrap_or(1.0) * zoom(); let r = |v: f64| (v * k).round() as i32;
    let (a, b, c, d) = (r(x), r(y), r(x + w) - r(x), r(y + h) - r(y));
    let _ = window.run_on_main_thread(move || shadow::set_frame(a, b, c, d, k));
}

#[tauri::command]
fn dbg(window: tauri::WebviewWindow, s: String) {
    let o = window.outer_position().ok(); let i = window.inner_position().ok(); let os = window.outer_size().ok(); let is = window.inner_size().ok();
    let _ = std::fs::write(std::env::temp_dir().join("aoe4s_dbg.txt"), format!("{s}\nouter {o:?} {os:?}\ninner {i:?} {is:?} scale {:?}", window.scale_factor()));
}

fn open_path(p: &str) {
    if let Some(f) = std::env::var_os("AOE4S_DRYOPEN") { use std::io::Write; if let Ok(mut h) = std::fs::OpenOptions::new().create(true).append(true).open(f) { let _ = writeln!(h, "{p}"); } return; }
    use std::os::windows::process::CommandExt; let _ = std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", p]).creation_flags(0x0800_0000).spawn(); }

/// Cog menu rows (1.0.9 behaviour; 1.1 keeps its own files and never writes the 1.0.9 settings).
#[tauri::command]
fn menu(app: tauri::State<Arc<AppState>>, kind: String) -> String {
    match kind.as_str() {
        k if k.starts_with("pl:") => { let id: String = k[3..].chars().filter(|c| c.is_ascii_alphanumeric()).collect(); if id.len() == 22 { open_path(&format!("spotify:playlist:{id}")); } String::new() }
        "github" => { open_path("https://github.com/Capstar1/aoe4-spotify"); String::new() }
        "dashboard" => { open_path("https://developer.spotify.com/dashboard"); String::new() }
        "account" => { open_path("https://www.spotify.com/account/overview/"); String::new() }
        "log" => { let p = app.dir.join("aoe4_spotify.log"); let _ = std::fs::create_dir_all(&app.dir);   // 1.0.9: the app's own log file
                   if !p.exists() { let _ = std::fs::write(&p, ""); } open_path(&p.display().to_string()); String::new() }
        "replays" => { let v = !app.replays.load(Ordering::SeqCst); app.replays.store(v, Ordering::SeqCst); save_prefs(&app); String::new() }
        "uninstall" => {   // installed copy: hand over to "<exe> --uninstall" (asks, then removes everything) and close the panel
            let unins = launcher::install_dir().join("unins000.exe");
            if unins.is_file() && std::env::var_os("AOE4S_DRYOPEN").is_none() {   // installer build: its uninstaller asks and does everything (like 1.0.9)
                let _ = std::process::Command::new(&unins).spawn(); return String::new();
            }
            if launcher::installed() && std::env::var_os("AOE4S_DRYOPEN").is_none() {
                if let Ok(exe) = std::env::current_exe() { let _ = std::process::Command::new(exe).arg("--uninstall").spawn(); std::thread::spawn(|| { std::thread::sleep(Duration::from_millis(300)); std::process::exit(0) }); }
                return String::new();
            }
            let msg = "Uninstaller not found (not installed?).";
            if std::env::var_os("AOE4S_DRYOPEN").is_none() {
                std::thread::spawn(move || {
                    #[link(name = "user32")] extern "system" { fn MessageBoxW(h: isize, t: *const u16, c: *const u16, f: u32) -> i32; }
                    let w = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
                    unsafe { MessageBoxW(0, w(msg).as_ptr(), w("Uninstall").as_ptr(), 0x40 | 0x40000); }   // info icon, topmost
                });
            }
            msg.into()
        }
        _ => String::new(),
    }
}

#[tauri::command]
fn cfg() -> serde_json::Value { serde_json::json!({ "order": std::env::var("AOE4S_ORDER").unwrap_or_default(), "pl_closed": std::env::var_os("AOE4S_PL_CLOSED").is_some(), "menutest": std::env::var_os("AOE4S_MENUTEST").is_some(), "open": std::env::var("AOE4S_OPEN").unwrap_or_default(), "edtest": std::env::var_os("AOE4S_EDTEST").is_some(), "addtest": std::env::var_os("AOE4S_ADDTEST").is_some() }) }

#[tauri::command]
async fn logout(app: tauri::State<'_, Arc<AppState>>) -> Result<(), String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || { a.spotify.lock().unwrap().logout(); sync_logged(&a); push(&a.status, "Spotify: logged out".into()); }).await.map_err(|e| e.to_string())
}

fn main() {
    let dir = PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify-1.1");
    if std::env::args().nth(1).as_deref() != Some("--migrate-109") { import_109(&dir); }
    let settings = settings::load_own(&dir);
    // 1.0.9 start-up modes: Steam launch (%command%), --set/--remove-launch-option, panel (one instance)
    let mut hidden = false;
    let login_first = std::env::args().nth(1).is_none();   // started by hand / installer Finish: log in first, then "You're good to go"
    match launcher::mode(settings.enabled) {
        launcher::Mode::Done => return,
        launcher::Mode::Migrate(inst, cleanup) => { std::process::exit(if migrate_109(&dir, inst, cleanup).is_ok() { 0 } else { 2 }); }
        launcher::Mode::Attach => { if !launcher::aoe_running() || !settings.enabled || !launcher::single_instance() { return; } hidden = true; }
        launcher::Mode::Game(args) => {
            if !launcher::start_game(&args, settings.enabled) { return; }
            hidden = true;     // the switcher runs with its window hidden; opening the panel shows it
            for (k, _) in std::env::vars() { let l = k.to_lowercase(); if l.starts_with("steam") || l.starts_with("enable_vk_layer_valve") { std::env::remove_var(k); } }   // only the game gets Steam's variables
        }
        launcher::Mode::Panel => { if !launcher::single_instance() { win::show_existing(); return; } launcher::register_uninstall(); }
    }
    let probe = Aoe4::new(Box::new(|_, _| None));
    let path = settings.log_path.clone().map(PathBuf::from).or_else(|| probe.default_log_path()).unwrap_or_default();
    let ages = probe.ages().iter().map(|(k, l)| (k.to_string(), l.to_string())).collect();
    let status = Status { game: probe.label().into(), log_path: path.display().to_string(), ..Default::default() };
    let prefs: serde_json::Value = std::fs::read_to_string(dir.join("settings.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    let spotify = Spotify::new(settings.client_id.clone(), dir.join("token.json")); let logged0 = spotify.logged_in();
    let (tx, rx) = channel(); let replays0 = prefs["music_in_replays"].as_bool().unwrap_or(settings.music_in_replays);
    let app = Arc::new(AppState { pick: Mutex::new(serde_json::Value::Null), gtg: Mutex::new(serde_json::Value::Null), settings: Mutex::new(settings), ver: Default::default(), upd: Mutex::new(serde_json::json!({ "phase": if std::env::args().any(|a| a == "--updated") { "done" } else { "idle" }, "msg": format!("Updated to {}", env!("CARGO_PKG_VERSION")) })), ages, status: Mutex::new(status), cv: Condvar::new(), stat: Mutex::new(None), logged: AtomicBool::new(logged0),
        replays: AtomicBool::new(replays0), busy: AtomicBool::new(false), spotify: Mutex::new(spotify), tx: Mutex::new(tx), ed: Mutex::new(load_ed(&dir)), dir });
    let a2 = app.clone(); std::thread::spawn(move || watch(a2, path));
    let a3 = app.clone(); std::thread::spawn(move || player(a3, rx));
    let a4 = app.clone();
    tauri::Builder::default()
        .manage(app)
        .setup(move |a| { use tauri::Manager; { let h = a.handle().clone(); std::thread::spawn(move || notifier(h, a4)); } if let Some(h) = a.get_webview_window("main").and_then(|w| w.hwnd().ok()) { shadow::init(h.0 as isize); } if zoom() != 1.0 { let w = a.get_webview_window("main").unwrap(); let _ = w.set_zoom(zoom()); let _ = w.set_size(tauri::LogicalSize::new(554.0 * zoom(), 880.0 * zoom())); }
            { let w = a.get_webview_window("main").unwrap();
              if hidden { let h = w.hwnd().map(|h| h.0 as isize).unwrap_or(0); let ah = a.handle().clone();
                  let a5 = a.state::<Arc<AppState>>().inner().clone(); let a6 = a5.clone();
                  std::thread::spawn(move || auto_update(a6));
                  std::thread::spawn(move || launcher::follow_game(move || { install_pending(&a5); if !win::visible(h) { ah.exit(0) } })); }
              else { let a5 = a.state::<Arc<AppState>>().inner().clone(); std::thread::spawn(move || { if let Ok(Some(i)) = latest() { let mut u = a5.upd.lock().unwrap(); if u["phase"] == "idle" || u["phase"] == "done" { *u = serde_json::json!({ "phase": "avail", "info": i }); } } }); }
              if !login_first && std::env::args().nth(1).is_none() { pending_access(a.handle().clone(), a.state::<Arc<AppState>>().inner().clone()); }
              if login_first { let a7 = a.state::<Arc<AppState>>().inner().clone(); let h7 = a.handle().clone();
                  if a7.spotify.lock().unwrap().logged_in() { std::thread::spawn(move || after_login(&h7, &a7)); } else { do_login(h7, a7); } }
              else if !hidden { let _ = w.show(); let _ = w.set_focus(); } }
            if let Some(d) = std::env::var_os("AOE4S_SWITCHTEST") { use tauri::Manager; let w = a.get_webview_window("main").unwrap(); std::thread::spawn(move || switch_test(w, PathBuf::from(d))); } Ok(()) })
        .on_window_event(|w, e| { use tauri::Manager; if (w.label() == "gtg" || w.label() == "access" || w.label() == "own") && matches!(e, tauri::WindowEvent::Destroyed) {
            let h = w.app_handle().clone(); if let Some(m) = h.get_webview_window("main") { if !m.is_visible().unwrap_or(true) && std::env::args().nth(1).is_none() { h.exit(0); } } } })
        .invoke_handler(tauri::generate_handler![get_state, guides::login, logout, resize, cfg, cover, region, shadow, picker::preview, data::save_ed, data::encode_preset, data::decode_preset, picker::sp, picker::cache_covers, picker::open_add, dbg, menu, updater::check_update, guides::show_panel, data::set_user, data::set_enabled, updater::start_update, picker::open_pick, picker::pick_done, picker::pick_info, guides::gtg_info, guides::gtg_fix, picker::save_list, picker::delete_list, guides::access_info, guides::access_send, guides::access_check, guides::clip_text, guides::open_own, guides::own_info, guides::own_save, guides::own_shared])
        .run(tauri::generate_context!())
        .expect("error while running AoE4 Spotify");
}