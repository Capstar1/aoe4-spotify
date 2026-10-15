#![windows_subsystem = "windows"]
//! M1 shell: one fixed-size window; the core follows the game log. Playback is always real, as in 1.0.9 (no dry-run switch)
//! so 1.1 never fights the 1.0.9 app over Spotify; the toggle is saved in %APPDATA%\AoE4Spotify-1.1.
mod shadow;
mod launcher;
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
struct Status { result: Option<i32>, match_n: u64, game: String, log_path: String, watching: bool, in_match: bool, age: Option<String>, playing: Option<String>, log: Vec<String> }

struct AppState { pick: Mutex<serde_json::Value>, gtg: Mutex<serde_json::Value>, settings: Mutex<Settings>, ver: std::sync::atomic::AtomicU64, upd: Mutex<serde_json::Value>, ages: Vec<(String, String)>, status: Mutex<Status>, replays: AtomicBool, busy: AtomicBool, spotify: Mutex<Spotify>, tx: Mutex<Sender<Action>>, dir: PathBuf, ed: Mutex<serde_json::Value> }

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
    if !dir.join("import.json").exists() { let _ = migrate_109(dir, None, false); return; }
    // the installer's cleanup can leave the 1.0.9 folder behind (its update log was still open): finish it once verified
    let ad = PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify");
    let ok = std::fs::read_to_string(dir.join("import.json")).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()).map_or(false, |v| v["ok"] == true && v["cleaned"] == true);
    if ok && ad.exists() { let _ = std::fs::remove_dir_all(&ad); }
}
fn count_json(p: &std::path::Path, f: impl Fn(&serde_json::Value) -> usize) -> usize { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()).map(|v| f(&v)).unwrap_or(0) }
fn cnt(v: &serde_json::Value) -> usize { v.as_array().map(|a| a.len()).or_else(|| v.as_object().map(|o| o.len())).unwrap_or(0) }
/// 1.0.9 -> 1.1 import (installer runs `--migrate-109 [--cleanup]`, first run does the same without cleanup):
/// settings, playlist names, intros + presets, cover cache, the Spotify login (refresh token, never logged) and the
/// saved game-music level (1.0.9 kept it next to its exe). Copies only; verified by counts; with cleanup the 1.0.9
/// data is deleted only after the copy verified. Returns Ok(summary) when verified.
fn migrate_109(dir: &std::path::Path, inst109: Option<PathBuf>, cleanup: bool) -> Result<serde_json::Value, String> {
    use serde_json::{json, Value};
    let ad = PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify");
    let inst = inst109.unwrap_or_else(launcher::install_dir);
    let base = [inst.join("config.json"), inst.join(r"_internal\config.json"), PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or_default()).join(r"Programs\AoE4 Spotify\_internal\config.json")].into_iter().find(|p| p.is_file());
    // Nothing of 1.0.9's user data left (fresh install, or already imported and cleaned): quietly do nothing -
    // no "NOT verified" log line and import.json is left untouched.
    if !ad.join("config.json").exists() && !ad.join("token.json").exists() && !inst.join("game_music.json").is_file() { return Err("no 1.0.9 data".into()); }
    let _ = std::fs::create_dir_all(dir.join("covers"));
    let cp = |a: &std::path::Path, b: &str| if a.exists() && !dir.join(b).exists() { std::fs::copy(a, dir.join(b)).is_ok() } else { dir.join(b).exists() || !a.exists() };
    let ok_base = base.as_ref().map_or(true, |b| cp(b, "base.json"));
    let ok_cfg = cp(&ad.join("config.json"), "config.json"); let ok_names = cp(&ad.join("playlist_names.json"), "playlist_names.json");
    let (mut n, mut src) = (0, 0);
    for e in std::fs::read_dir(ad.join("covers")).into_iter().flatten().flatten() { if e.path().is_file() { src += 1; let t = dir.join("covers").join(e.file_name()); if t.exists() || std::fs::copy(e.path(), &t).is_ok() { n += 1; } } }
    if !dir.join("intros.json").exists() { let v = load_ed(dir); let _ = std::fs::write(dir.join("intros.json"), serde_json::to_string_pretty(&v).unwrap_or_default()); }
    // Spotify login: 1.0.9 token.json {access_token, refresh_token, expires_at: float, ...} -> 1.1 {access_token, refresh_token, expires_at: u64=0 (refresh on first use)}
    let tok_src: Option<Value> = std::fs::read_to_string(ad.join("token.json")).ok().and_then(|s| serde_json::from_str(&s).ok());
    let rt = tok_src.as_ref().and_then(|t| t["refresh_token"].as_str()).filter(|s| !s.is_empty()).map(String::from);
    let ok_tok = match &rt { None => true, Some(r) => {
        if !dir.join("token.json").exists() { let t = json!({ "access_token": "", "refresh_token": r, "expires_at": 0 }); let tmp = dir.join("token.tmp");
            if std::fs::write(&tmp, t.to_string()).is_ok() { let _ = std::fs::rename(&tmp, dir.join("token.json")); } }
        std::fs::read_to_string(dir.join("token.json")).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()).map_or(false, |t| t["refresh_token"].as_str().map_or(false, |x| !x.is_empty())) } };
    // saved game-music level (only when 1.0.9 muted the music)
    let gm = inst.join("game_music.json"); let ok_music = if gm.is_file() && !dir.join("game_music.json").exists() { std::fs::copy(&gm, dir.join("game_music.json")).is_ok() } else { true };
    let mut pr: Value = std::fs::read_to_string(dir.join("settings.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(json!({}));
    // verify: counts in the copies match the originals
    let k = |p: &std::path::Path, key: &str| count_json(p, |v| cnt(&v[key]));
    let src_cfg = ad.join("config.json");
    let checks = json!({
        "custom_songs": [k(&src_cfg, "custom_songs"), k(&dir.join("intros.json"), "custom_songs")],
        "intro_presets": [k(&src_cfg, "intro_presets"), k(&dir.join("intros.json"), "intro_presets")],
        "intro_pools": [k(&src_cfg, "intro_pools"), k(&dir.join("intros.json"), "intro_pools")],
        "playlists": [k(&src_cfg, "playlists"), k(&dir.join("config.json"), "playlists")],
        "covers": [src, n] });
    let counts_ok = checks.as_object().unwrap().values().all(|v| v[0] == v[1]);
    let ok = ok_base && ok_cfg && ok_names && ok_tok && ok_music && counts_ok;
    let sum = json!({ "from": "1.0.9", "ok": ok, "base": ok_base, "config": ok_cfg, "playlist_names": ok_names, "token": rt.is_some() && ok_tok, "music_level": gm.is_file(), "counts": checks, "at": now() });
    let _ = std::fs::write(dir.join("import.json"), sum.to_string());
    if !ok { launcher::log("1.0.9 import NOT verified - 1.0.9 data kept"); return Err(sum.to_string()); }
    launcher::log("1.0.9 settings, intros, presets, covers and login imported (verified)");
    if cleanup {
        let _ = std::fs::remove_dir_all(&ad); let _ = std::fs::remove_file(&gm);
        let mut s2 = sum.clone(); s2["cleaned"] = serde_json::json!(true); let _ = std::fs::write(dir.join("import.json"), s2.to_string());
        launcher::log(if ad.exists() { "1.0.9 data removed after the verified import (an open log file goes on next start)" } else { "1.0.9 data removed after the verified import" });
    }
    Ok(sum)
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
    let _ = std::fs::write(app.dir.join("settings.json"), serde_json::json!({ "music_in_replays": app.replays.load(Ordering::SeqCst) }).to_string());
}

/// Spotify worker: actions run one after another so fades never overlap and the log watcher never blocks.
fn player(app: Arc<AppState>, rx: std::sync::mpsc::Receiver<Action>) {
    for a in rx {
        if let Action::AfterMatch { mode, playlist, wl, win, loss, fade_s } = &a {
            let r = after_match(&app, mode, playlist, *wl, win, loss, *fade_s);
            push(&app.status, match r { Ok(m) => format!("After match: {m}"), Err(e) => format!("After match failed: {e}") }); continue;
        }
        let r = { let mut sp = app.spotify.lock().unwrap(); match &a {
            Action::AfterMatch { .. } => Ok(String::new()),
            Action::Play { age, uri, fade_s } => sp.play_age(uri, *fade_s).map(|_| format!("playing {uri} for {age}")),
            Action::Restore => sp.restore(app.settings.lock().unwrap().fade_seconds),
            Action::Stop => sp.fade_pause(app.settings.lock().unwrap().fade_seconds).map(|_| "stopped (faded out and paused)".to_string()),
        } };
        push(&app.status, match r { Ok(m) => format!("Spotify: {m}"), Err(e) => format!("Spotify error: {e}") });
    }
}

/// 1.0.9 install_after_match: wait (max 6 s) for the result, play the Win / Loss pick to its end, then Resume / Playlist / Stop.
fn after_match(app: &AppState, mode: &str, playlist: &str, wl: bool, win: &str, loss: &str, fade_s: f32) -> Result<String, String> {
    let n = app.status.lock().unwrap().match_n; let same = || app.status.lock().unwrap().match_n == n;
    let mut fade = fade_s;
    if wl {
        let t0 = std::time::Instant::now();
        while app.status.lock().unwrap().result.is_none() && t0.elapsed() < Duration::from_secs(6) && same() { std::thread::sleep(Duration::from_millis(200)); }
        if !same() { return Ok("a new match already started".into()); }
        let r = app.status.lock().unwrap().result; let pick = match r { Some(1) => win, Some(0) => loss, _ => "" };
        push(&app.status, format!("After match: {}", match r { Some(1) => "victory", Some(0) => "defeat", _ => "no final result" }));
        if !pick.is_empty() {
            push(&app.status, format!("After match: play {} first", pick.split(',').next().unwrap_or(pick)));
            app.spotify.lock().unwrap().play_age(pick, fade)?;
            // until that song / list item ends, you skip, or you pause (then: nothing more)
            let t0 = std::time::Instant::now(); let mut first: Option<String> = None;
            loop {
                std::thread::sleep(Duration::from_secs(2));
                if !same() { return Ok("a new match started".into()); }
                let st = app.spotify.lock().unwrap().player_state();
                let item = st["item"]["uri"].as_str().map(String::from); let dur = st["item"]["duration_ms"].as_i64().unwrap_or(0); let pos = st["progress_ms"].as_i64().unwrap_or(0);
                if first.is_none() { first = item.clone(); }
                if st["is_playing"].as_bool() != Some(true) { if pos == 0 { break; } app.spotify.lock().unwrap().forget_saved(); return Ok("Spotify paused by you - doing nothing".into()); }
                if item != first || (dur > 0 && pos >= dur - 1500) { if dur > 0 && pos >= dur - 1500 { std::thread::sleep(Duration::from_millis(1500)); } break; }
                if t0.elapsed() > Duration::from_secs(15 * 60) { break; }
            }
            fade = fade.min(1.0);
        }
    }
    let mut sp = app.spotify.lock().unwrap();
    match mode {
        "playlist" if !playlist.is_empty() => { sp.play_age(playlist, fade)?; sp.forget_saved(); Ok(format!("play {}", playlist.split(',').next().unwrap_or(""))) }
        "resume" => sp.restore(fade),
        _ => sp.fade_pause(fade).map(|_| "stop (fade out and pause)".into()),
    }
}

fn now() -> String {
    let s = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) + 2 * 3600;   // Oslo summer time (M1)
    format!("{:02}:{:02}:{:02}", (s / 3600) % 24, (s / 60) % 60, s % 60)
}

fn push(st: &Mutex<Status>, line: String) {
    launcher::log(&line);
    let mut s = st.lock().unwrap(); s.log.push(format!("{} {}", now(), line));
    let n = s.log.len(); if n > 200 { s.log.drain(..n - 200); }
}

fn watch(app: Arc<AppState>, path: PathBuf) {
    let la = std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap_or_default();
    let crc = la.join(r"Documents\My Games\Age of Empires IV\LogFiles");
    let mut game = Aoe4::new(Aoe4::datacrc_resolver(crc));
    let mut sw = { let s = app.settings.lock().unwrap(); let mut w = Switcher::new(s.enabled, s.fade_seconds, resolve(&s)); w.after = after_cfg(&s); w };
    let mut seen = app.ver.load(Ordering::SeqCst);
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
        let v = app.ver.load(Ordering::SeqCst);
        if v != seen { seen = v; let s = app.settings.lock().unwrap(); sw.enabled = s.enabled; sw.fade_s = s.fade_seconds; sw.playlists = resolve(&s); sw.after = after_cfg(&s); }
        for l in lines {
            for ev in game.feed(&l) {
                if catching { continue; }
                push(&app.status, format!("event: {}", serde_json::to_string(&ev).unwrap_or_default()));
                match &ev {
                    GameEvent::MatchStart { .. } => { let mut s = app.status.lock().unwrap(); s.in_match = true; s.result = None; s.match_n += 1; }
                    GameEvent::MatchResult { result } => { app.status.lock().unwrap().result = Some(*result); push(&app.status, (if *result == 1 { "Result: victory" } else { "Result: defeat" }).into()) }
                    GameEvent::MatchEnd { .. } | GameEvent::Replay => { let mut s = app.status.lock().unwrap(); s.in_match = false; s.age = None; }
                    GameEvent::Age { key, .. } => app.status.lock().unwrap().age = Some(key.clone()),
                    _ => {}
                }
                for a in sw.on_event(&ev) {
                    match a.clone() {
                        Action::Play { age, uri, fade_s } => {
                            app.status.lock().unwrap().playing = Some(uri.clone());
                            let _ = (age, fade_s); let _ = app.tx.lock().unwrap().send(a.clone());
                        }
                        Action::AfterMatch { .. } => {
                            app.status.lock().unwrap().playing = None;
                            let _ = app.tx.lock().unwrap().send(a.clone());
                        }
                        Action::Restore | Action::Stop => {
                            app.status.lock().unwrap().playing = None;
                            let _ = app.tx.lock().unwrap().send(a.clone());
                        }
                    }
                }
            }
        }
        if catching { catching = false; push(&app.status, format!("Watching {}", path.display())); }
        std::thread::sleep(Duration::from_millis(250));
    }
}


fn read_user(dir: &std::path::Path) -> serde_json::Value { std::fs::read_to_string(dir.join("config.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).filter(|v: &serde_json::Value| v.is_object()).unwrap_or_else(|| serde_json::json!({})) }
const LIST_PREFIX: &str = "aoe4s:list:";
/// Age playlists with app-only lists (1.0.9 custom_lists) expanded to "uris:" + their tracks.
fn resolve(s: &Settings) -> std::collections::HashMap<String, String> {
    let u = read_user(&launcher::data_dir());
    s.playlists.iter().map(|(k, v)| (k.clone(), expand(&u, v))).collect()
}
fn expand(u: &serde_json::Value, v: &str) -> String {
    match v.strip_prefix(LIST_PREFIX) { Some(id) if id != "liked" => {
        let t: Vec<String> = u["custom_lists"][id]["tracks"].as_array().cloned().unwrap_or_default().iter().filter_map(|t| t["uri"].as_str().map(String::from)).collect();
        if t.is_empty() { String::new() } else { format!("uris:{}", t.join(",")) } }
        _ => v.to_string() }
}
/// 1.0.9 after_match_cfg: mode resume|playlist|stop, Win / Loss switch, its picks.
fn after_cfg(s: &Settings) -> aoe4core::switcher::AfterMatch {
    let a = &s.after_match; let u = read_user(&launcher::data_dir());
    let g = |k: &str| a[k].as_str().filter(|v| v.starts_with("spotify:playlist:") || v.starts_with("spotify:track:") || v.starts_with(LIST_PREFIX)).map(|v| expand(&u, v)).unwrap_or_default();
    let old_wl = a["mode"] == "winloss";
    let mode = match a["mode"].as_str() { Some(m @ ("resume" | "playlist" | "stop")) => m.to_string(), None => "resume".into(), _ => "stop".into() };
    let pl = g("playlist"); let pl = if pl.starts_with("spotify:track:") { String::new() } else { pl };
    aoe4core::switcher::AfterMatch { mode, wl: a["winloss_on"].as_bool().unwrap_or(old_wl), playlist: pl, win: g("win"), loss: g("loss") }
}
/// 1.0.9 set_user: one key of %APPDATA%\AoE4Spotify-1.1\config.json (null removes it), then live everywhere.
fn set_user_(app: &AppState, k: &str, v: serde_json::Value) {
    let mut u = read_user(&app.dir);
    if v.is_null() { u.as_object_mut().map(|o| o.remove(k)); } else { u[k] = v; }
    let _ = std::fs::create_dir_all(&app.dir);
    let tmp = app.dir.join("config.json.tmp");
    if std::fs::write(&tmp, serde_json::to_string_pretty(&u).unwrap_or_default()).is_ok() { let _ = std::fs::rename(&tmp, app.dir.join("config.json")); }
    let mut s = app.settings.lock().unwrap(); let names = s.playlist_names.clone(); *s = settings::load_own(&app.dir);
    for (k2, v2) in names { s.playlist_names.entry(k2).or_insert(v2); }
    drop(s); app.ver.fetch_add(1, Ordering::SeqCst);
}
#[tauri::command]
fn set_user(app: tauri::State<Arc<AppState>>, k: String, v: serde_json::Value) {
    const OK: [&str; 6] = ["enabled", "fade_seconds", "playlists", "boss_intro_enabled", "after_match", "custom_lists"];
    if OK.contains(&k.as_str()) { set_user_(&app, &k, v); }
}
/// Enabled switch (1.0.9): save, then mute / give back the game music in the background.
#[tauri::command]
fn set_enabled(app: tauri::State<Arc<AppState>>, on: bool) {
    set_user_(&app, "enabled", serde_json::json!(on));
    push(&app.status, if on { "Enabled".into() } else { "Disabled".into() });
    std::thread::spawn(move || { launcher::music_sync(on); });
}

#[tauri::command]
fn get_state(app: tauri::State<Arc<AppState>>) -> serde_json::Value {
    let st = app.status.lock().unwrap().clone();
    let logged_in = app.spotify.lock().map(|s| s.logged_in()).ok();
    let keys: Vec<String> = app.ages.iter().map(|(k, _)| k.clone()).collect();
    let ed = app.ed.lock().unwrap().clone(); let set = app.settings.lock().unwrap().clone(); let es = with_ed(&set, &ed);
    let user = read_user(&app.dir);
    serde_json::json!({ "settings": set, "user": { "custom_lists": user["custom_lists"], "after_match": user["after_match"], "fade_seconds": user["fade_seconds"] }, "upd": app.upd.lock().unwrap().clone(), "ages": app.ages, "ages": app.ages, "status": st, "intros": aoe4core::intros::overview(&es, &keys), "agedata": aoe4core::intros::age_data(&es, &keys), "ed": ed,
        "spotify": { "logged_in": logged_in, "replays": app.replays.load(Ordering::SeqCst), "busy": app.busy.load(Ordering::SeqCst) } })
}

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
    Some(serde_json::json!({ "uri": u, "name": t["name"].as_str().unwrap_or("Song"), "artist": ar, "img": img, "ms": t["duration_ms"].as_i64().unwrap_or(0) }))
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
            "playlists" => { let v = ok(s.get("/me/playlists?limit=50"))?; let ln = ok(s.get("/me/tracks?limit=1")).ok().map(|v| v["total"].clone()).unwrap_or(Value::Null); let mut o = vec![json!({ "id": "liked", "name": "Liked Songs", "n": ln })];
                for p in v["items"].as_array().cloned().unwrap_or_default() { if let Some(id) = p["id"].as_str() { o.push(json!({ "id": id, "name": p["name"], "img": p["images"][0]["url"], "n": if p["tracks"]["total"].is_null() { p["items"]["total"].clone() } else { p["tracks"]["total"].clone() } })); } }
                Ok(Value::Array(o)) }
            "plist" => { if arg == "liked" { let v = ok(s.get("/me/tracks?limit=50"))?; return Ok(list(&v["items"])); }
                let id: String = arg.chars().filter(|c| c.is_ascii_alphanumeric()).collect();
                let v = match ok(s.get(&format!("/playlists/{id}/items?limit=100"))) { Ok(v) => v, Err(_) => ok(s.get(&format!("/playlists/{id}/tracks?limit=100")))? }; Ok(list(&v["items"])) }
            "tracks" => { let ids: Vec<String> = arg.split(',').map(|i| i.chars().filter(|c| c.is_ascii_alphanumeric()).collect()).filter(|i: &String| i.len() == 22).take(50).collect();
                if let Ok(v) = ok(s.get(&format!("/tracks?ids={}", ids.join(",")))) { return Ok(list(&v["tracks"])); }
                let mut o = vec![]; for i in ids { if let Ok(v) = ok(s.get(&format!("/tracks/{i}"))) { if let Some(t) = norm(&v) { o.push(t); } } } Ok(Value::Array(o)) }
            "plmeta" => { let id: String = arg.chars().filter(|c| c.is_ascii_alphanumeric()).collect(); let v = ok(s.get(&format!("/playlists/{id}?fields=name,images")))?;
                Ok(json!([{ "name": v["name"], "img": v["images"][0]["url"] }])) }
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


/// 1.0.9 list_picker as its own window: target "age:<key>" | "am:playlist" | "am:win" | "am:loss".
fn small_window(app: &tauri::AppHandle, label: &str, page: &str, w: f64, h: f64) {
    use tauri::Manager;
    if let Some(x) = app.get_webview_window(label) { let _ = x.close(); }
    let main = app.get_webview_window("main"); let z = zoom();
    let mut b = tauri::WebviewWindowBuilder::new(app, label, tauri::WebviewUrl::App(page.into())).title("AoE4 Spotify").inner_size(w * z, h * z)
        .resizable(false).maximizable(false).minimizable(false).theme(Some(tauri::Theme::Dark)).background_color(tauri::window::Color(18, 18, 18, 255)).disable_drag_drop_handler().visible(false).center();
    if let Some(m) = &main { if m.is_visible().unwrap_or(false) { b = b.parent(m).unwrap_or_else(|e| panic!("{e}")); } }
    if let Ok(w) = b.build() { if z != 1.0 { let _ = w.set_zoom(z); } }
}
#[tauri::command]
async fn open_pick(app: tauri::AppHandle, st: tauri::State<'_, Arc<AppState>>, target: String, title: String, tracks: bool, current: String) -> Result<(), String> {
    *st.pick.lock().unwrap() = serde_json::json!({ "target": target, "title": title, "tracks": tracks, "current": current });
    small_window(&app, "pick", "pick.html", 420.0, 640.0); Ok(())
}

/// 1.0.9 list builder save: app-only list (custom_lists in your settings, max 100 songs) + its 2x2 mosaic cover.
#[tauri::command]
fn save_list(app: tauri::State<Arc<AppState>>, id: String, name: String, tracks: serde_json::Value, mosaic: String) -> String {
    use base64::Engine;
    let id: String = if id.chars().all(|c| c.is_ascii_alphanumeric()) && !id.is_empty() && id != "liked" { id } else { format!("{:08x}", (wall() * 1000.0) as u64 as u32) };
    let tr: Vec<serde_json::Value> = tracks.as_array().cloned().unwrap_or_default().into_iter().filter(|t| t["uri"].as_str().map_or(false, |u| u.starts_with("spotify:track:"))).take(100)
        .map(|t| serde_json::json!({ "uri": t["uri"], "name": t["name"], "artist": t["artist"], "ms": t["ms"] })).collect();
    if tr.is_empty() { return String::new(); }
    let name: String = { let n: String = name.trim().chars().take(40).collect(); if n.is_empty() { "My list".into() } else { n } };
    let mut cl = read_user(&app.dir)["custom_lists"].clone(); if !cl.is_object() { cl = serde_json::json!({}); }
    cl[&id] = serde_json::json!({ "name": name, "tracks": tr }); set_user_(&app, "custom_lists", cl);
    if let Some(b) = mosaic.strip_prefix("data:image/png;base64,") { if let Ok(b) = base64::engine::general_purpose::STANDARD.decode(b) { let d = app.dir.join("covers"); let _ = std::fs::create_dir_all(&d); let _ = std::fs::write(d.join(format!("list_{id}.png")), b); } }
    format!("{LIST_PREFIX}{id}")
}
/// Delete list (pressed twice): ages and After match picks that used it go back to their defaults / empty.
#[tauri::command]
fn delete_list(app: tauri::State<Arc<AppState>>, id: String) {
    let u = read_user(&app.dir); let uri = format!("{LIST_PREFIX}{id}");
    let mut cl = u["custom_lists"].clone(); if let Some(o) = cl.as_object_mut() { o.remove(&id); } set_user_(&app, "custom_lists", cl);
    let mut pl = u["playlists"].clone(); if let Some(o) = pl.as_object_mut() { o.retain(|_, v| v.as_str() != Some(uri.as_str())); set_user_(&app, "playlists", pl); }
    let mut am = u["after_match"].clone(); if am.is_object() { for k in ["playlist", "win", "loss"] { if am[k].as_str() == Some(uri.as_str()) { am[k] = serde_json::json!(""); } } set_user_(&app, "after_match", am); }
    let _ = std::fs::remove_file(app.dir.join("covers").join(format!("list_{id}.png")));
    launcher::log(&format!("Deleted app list {id}"));
}
#[tauri::command]
fn pick_info(app: tauri::State<Arc<AppState>>) -> serde_json::Value { let mut v = app.pick.lock().unwrap().clone(); v["custom_lists"] = read_user(&app.dir)["custom_lists"].clone(); v }
#[tauri::command]
fn pick_done(app: tauri::State<Arc<AppState>>, uri: String, name: String, img: String) {
    let p = app.pick.lock().unwrap().clone(); let t = p["target"].as_str().unwrap_or("").to_string();
    let ok = uri.starts_with("spotify:playlist:") || uri.starts_with(LIST_PREFIX) || (p["tracks"] == true && uri.starts_with("spotify:track:"));
    if !ok { return; }
    let id = uri.rsplit(':').next().unwrap_or("").to_string();
    if !name.is_empty() && !uri.starts_with(LIST_PREFIX) {           // name + cover for the panel rows (1.0.9 playlist_names.json / covers)
        let np = app.dir.join("playlist_names.json"); let mut n = read_json(&np); n[&id] = serde_json::json!(name);
        let _ = std::fs::write(&np, serde_json::to_string_pretty(&n).unwrap_or_default()); app.settings.lock().unwrap().playlist_names.insert(id.clone(), name);
        if img.starts_with("https://") { let a = app.inner().clone(); let tr = uri.starts_with("spotify:track:"); std::thread::spawn(move || {
            let dir = a.dir.join("covers"); let _ = std::fs::create_dir_all(&dir); let f = dir.join(if tr { format!("track_{id}.jpg") } else { format!("{id}_pick.jpg") });
            if let Ok(b) = a.spotify.lock().unwrap().fetch(&img) { let _ = std::fs::write(f, b); } }); }
    }
    let u = read_user(&app.dir);
    if let Some(k) = t.strip_prefix("age:") { let mut pl = u["playlists"].clone(); if !pl.is_object() { pl = serde_json::json!({}); } pl[k] = serde_json::json!(uri); set_user_(&app, "playlists", pl); }
    else if let Some(w) = t.strip_prefix("am:") { let mut a = u["after_match"].clone(); if !a.is_object() { a = serde_json::json!({}); } a[w] = serde_json::json!(uri);
        if w == "playlist" { a["mode"] = serde_json::json!("playlist"); } else { a["winloss_on"] = serde_json::json!(true); if a["mode"] == "winloss" { a["mode"] = serde_json::json!("stop"); } }
        set_user_(&app, "after_match", a); }
}
fn read_json(p: &std::path::Path) -> serde_json::Value { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(&s).ok()).filter(|v: &serde_json::Value| v.is_object()).unwrap_or_else(|| serde_json::json!({})) }
/// 1.0.9 setup_status for the "You're good to go" window.
fn spotify_installed() -> bool {
    let ad = std::env::var("APPDATA").unwrap_or_default(); let la = std::env::var("LOCALAPPDATA").unwrap_or_default();
    std::path::Path::new(&ad).join(r"Spotify\Spotify.exe").is_file() || std::path::Path::new(&la).join(r"Packages\SpotifyAB.SpotifyMusic_zpdnekdrzrea0").is_dir()
        || std::process::Command::new("reg").args(["query", r"HKCU\Software\Classes\spotify"]).output().map(|o| o.status.success()).unwrap_or(false)
}
fn show_gtg(app: &tauri::AppHandle, a: &Arc<AppState>) {
    let ok = a.spotify.lock().unwrap().logged_in();
    let name = if ok { a.spotify.lock().unwrap().get("/me").ok().filter(|(c, _)| *c == 200).and_then(|(_, v)| v["display_name"].as_str().or(v["id"].as_str()).map(String::from)) } else { None };
    *a.gtg.lock().unwrap() = serde_json::json!({ "ok": ok, "name": name, "steam": launcher::launch_option_is_set(), "spotify_app": spotify_installed() });
    let h = app.clone(); let _ = app.run_on_main_thread(move || small_window(&h, "gtg", "gtg.html", 400.0, 470.0));
}
#[tauri::command]
fn gtg_info(app: tauri::State<Arc<AppState>>) -> serde_json::Value { app.gtg.lock().unwrap().clone() }
/// Fix: put the Steam launch option back (Steam closes and reopens), then re-check.
#[tauri::command]
async fn gtg_fix(app: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || { launcher::with_steam_closed(launcher::set_launch_option); let st = launcher::launch_option_is_set(); a.gtg.lock().unwrap()["steam"] = serde_json::json!(st); a.gtg.lock().unwrap().clone() }).await.map_err(|e| e.to_string())
}

#[tauri::command]
fn login(h: tauri::AppHandle, app: tauri::State<Arc<AppState>>) { do_login(h, app.inner().clone()); }
/// 1.0.9 login(): browser login, then the "You're good to go" window.
fn do_login(h: tauri::AppHandle, a: Arc<AppState>) {
    if a.busy.swap(true, Ordering::SeqCst) { return; }
    std::thread::spawn(move || {
        push(&a.status, "Spotify: opening login in your browser...".into());
        let cid = a.spotify.lock().unwrap().client_id();   // lock released before the browser wait
        let r = Spotify::login_code(&cid).and_then(|(c, v)| a.spotify.lock().unwrap().login_finish(&c, &v));
        push(&a.status, match r { Ok(_) => "Spotify: logged in".into(), Err(e) => format!("Spotify login: {e}") });
        a.busy.store(false, Ordering::SeqCst);
        after_login(&h, &a);
    });
}

// ---- 1.0.9 access.py: shared-app access request (capstar.app relay) and the 'Not invited yet' guide
const ACCESS_URL: &str = "https://capstar.app/api/aoe4-spotify/access-request";
const ACCESS_GAP: f64 = 600.0;   // one request per 10 min per install
/// "ok", "blocked" (Spotify refuses this account: not on the shared app's user list, dev-mode 403) or None (offline / not logged in).
fn access_status(a: &AppState) -> Option<&'static str> {
    let mut sp = a.spotify.lock().unwrap(); if !sp.logged_in() { return None; }
    let (c, r) = sp.get("/me").ok()?; if c == 200 { return Some("ok"); }
    let t = r.to_string().to_lowercase();
    if c == 403 && (t.contains("not registered") || t.contains("developer dashboard") || t.contains("user may not be registered")) { Some("blocked") } else { None }
}
/// After a login: good to go, or the not-invited guide when the shared app refuses this account.
fn after_login(h: &tauri::AppHandle, a: &Arc<AppState>) { if access_status(a) == Some("blocked") { show_access(h); } else { show_gtg(h, a); } }
fn show_access(h: &tauri::AppHandle) { let h2 = h.clone(); let _ = h.run_on_main_thread(move || small_window(&h2, "access", "access.html", 500.0, 701.0)); }
/// Asked for access earlier: check once on start (1.0.9 pending_access).
fn pending_access(h: tauri::AppHandle, a: Arc<AppState>) {
    if read_user(&a.dir)["access_pending"].as_bool() != Some(true) { return; }
    std::thread::spawn(move || match access_status(&a) { Some("ok") => { set_user_(&a, "access_pending", serde_json::Value::Null); show_gtg(&h, &a); } Some("blocked") => show_access(&h), _ => {} });
}
#[tauri::command]
fn access_info(app: tauri::State<Arc<AppState>>) -> serde_json::Value {
    let u = read_user(&app.dir); let last = u["access_last"].as_f64().unwrap_or(0.0);
    serde_json::json!({ "pending": u["access_pending"].as_bool() == Some(true) && wall() - last < ACCESS_GAP, "on": true, "light": windows_light() })
}
/// Windows app theme (1.0.9 windows_light): HKCU ...\Themes\Personalize AppsUseLightTheme = 1.
fn windows_light() -> bool {
    #[cfg(windows)] { use std::os::windows::process::CommandExt;
        if let Ok(o) = std::process::Command::new("reg").args(["query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "/v", "AppsUseLightTheme"]).creation_flags(0x0800_0000).output() {
            return String::from_utf8_lossy(&o.stdout).contains("0x1"); } }
    false
}
/// The 'Send request' button: one POST {email[, name]} to the relay (no key in the app). sent | wait | bad | busy | down | error.
#[tauri::command]
async fn access_send(app: tauri::State<'_, Arc<AppState>>, email: String) -> Result<String, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let e = email.trim().to_string(); let at = e.find('@').unwrap_or(0);
        if e.len() > 100 || at == 0 || !e[at + 1..].contains('.') || e.chars().any(|c| c.is_whitespace() || c == ',' || c == ';') || e.ends_with('.') { return "bad".to_string(); }
        let u = read_user(&a.dir); if wall() - u["access_last"].as_f64().unwrap_or(0.0) < ACCESS_GAP { return "wait".into(); }
        let name: Option<String> = { let me = a.spotify.lock().unwrap().get("/me").ok().map(|(_, v)| v["display_name"].as_str().unwrap_or("").to_string()).unwrap_or_default();
            let n: String = me.chars().map(|c| if c.is_whitespace() { ' ' } else { c }).filter(|c| c.is_alphanumeric() || " ._-".contains(*c)).collect();
            let n = n.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(40).collect::<String>().trim().to_string(); if n.is_empty() { None } else { Some(n) } };
        let mut body = serde_json::json!({ "email": e }); if let Some(n) = name { body["name"] = serde_json::json!(n); }
        let r = ureq::post(ACCESS_URL).timeout(Duration::from_secs(15)).set("User-Agent", &format!("AoE4Spotify/{}", env!("CARGO_PKG_VERSION"))).send_json(body);
        let code = match r { Ok(r) => r.status(), Err(ureq::Error::Status(c, _)) => c, Err(_) => { launcher::log("Access request failed: network"); return "down".into(); } };
        if !(200..300).contains(&code) { launcher::log(&format!("Access request failed: HTTP {code}")); return match code { 400 => "bad", 429 => "busy", 502 | 503 => "down", _ => "error" }.into(); }
        set_user_(&a, "access_last", serde_json::json!(wall())); set_user_(&a, "access_pending", serde_json::json!(true)); launcher::log("Access request sent"); "sent".into()
    }).await.map_err(|e| e.to_string())
}
/// Rechecked every minute while the guide is open: once access works, close it and show good to go.
#[tauri::command]
async fn access_check(h: tauri::AppHandle, app: tauri::State<'_, Arc<AppState>>) -> Result<Option<String>, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || { let r = access_status(&a);
        if r == Some("ok") { set_user_(&a, "access_pending", serde_json::Value::Null); show_gtg(&h, &a); use tauri::Manager; if let Some(w) = h.get_webview_window("access") { let _ = w.close(); } }
        r.map(String::from) }).await.map_err(|e| e.to_string())
}
/// Windows clipboard text (the guide fills the email box as soon as you copy one; builder Paste).
#[tauri::command]
fn clip_text() -> String {
    #[cfg(windows)] unsafe {
        #[link(name = "user32")] extern "system" { fn OpenClipboard(h: isize) -> i32; fn CloseClipboard() -> i32; fn GetClipboardData(f: u32) -> isize; }
        #[link(name = "kernel32")] extern "system" { fn GlobalLock(h: isize) -> *const u16; fn GlobalUnlock(h: isize) -> i32; }
        if OpenClipboard(0) == 0 { return String::new(); }
        let h = GetClipboardData(13); let mut out = String::new();
        if h != 0 { let p = GlobalLock(h); if !p.is_null() { let mut n = 0; while *p.add(n) != 0 && n < 100_000 { n += 1; } out = String::from_utf16_lossy(std::slice::from_raw_parts(p, n)); GlobalUnlock(h); } }
        CloseClipboard(); return out;
    }
    #[allow(unreachable_code)] String::new()
}

// ---- Your Spotify app (1.0.9 byo.py, approved v3 guide): your own Client ID instead of the shared app
fn show_own(h: &tauri::AppHandle) { let h2 = h.clone(); let _ = h.run_on_main_thread(move || small_window(&h2, "own", "own.html", 500.0, 922.0)); }
#[tauri::command]
fn open_own(h: tauri::AppHandle) { show_own(&h); }
#[tauri::command]
fn own_info(app: tauri::State<Arc<AppState>>) -> serde_json::Value { serde_json::json!({ "own": app.settings.lock().unwrap().own_app, "light": windows_light() }) }
fn close_guides(h: &tauri::AppHandle) { use tauri::Manager; for l in ["own", "access"] { if let Some(w) = h.get_webview_window(l) { let _ = w.close(); } } }
/// Save and log in: a valid Client ID (32 hex, not the secret) -> settings, switch the client (drops the old login), log in (PKCE).
#[tauri::command]
fn own_save(h: tauri::AppHandle, app: tauri::State<Arc<AppState>>, cid: String) -> String {
    let c = cid.trim().to_lowercase(); if !settings::client_id_ok(&c) { return "bad".into(); }
    set_user_(&app, "client_id", serde_json::json!(c)); set_user_(&app, "own_app", serde_json::json!(true));
    if app.spotify.lock().unwrap().set_client(&c) { launcher::log("Using your own Spotify app"); }
    close_guides(&h); do_login(h.clone(), app.inner().clone()); "saved".into()
}
/// Use the shared app instead: back to the installer's client (drops the login only when it changes).
#[tauri::command]
fn own_shared(h: tauri::AppHandle, app: tauri::State<Arc<AppState>>) {
    set_user_(&app, "client_id", serde_json::Value::Null); set_user_(&app, "own_app", serde_json::Value::Null);
    let shared = app.settings.lock().unwrap().shared_client_id.clone();
    let changed = app.spotify.lock().unwrap().set_client(&shared);
    close_guides(&h); if changed { launcher::log("Using the shared Spotify app"); do_login(h.clone(), app.inner().clone()); }
}
#[tauri::command]
fn show_panel(app: tauri::AppHandle) { use tauri::Manager; if let Some(w) = app.get_webview_window("main") { let _ = w.show(); let _ = w.unminimize(); let _ = w.set_focus(); } }

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


// ---- updates (1.0.9 updater.py): GitHub release Setup .exe, size + SHA-256 checked, silent in-place install
fn ver_t(v: &str) -> Vec<u32> { let mut n: Vec<u32> = v.split(|c: char| !c.is_ascii_digit()).filter(|x| !x.is_empty()).take(3).map(|x| x.parse().unwrap_or(0)).collect(); n.resize(3, 0); n }
fn latest() -> Result<Option<serde_json::Value>, String> {
    let api = launcher::test_env("AOE4S_UPDATE_API").unwrap_or_else(|| "https://api.github.com/repos/Capstar1/aoe4-spotify/releases/latest".into());
    let v: serde_json::Value = ureq::get(&api).set("User-Agent", "aoe4-spotify").set("Accept", "application/vnd.github+json").timeout(Duration::from_secs(8)).call().map_err(|e| e.to_string())?.into_json().map_err(|e| e.to_string())?;
    let tag = v["tag_name"].as_str().unwrap_or("");
    if ver_t(tag) <= ver_t(env!("CARGO_PKG_VERSION")) { return Ok(None); }
    let Some(a) = v["assets"].as_array().and_then(|a| a.iter().find(|a| a["name"].as_str().unwrap_or("").to_lowercase().ends_with(".exe"))) else { return Ok(None) };
    let dg = a["digest"].as_str().unwrap_or("");
    Ok(Some(serde_json::json!({ "version": tag.trim_start_matches(['v', 'V']), "url": a["browser_download_url"], "size": a["size"], "sha256": dg.split("sha256:").nth(1).unwrap_or("") })))
}
fn download(info: &serde_json::Value, dest: &std::path::Path, mut progress: impl FnMut(f64)) -> Result<(), String> {
    use sha2::Digest; use std::io::{Read, Write};
    let part = dest.with_extension("part");
    let r = (|| -> Result<(), String> {
        let resp = ureq::get(info["url"].as_str().unwrap_or("")).set("User-Agent", "aoe4-spotify").timeout(Duration::from_secs(120)).call().map_err(|e| e.to_string())?;
        let total = info["size"].as_u64().filter(|n| *n > 0).or_else(|| resp.header("Content-Length").and_then(|s| s.parse().ok())).unwrap_or(0);
        let mut rd = resp.into_reader(); let mut f = std::fs::File::create(&part).map_err(|e| e.to_string())?;
        let mut h = sha2::Sha256::new(); let mut got = 0u64; let mut buf = vec![0u8; 65536];
        loop { let n = rd.read(&mut buf).map_err(|e| e.to_string())?; if n == 0 { break; } f.write_all(&buf[..n]).map_err(|e| e.to_string())?; h.update(&buf[..n]); got += n as u64; if total > 0 { progress((got as f64 / total as f64).min(1.0)); } }
        drop(f);
        if let Some(sz) = info["size"].as_u64().filter(|n| *n > 0) { if got != sz { return Err(format!("size mismatch ({got} of {sz} bytes)")); } }
        let want = info["sha256"].as_str().unwrap_or(""); let hx: String = h.finalize().iter().map(|b| format!("{b:02x}")).collect();
        if !want.is_empty() && !hx.eq_ignore_ascii_case(want) { return Err("checksum mismatch".into()); }
        std::fs::rename(&part, dest).map_err(|e| e.to_string())
    })();
    let _ = std::fs::remove_file(&part); r
}
fn run_setup(setup: &std::path::Path, relaunch: bool) {
    let lg = format!("/LOG={}", launcher::data_dir().join("update_setup.log").display());
    let mut a = vec!["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]; a.push(if relaunch { "/RELAUNCH=1" } else { "/FROMSWITCHER=1" });
    let mut c = std::process::Command::new(setup); c.args(&a).arg(&lg);
    for (k, _) in std::env::vars() { let l = k.to_lowercase(); if l.starts_with("steam") || l.starts_with("steam_") { c.env_remove(k); } }
    if !relaunch { use std::os::windows::process::CommandExt; c.creation_flags(0x0800_0000); }
    match c.spawn() { Ok(_) => launcher::log(&format!("Update: running {}", setup.display())), Err(e) => launcher::log(&format!("Update: could not start setup: {e}")) }
}
/// Update pill (panel): check at start; "↓ Update x" downloads with progress and installs (relaunches the panel).
#[tauri::command]
async fn check_update(app: tauri::State<'_, Arc<AppState>>) -> Result<String, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || match latest() {
        Ok(Some(i)) => { let v = i["version"].as_str().unwrap_or("").to_string(); *a.upd.lock().unwrap() = serde_json::json!({ "phase": "avail", "info": i }); format!("\u{2193} Update {v}") }
        Ok(None) => "Up to date".into(), Err(_) => "Couldn't check".into() }).await.map_err(|e| e.to_string())
}
#[tauri::command]
fn start_update(app: tauri::State<Arc<AppState>>) {
    let a = app.inner().clone(); let u = a.upd.lock().unwrap().clone();
    if !matches!(u["phase"].as_str(), Some("avail" | "error")) || u["info"].is_null() { return; }
    if launcher::aoe_running() { *a.upd.lock().unwrap() = serde_json::json!({ "phase": "error", "msg": "Close Age of Empires IV to update", "info": u["info"] }); return; }   // setup won't install mid-game
    *a.upd.lock().unwrap() = serde_json::json!({ "phase": "dl", "pct": 0, "info": u["info"] });
    std::thread::spawn(move || {
        let info = u["info"].clone(); let dest = std::env::temp_dir().join(format!("AoE4 Spotify Setup {}.exe", info["version"].as_str().unwrap_or("")));
        let a2 = a.clone();
        match download(&info, &dest, |f| { a2.upd.lock().unwrap()["pct"] = serde_json::json!((f * 100.0) as i64); }) {
            Ok(_) => { *a.upd.lock().unwrap() = serde_json::json!({ "phase": "run", "info": info }); run_setup(&dest, true); std::thread::sleep(Duration::from_millis(400)); std::process::exit(0); }
            Err(e) => { launcher::log(&format!("Update failed: {e}")); *a.upd.lock().unwrap() = serde_json::json!({ "phase": "error", "msg": "Update failed \u{2013} retry", "info": info }); }
        }
    });
}
static PENDING_SETUP: Mutex<Option<PathBuf>> = Mutex::new(None);
/// Switcher (started with the game): newer release -> download in the background; install silently once no match
/// is on and the game is closed (setup refuses while AoE4 runs). Same 6 h no-retry mark as 1.0.9.
fn auto_update(app: Arc<AppState>) {
    let Ok(Some(info)) = latest() else { return };
    let v = info["version"].as_str().unwrap_or("").to_string(); let mark = app.dir.join("auto_update.json");
    let last: serde_json::Value = std::fs::read_to_string(&mark).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    if last["v"] == serde_json::json!(v) && wall() - last["t"].as_f64().unwrap_or(0.0) < 6.0 * 3600.0 { launcher::log(&format!("Auto-update: {v} was already installed recently but this is still {} - not retrying for now", env!("CARGO_PKG_VERSION"))); return; }
    launcher::log(&format!("Auto-update: {v} available - downloading in the background"));
    let dest = std::env::temp_dir().join(format!("AoE4.Spotify.Setup-{v}.exe"));
    if let Err(e) = download(&info, &dest, |_| {}) { launcher::log(&format!("Auto-update: download failed ({e}) - trying again next launch")); return; }
    let _ = std::fs::write(&mark, serde_json::json!({ "v": v, "t": wall() }).to_string());
    launcher::log(&format!("Auto-update: {v} ready - installing between matches, after the game closes"));
    *PENDING_SETUP.lock().unwrap() = Some(dest);
}
fn install_pending(app: &AppState) {
    if app.status.lock().unwrap().in_match { return; }     // never mid-match
    if let Some(p) = PENDING_SETUP.lock().unwrap().take() { run_setup(&p, false); }
}

#[tauri::command]
fn cfg() -> serde_json::Value { serde_json::json!({ "order": std::env::var("AOE4S_ORDER").unwrap_or_default(), "pl_closed": std::env::var_os("AOE4S_PL_CLOSED").is_some(), "menutest": std::env::var_os("AOE4S_MENUTEST").is_some(), "open": std::env::var("AOE4S_OPEN").unwrap_or_default(), "edtest": std::env::var_os("AOE4S_EDTEST").is_some(), "addtest": std::env::var_os("AOE4S_ADDTEST").is_some() }) }

#[tauri::command]
fn logout(app: tauri::State<Arc<AppState>>) { app.spotify.lock().unwrap().logout(); push(&app.status, "Spotify: logged out".into()); }


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
    let spotify = Spotify::new(settings.client_id.clone(), dir.join("token.json"));
    let (tx, rx) = channel(); let replays0 = prefs["music_in_replays"].as_bool().unwrap_or(settings.music_in_replays);
    let app = Arc::new(AppState { pick: Mutex::new(serde_json::Value::Null), gtg: Mutex::new(serde_json::Value::Null), settings: Mutex::new(settings), ver: Default::default(), upd: Mutex::new(serde_json::json!({ "phase": if std::env::args().any(|a| a == "--updated") { "done" } else { "idle" }, "msg": format!("Updated to {}", env!("CARGO_PKG_VERSION")) })), ages, status: Mutex::new(status), 
        replays: AtomicBool::new(replays0), busy: AtomicBool::new(false), spotify: Mutex::new(spotify), tx: Mutex::new(tx), ed: Mutex::new(load_ed(&dir)), dir });
    let a2 = app.clone(); std::thread::spawn(move || watch(a2, path));
    let a3 = app.clone(); std::thread::spawn(move || player(a3, rx));
    tauri::Builder::default()
        .manage(app)
        .setup(move |a| { use tauri::Manager; if let Some(h) = a.get_webview_window("main").and_then(|w| w.hwnd().ok()) { shadow::init(h.0 as isize); } if zoom() != 1.0 { let w = a.get_webview_window("main").unwrap(); let _ = w.set_zoom(zoom()); let _ = w.set_size(tauri::LogicalSize::new(554.0 * zoom(), 880.0 * zoom())); }
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
        .invoke_handler(tauri::generate_handler![get_state, login, logout, resize, cfg, cover, region, shadow, preview, save_ed, encode_preset, decode_preset, sp, cache_covers, open_add, dbg, menu, check_update, show_panel, set_user, set_enabled, start_update, open_pick, pick_done, pick_info, gtg_info, gtg_fix, save_list, delete_list, access_info, access_send, access_check, clip_text, open_own, own_info, own_save, own_shared])
        .run(tauri::generate_context!())
        .expect("error while running AoE4 Spotify");
}