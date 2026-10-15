#![windows_subsystem = "windows"]
//! M1 shell: one fixed-size window; the core follows the game log. Real playback is OFF by default (dry run)
//! so 1.1 never fights the 1.0.9 app over Spotify; the toggle is saved in %APPDATA%\AoE4Spotify-1.1.
mod shadow;
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

struct AppState { settings: Settings, ages: Vec<(String, String)>, status: Mutex<Status>, real: AtomicBool, replays: AtomicBool, busy: AtomicBool, spotify: Mutex<Spotify>, tx: Mutex<Sender<Action>>, dir: PathBuf, ed: Mutex<serde_json::Value> }

const ED_KEYS: [&str; 6] = ["intro_pools", "intro_ages", "custom_songs", "intro_presets", "intro_preset", "intro_pack_open"];
/// Age Intros edits made in 1.1 live in 1.1's own intros.json (seeded once from 1.0.9's settings), so the
/// installed 1.0.9 config is never written.
fn load_ed(dir: &std::path::Path) -> serde_json::Value {
    if let Some(v) = std::fs::read_to_string(dir.join("intros.json")).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()) { return v; }
    let u: serde_json::Value = std::fs::read_to_string(dir.join("config.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    let mut m = serde_json::Map::new(); for k in ED_KEYS { if !u[k].is_null() { m.insert(k.into(), u[k].clone()); } } serde_json::Value::Object(m)
}
/// One-time import of the 1.0.9 data (install config, settings, playlist names, intros/presets, cover cache) into
/// 1.1's own folder; afterwards 1.1 reads only its own files. Writes import.json with the copied counts.
fn import_109(dir: &std::path::Path) {
    if dir.join("import.json").exists() { return; }
    let ad = PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify");
    let inst = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or_default()).join(r"Programs\AoE4 Spotify\_internal\config.json");
    if !ad.join("config.json").exists() && !inst.exists() { return; }
    let _ = std::fs::create_dir_all(dir.join("covers"));
    let cp = |a: &std::path::Path, b: &str| if a.exists() && !dir.join(b).exists() { std::fs::copy(a, dir.join(b)).is_ok() } else { dir.join(b).exists() };
    let (b1, b2, b3) = (cp(&inst, "base.json"), cp(&ad.join("config.json"), "config.json"), cp(&ad.join("playlist_names.json"), "playlist_names.json"));
    let mut n = 0; let mut src = 0;
    for e in std::fs::read_dir(ad.join("covers")).into_iter().flatten().flatten() { if e.path().is_file() { src += 1; let t = dir.join("covers").join(e.file_name()); if t.exists() || std::fs::copy(e.path(), &t).is_ok() { n += 1; } } }
    if !dir.join("intros.json").exists() { let v = load_ed(dir); let _ = std::fs::write(dir.join("intros.json"), serde_json::to_string_pretty(&v).unwrap_or_default()); }
    let mut pr: serde_json::Value = std::fs::read_to_string(dir.join("settings.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(serde_json::json!({}));
    pr["real_playback"] = serde_json::json!(true); let _ = std::fs::write(dir.join("settings.json"), pr.to_string());   // 1.1 replaces 1.0.9: real playback on
    let _ = std::fs::write(dir.join("import.json"), serde_json::json!({ "from": "1.0.9", "base": b1, "config": b2, "playlist_names": b3, "covers": n, "covers_src": src, "at": now() }).to_string());
}
fn with_ed(s: &Settings, ed: &serde_json::Value) -> Settings {
    let mut s = s.clone(); s.user_pools = ed["intro_pools"].clone(); s.custom_songs = ed["custom_songs"].clone();
    s.intro_ages = ed["intro_ages"].as_object().map(|o| o.iter().filter_map(|(k, v)| v.as_bool().map(|b| (k.clone(), b))).collect()).unwrap_or_default(); s
}
#[tauri::command]
fn save_ed(app: tauri::State<Arc<AppState>>, u: serde_json::Value) {
    let mut m = serde_json::Map::new(); for k in ED_KEYS { if !u[k].is_null() { m.insert(k.into(), u[k].clone()); } }
    let v = serde_json::Value::Object(m); let _ = std::fs::create_dir_all(&app.dir);
    let _ = std::fs::write(app.dir.join("intros.json"), serde_json::to_string_pretty(&v).unwrap_or_default()); *app.ed.lock().unwrap() = v;
}
/// 1.0.9 share codes: "AOE4S1:" + urlsafe base64 (no padding) of zlib(json {v,name,pools,ages,custom}).
#[tauri::command]
fn encode_preset(p: serde_json::Value) -> String {
    use std::io::Write; use base64::Engine;
    let d = serde_json::json!({ "v": 1, "name": p["name"], "pools": p["pools"], "ages": p["ages"], "custom": p["custom"] });
    let mut z = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::best()); let _ = z.write_all(d.to_string().as_bytes());
    format!("AOE4S1:{}", base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(z.finish().unwrap_or_default()))
}
#[tauri::command]
fn decode_preset(app: tauri::State<Arc<AppState>>, code: String) -> Result<serde_json::Value, String> {
    use std::io::Read; use base64::Engine; use serde_json::{json, Value};
    let code: String = code.chars().filter(|c| !c.is_whitespace()).collect();
    let Some(rest) = code.strip_prefix("AOE4S") else { return Err("Not an AoE4 Spotify code".into()) };
    let (ver, b) = rest.split_once(':').ok_or("Not an AoE4 Spotify code")?;
    if ver != "1" { return Err("Made with a newer version - update AoE4 Spotify".into()); }
    if b.len() > 1 << 18 { return Err("Code is too big".into()); }
    let raw = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(b.trim_end_matches('=')).map_err(|_| "Code is incomplete or damaged")?;
    let mut out = Vec::new(); flate2::read::ZlibDecoder::new(&raw[..]).take((1 << 18) + 1).read_to_end(&mut out).map_err(|_| "Code is incomplete or damaged")?;
    if out.len() > 1 << 18 { return Err("Code is too big".into()); }
    let d: Value = serde_json::from_slice(&out).map_err(|_| "Code is incomplete or damaged")?;
    if d["v"] != json!(1) { return Err("Made with a newer version - update AoE4 Spotify".into()); }
    let track = |s: &str| s.len() == 36 && s.starts_with("spotify:track:") && s[14..].chars().all(|c| c.is_ascii_alphanumeric());
    let cat: Value = serde_json::from_str(aoe4core::intros::CATALOG).unwrap_or_default();
    let civs: Vec<String> = cat["factions"].as_array().cloned().unwrap_or_default().iter().filter_map(|f| f[0].as_str().map(String::from)).collect();
    let ages: Vec<String> = app.ages.iter().map(|a| a.0.clone()).collect();
    let mut pools = serde_json::Map::new(); let mut used: Vec<String> = vec![];
    if let Some(o) = d["pools"].as_object() { for (a, dd) in o { if !ages.contains(a) { continue; } let mut m = serde_json::Map::new();
        if let Some(dd) = dd.as_object() { for (c, v) in dd { if !civs.contains(c) { continue; } let mut l: Vec<String> = vec![];
            for x in v.as_array().cloned().unwrap_or_default() { if let Some(x) = x.as_str() { if track(x) && !l.iter().any(|y| y == x) && l.len() < 12 { l.push(x.into()); } } }
            if !l.is_empty() { used.extend(l.clone()); m.insert(c.clone(), json!(l)); } } }
        if !m.is_empty() { pools.insert(a.clone(), Value::Object(m)); } } }
    let mut ag = serde_json::Map::new(); if let Some(o) = d["ages"].as_object() { for (a, v) in o { if ages.contains(a) && v.is_boolean() { ag.insert(a.clone(), v.clone()); } } }
    let mut custom = vec![]; let mut known: Vec<String> = cat["songs"].as_array().cloned().unwrap_or_default().iter().filter_map(|s| s[3].as_str().map(String::from)).collect();
    for c in d["custom"].as_array().cloned().unwrap_or_default() { if let Some(u) = c["uri"].as_str() { if track(u) && used.iter().any(|x| x == u) {
        let n: String = c["name"].as_str().unwrap_or("Song").chars().take(80).collect(); let ar: String = c["artist"].as_str().unwrap_or("").chars().take(80).collect();
        custom.push(json!({ "uri": u, "name": n, "artist": ar })); known.push(u.into()); } } }
    if used.iter().any(|u| !known.contains(u)) { return Err("Code uses songs it doesn't include".into()); }
    if d.get("pools").is_none() && d.get("ages").is_none() { return Err("Code has no intro lists".into()); }
    let name: String = d["name"].as_str().unwrap_or("Shared").trim().chars().take(40).collect();
    Ok(json!({ "v": 1, "name": if name.is_empty() { "Shared".to_string() } else { name }, "pools": pools, "ages": ag, "custom": custom }))
}

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
    let ed = app.ed.lock().unwrap().clone(); let es = with_ed(&app.settings, &ed);
    serde_json::json!({ "settings": app.settings, "ages": app.ages, "status": st, "intros": aoe4core::intros::overview(&es, &keys), "agedata": aoe4core::intros::age_data(&es, &keys), "ed": ed,
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

/// Age page: click a chip = play that song now, click again = pause ("login" when 1.1 is not logged in).
#[tauri::command]
async fn preview(app: tauri::State<'_, Arc<AppState>>, uri: Option<String>) -> Result<String, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut sp = a.spotify.lock().unwrap();
        if !sp.logged_in() { return Ok("login".to_string()); }
        match uri { Some(u) => sp.preview(&u), None => sp.pause() }.map(|_| "ok".to_string())
    }).await.map_err(|e| e.to_string())?
}

/// Add a song (M3): one Spotify track -> {uri,name,artist,img}.
fn norm(t: &serde_json::Value) -> Option<serde_json::Value> {
    let u = t["uri"].as_str()?; if !u.starts_with("spotify:track:") { return None; }
    let imgs = t["album"]["images"].as_array().cloned().unwrap_or_default();
    let img = imgs.iter().min_by_key(|i| (i["width"].as_i64().unwrap_or(640) - 64).abs()).and_then(|i| i["url"].as_str()).unwrap_or("");
    let ar = t["artists"].as_array().map(|a| a.iter().take(2).filter_map(|x| x["name"].as_str()).collect::<Vec<_>>().join(", ")).unwrap_or_default();
    Some(serde_json::json!({ "uri": u, "name": t["name"].as_str().unwrap_or("Song"), "artist": ar, "img": img }))
}
fn fake_sp(kind: &str, arg: &str) -> serde_json::Value {
    let tr = |k: usize, n: &str| serde_json::json!({ "uri": format!("spotify:track:{}", k.to_string().repeat(22)), "name": n, "artist": "Yasunori Nishiki", "img": "" });
    match kind {
        "playlists" => serde_json::json!([{ "id": "liked", "name": "Liked Songs", "n": 212 }, { "id": "p1", "name": "Octopath favourites", "n": 38 }, { "id": "p2", "name": "Game OSTs", "n": 64 }]),
        "plist" => serde_json::json!([tr(5, "Main Theme"), tr(6, "Battle at the Gate"), tr(7, "Cyrus, the Scholar"), tr(8, "Decisive Battle II"), tr(9, "Ophilia's Theme"), tr(3, &format!("From {arg}"))]),
        "tracks" => serde_json::Value::Array(arg.split(',').map(|i| serde_json::json!({ "uri": format!("spotify:track:{i}"), "name": format!("Dropped {}", &i[..4.min(i.len())]), "artist": "Test", "img": "" })).collect()),
        "playing" => serde_json::json!([tr(4, "Now Playing Song")]),
        _ => serde_json::json!([tr(1, &format!("{arg} 1")), tr(2, &format!("{arg} 2"))]),
    }
}
#[tauri::command]
async fn sp(app: tauri::State<'_, Arc<AppState>>, kind: String, arg: String) -> Result<serde_json::Value, String> {
    use serde_json::{json, Value};
    if std::env::var_os("AOE4S_FAKESP").is_some() { return Ok(fake_sp(&kind, &arg)); }
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut s = a.spotify.lock().unwrap();
        if !s.logged_in() { return Ok(json!("login")); }
        let ok = |r: Result<(u16, Value), String>| -> Result<Value, String> { let (c, v) = r?; if (200..300).contains(&c) { Ok(v) } else { Err(format!("Spotify error {c}: {}", v["error"]["message"].as_str().unwrap_or(""))) } };
        let list = |v: &Value| -> Value { Value::Array(v.as_array().cloned().unwrap_or_default().iter().filter_map(|i| norm(if i["track"].is_object() { &i["track"] } else if i["item"].is_object() { &i["item"] } else { i })).collect()) };
        match kind.as_str() {
            "search" => { let v = ok(s.get(&format!("/search?type=track&limit=10&q={}", aoe4core::spotify::enc(&arg))))?; Ok(list(&v["tracks"]["items"])) }
            "playlists" => { let v = ok(s.get("/me/playlists?limit=50"))?; let mut o = vec![json!({ "id": "liked", "name": "Liked Songs", "n": Value::Null })];
                for p in v["items"].as_array().cloned().unwrap_or_default() { if let Some(id) = p["id"].as_str() { o.push(json!({ "id": id, "name": p["name"], "n": if p["tracks"]["total"].is_null() { p["items"]["total"].clone() } else { p["tracks"]["total"].clone() } })); } }
                Ok(Value::Array(o)) }
            "plist" => { if arg == "liked" { let v = ok(s.get("/me/tracks?limit=50"))?; return Ok(list(&v["items"])); }
                let id: String = arg.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
                let v = match ok(s.get(&format!("/playlists/{id}/items?limit=100"))) { Ok(v) => v, Err(_) => ok(s.get(&format!("/playlists/{id}/tracks?limit=100")))? }; Ok(list(&v["items"])) }
            "tracks" => { let ids: Vec<String> = arg.split(',').map(|i| i.chars().filter(|c| c.is_ascii_alphanumeric()).collect()).filter(|i: &String| i.len() == 22).take(50).collect();
                if let Ok(v) = ok(s.get(&format!("/tracks?ids={}", ids.join(",")))) { return Ok(list(&v["tracks"])); }
                let mut o = vec![]; for i in ids { if let Ok(v) = ok(s.get(&format!("/tracks/{i}"))) { if let Some(t) = norm(&v) { o.push(t); } } } Ok(Value::Array(o)) }
            "playing" => { let v = ok(s.get("/me/player/currently-playing"))?; Ok(Value::Array(norm(&v["item"]).into_iter().collect())) }
            _ => Err("unknown".into()),
        }
    }).await.map_err(|e| e.to_string())?
}
/// New songs' covers go to 1.1's own cache (the 1.0.9 cache is only read).
#[tauri::command]
fn cache_covers(app: tauri::State<Arc<AppState>>, items: Vec<serde_json::Value>) {
    let a = app.inner().clone();
    std::thread::spawn(move || { let dir = a.dir.join("covers"); let _ = std::fs::create_dir_all(&dir);
        for it in items { let (Some(u), Some(img)) = (it["uri"].as_str(), it["img"].as_str()) else { continue };
            let id: String = u.rsplit(':').next().unwrap_or("").chars().filter(|c| c.is_ascii_alphanumeric()).collect(); let p = dir.join(format!("track_{id}.jpg"));
            if img.starts_with("https://") && !p.exists() { let b = a.spotify.lock().unwrap().fetch(img); if let Ok(b) = b { let _ = std::fs::write(&p, b); } } } });
}
#[tauri::command]
async fn open_add(app: tauri::AppHandle) {
    use tauri::Manager;
    if let Some(w) = app.get_webview_window("add") { let _ = w.unminimize(); let _ = w.set_focus(); return; }
    let main = app.get_webview_window("main"); let z = zoom();
    let mut b = tauri::WebviewWindowBuilder::new(&app, "add", tauri::WebviewUrl::App("add.html".into())).title("AoE4 Spotify").inner_size(416.0 * z, 560.0 * z)
        .resizable(false).maximizable(false).minimizable(false).theme(Some(tauri::Theme::Dark)).background_color(tauri::window::Color(33, 33, 33, 255)).disable_drag_drop_handler().visible(false);
    if let Some(m) = &main { if let (Ok(p), Ok(sz)) = (m.outer_position(), m.outer_size()) { b = b.position((p.x as f64 + sz.width as f64 + 4.0) / m.scale_factor().unwrap_or(1.0), (p.y as f64 + 40.0) / m.scale_factor().unwrap_or(1.0)); } b = b.parent(m).unwrap_or_else(|e| panic!("{e}")); }
    if let Ok(w) = b.build() { if z != 1.0 { let _ = w.set_zoom(z); } let _ = w.show(); let _ = w.set_focus(); }
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
    let dir = PathBuf::from(std::env::var("APPDATA").ok()?).join(r"AoE4Spotify-1.1\covers");
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
        "github" => { open_path("https://github.com/Capstar1/aoe4-spotify"); String::new() }
        "log" => { let p = app.dir.join("aoe4_spotify_1.1.log"); let _ = std::fs::create_dir_all(&app.dir);
                   let _ = std::fs::write(&p, app.status.lock().unwrap().log.join("\r\n")); open_path(&p.display().to_string()); String::new() }
        "replays" => { let v = !app.replays.load(Ordering::SeqCst); app.replays.store(v, Ordering::SeqCst); save_prefs(&app); String::new() }
        "uninstall" => {   // the 1.1 preview runs from its folder: same message box as 1.0.9 when no uninstaller exists
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
fn cfg() -> serde_json::Value { serde_json::json!({ "order": std::env::var("AOE4S_ORDER").unwrap_or_default(), "pl_closed": std::env::var_os("AOE4S_PL_CLOSED").is_some(), "menutest": std::env::var_os("AOE4S_MENUTEST").is_some(), "open": std::env::var("AOE4S_OPEN").unwrap_or_default(), "edtest": std::env::var_os("AOE4S_EDTEST").is_some(), "addtest": std::env::var_os("AOE4S_ADDTEST").is_some() }) }

#[tauri::command]
fn logout(app: tauri::State<Arc<AppState>>) { app.real.store(false, Ordering::SeqCst); save_prefs(&app); app.spotify.lock().unwrap().logout(); push(&app.status, "Spotify: logged out, real playback off".into()); }

#[tauri::command]
fn set_real(app: tauri::State<Arc<AppState>>, on: bool) {
    app.real.store(on, Ordering::SeqCst); save_prefs(&app);
    push(&app.status, if on { "Real playback ON".into() } else { "Real playback OFF (dry run)".into() });
}

fn main() {
    let dir = PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify-1.1");
    import_109(&dir);
    let settings = settings::load_own(&dir);
    let probe = Aoe4::new(Box::new(|_, _| None));
    let path = settings.log_path.clone().map(PathBuf::from).or_else(|| probe.default_log_path()).unwrap_or_default();
    let ages = probe.ages().iter().map(|(k, l)| (k.to_string(), l.to_string())).collect();
    let status = Status { game: probe.label().into(), log_path: path.display().to_string(), ..Default::default() };
    let prefs: serde_json::Value = std::fs::read_to_string(dir.join("settings.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    let spotify = Spotify::new(settings.client_id.clone(), dir.join("token.json"));
    let (tx, rx) = channel(); let replays0 = prefs["music_in_replays"].as_bool().unwrap_or(settings.music_in_replays);
    let app = Arc::new(AppState { settings, ages, status: Mutex::new(status), real: AtomicBool::new(prefs["real_playback"].as_bool() != Some(false)),
        replays: AtomicBool::new(replays0), busy: AtomicBool::new(false), spotify: Mutex::new(spotify), tx: Mutex::new(tx), ed: Mutex::new(load_ed(&dir)), dir });
    let a2 = app.clone(); std::thread::spawn(move || watch(a2, path));
    let a3 = app.clone(); std::thread::spawn(move || player(a3, rx));
    tauri::Builder::default()
        .manage(app)
        .setup(|a| { use tauri::Manager; if let Some(h) = a.get_webview_window("main").and_then(|w| w.hwnd().ok()) { shadow::init(h.0 as isize); } if zoom() != 1.0 { let w = a.get_webview_window("main").unwrap(); let _ = w.set_zoom(zoom()); let _ = w.set_size(tauri::LogicalSize::new(554.0 * zoom(), 880.0 * zoom())); }
            if let Some(d) = std::env::var_os("AOE4S_SWITCHTEST") { use tauri::Manager; let w = a.get_webview_window("main").unwrap(); std::thread::spawn(move || switch_test(w, PathBuf::from(d))); } Ok(()) })
        .invoke_handler(tauri::generate_handler![get_state, login, logout, set_real, resize, cfg, cover, region, shadow, preview, save_ed, encode_preset, decode_preset, sp, cache_covers, open_add, dbg, menu, check_update])
        .run(tauri::generate_context!())
        .expect("error while running AoE4 Spotify");
}