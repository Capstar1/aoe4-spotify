//! 1.1 data: 1.0.9 import, your settings (config.json), Age Intros edits and share codes.
use super::*;

pub const ED_KEYS: [&str; 6] = ["intro_pools", "intro_ages", "custom_songs", "intro_presets", "intro_preset", "intro_pack_open"];
/// Age Intros edits made in 1.1 live in 1.1's own intros.json (seeded once from 1.0.9's settings), so the
/// installed 1.0.9 config is never written.
pub fn load_ed(dir: &std::path::Path) -> serde_json::Value {
    if let Some(v) = std::fs::read_to_string(dir.join("intros.json")).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()) { return v; }
    let u: serde_json::Value = std::fs::read_to_string(dir.join("config.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    let mut m = serde_json::Map::new(); for k in ED_KEYS { if !u[k].is_null() { m.insert(k.into(), u[k].clone()); } } serde_json::Value::Object(m)
}
/// One-time import of the 1.0.9 data (install config, settings, playlist names, intros/presets, cover cache) into
/// 1.1's own folder; afterwards 1.1 reads only its own files. Writes import.json with the copied counts.
pub fn import_109(dir: &std::path::Path) {
    if !dir.join("import.json").exists() { let _ = migrate_109(dir, None, false); return; }
    // the installer's cleanup can leave the 1.0.9 folder behind (its update log was still open): finish it once verified
    let ad = PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify");
    let ok = std::fs::read_to_string(dir.join("import.json")).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()).map_or(false, |v| v["ok"] == true && v["cleaned"] == true);
    if ok && ad.exists() { let _ = std::fs::remove_dir_all(&ad); }
}
pub fn count_json(p: &std::path::Path, f: impl Fn(&serde_json::Value) -> usize) -> usize { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()).map(|v| f(&v)).unwrap_or(0) }
pub fn cnt(v: &serde_json::Value) -> usize { v.as_array().map(|a| a.len()).or_else(|| v.as_object().map(|o| o.len())).unwrap_or(0) }
/// 1.0.9 -> 1.1 import (installer runs `--migrate-109 [--cleanup]`, first run does the same without cleanup):
/// settings, playlist names, intros + presets, cover cache, the Spotify login (refresh token, never logged) and the
/// saved game-music level (1.0.9 kept it next to its exe). Copies only; verified by counts; with cleanup the 1.0.9
/// data is deleted only after the copy verified. Returns Ok(summary) when verified.
pub fn migrate_109(dir: &std::path::Path, inst109: Option<PathBuf>, cleanup: bool) -> Result<serde_json::Value, String> {
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
pub fn with_ed(s: &Settings, ed: &serde_json::Value) -> Settings {
    let mut s = s.clone(); s.user_pools = ed["intro_pools"].clone(); s.custom_songs = ed["custom_songs"].clone();
    s.intro_ages = ed["intro_ages"].as_object().map(|o| o.iter().filter_map(|(k, v)| v.as_bool().map(|b| (k.clone(), b))).collect()).unwrap_or_default(); s
}
#[tauri::command]
pub fn save_ed(app: tauri::State<Arc<AppState>>, u: serde_json::Value) {
    let mut m = serde_json::Map::new(); for k in ED_KEYS { if !u[k].is_null() { m.insert(k.into(), u[k].clone()); } }
    let v = serde_json::Value::Object(m); let _ = std::fs::create_dir_all(&app.dir);
    let _ = std::fs::write(app.dir.join("intros.json"), serde_json::to_string_pretty(&v).unwrap_or_default()); *app.ed.lock().unwrap() = v;
}
/// 1.0.9 share codes: "AOE4S1:" + urlsafe base64 (no padding) of zlib(json {v,name,pools,ages,custom}).
#[tauri::command]
pub fn encode_preset(p: serde_json::Value) -> String {
    use std::io::Write; use base64::Engine;
    let d = serde_json::json!({ "v": 1, "name": p["name"], "pools": p["pools"], "ages": p["ages"], "custom": p["custom"] });
    let mut z = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::best()); let _ = z.write_all(d.to_string().as_bytes());
    format!("AOE4S1:{}", base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(z.finish().unwrap_or_default()))
}
#[tauri::command]
pub fn decode_preset(app: tauri::State<Arc<AppState>>, code: String) -> Result<serde_json::Value, String> {
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

pub fn save_prefs(app: &AppState) {
    let _ = std::fs::create_dir_all(&app.dir);
    let _ = std::fs::write(app.dir.join("settings.json"), serde_json::json!({ "music_in_replays": app.replays.load(Ordering::SeqCst) }).to_string());
}

/// Your settings (config.json), parsed once and reused until the file changes (size / modified time) or set_user_ writes it.
pub type UserCache = Option<(PathBuf, Option<(SystemTime, u64)>, serde_json::Value)>;
pub static USER: Mutex<UserCache> = Mutex::new(None);
pub(crate) fn read_user(dir: &std::path::Path) -> serde_json::Value {
    let p = dir.join("config.json"); let key = std::fs::metadata(&p).ok().and_then(|m| Some((m.modified().ok()?, m.len())));
    let mut c = USER.lock().unwrap();
    if let Some((cp, ck, v)) = c.as_ref() { if *cp == p && *ck == key && key.is_some() { return v.clone(); } }
    let v = std::fs::read_to_string(&p).ok().and_then(|s| serde_json::from_str(&s).ok()).filter(|v: &serde_json::Value| v.is_object()).unwrap_or_else(|| serde_json::json!({}));
    *c = Some((p, key, v.clone())); v
}
pub const LIST_PREFIX: &str = "aoe4s:list:";
/// Age playlists with app-only lists (1.0.9 custom_lists) expanded to "uris:" + their tracks.
pub fn resolve(s: &Settings) -> std::collections::HashMap<String, String> {
    let u = read_user(&launcher::data_dir());
    s.playlists.iter().map(|(k, v)| (k.clone(), expand(&u, v))).collect()
}
pub fn expand(u: &serde_json::Value, v: &str) -> String {
    match v.strip_prefix(LIST_PREFIX) { Some(id) if id != "liked" => {
        let t: Vec<String> = u["custom_lists"][id]["tracks"].as_array().cloned().unwrap_or_default().iter().filter_map(|t| t["uri"].as_str().map(String::from)).collect();
        if t.is_empty() { String::new() } else { format!("uris:{}", t.join(",")) } }
        _ => v.to_string() }
}
/// 1.0.9 after_match_cfg: mode resume|playlist|stop, Win / Loss switch, its picks.
pub fn after_cfg(s: &Settings) -> aoe4core::switcher::AfterMatch {
    let a = &s.after_match; let u = read_user(&launcher::data_dir());
    let g = |k: &str| a[k].as_str().filter(|v| v.starts_with("spotify:playlist:") || v.starts_with("spotify:track:") || v.starts_with(LIST_PREFIX)).map(|v| expand(&u, v)).unwrap_or_default();
    let old_wl = a["mode"] == "winloss";
    let mode = match a["mode"].as_str() { Some(m @ ("resume" | "playlist" | "stop")) => m.to_string(), None => "resume".into(), _ => "stop".into() };
    let pl = g("playlist"); let pl = if pl.starts_with("spotify:track:") { String::new() } else { pl };
    aoe4core::switcher::AfterMatch { mode, wl: a["winloss_on"].as_bool().unwrap_or(old_wl), playlist: pl, win: g("win"), loss: g("loss") }
}
/// 1.0.9 set_user: one key of %APPDATA%\AoE4Spotify-1.1\config.json (null removes it), then live everywhere.
pub fn set_user_(app: &AppState, k: &str, v: serde_json::Value) {
    let mut u = read_user(&app.dir);
    if v.is_null() { u.as_object_mut().map(|o| o.remove(k)); } else { u[k] = v; }
    let _ = std::fs::create_dir_all(&app.dir);
    let tmp = app.dir.join("config.json.tmp");
    if std::fs::write(&tmp, serde_json::to_string_pretty(&u).unwrap_or_default()).is_ok() { let _ = std::fs::rename(&tmp, app.dir.join("config.json")); }
    *USER.lock().unwrap() = None;
    let mut s = app.settings.lock().unwrap(); let names = s.playlist_names.clone(); *s = settings::load_own(&app.dir);
    for (k2, v2) in names { s.playlist_names.entry(k2).or_insert(v2); }
    drop(s); app.ver.fetch_add(1, Ordering::SeqCst);
}
#[tauri::command]
pub fn set_user(app: tauri::State<Arc<AppState>>, k: String, v: serde_json::Value) {
    const OK: [&str; 6] = ["enabled", "fade_seconds", "playlists", "boss_intro_enabled", "after_match", "custom_lists"];
    if OK.contains(&k.as_str()) { set_user_(&app, &k, v); }
}
/// Enabled switch (1.0.9): save, then mute / give back the game music in the background.
#[tauri::command]
pub fn set_enabled(app: tauri::State<Arc<AppState>>, on: bool) {
    set_user_(&app, "enabled", serde_json::json!(on));
    push(&app.status, if on { "Enabled".into() } else { "Disabled".into() });
    std::thread::spawn(move || { launcher::music_sync(on); });
}

pub fn read_json(p: &std::path::Path) -> serde_json::Value { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(&s).ok()).filter(|v: &serde_json::Value| v.is_object()).unwrap_or_else(|| serde_json::json!({})) }
