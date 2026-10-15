//! 1.1 data: 1.0.9 import, your settings (config.json), Age Intros edits and share codes.
use crate::Engine;
use aoe4core::settings::{self, Settings};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

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
    let inst = inst109.unwrap_or_else(crate::sys::install_dir);
    let base = [inst.join("config.json"), inst.join(r"_internal\config.json"), PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or_default()).join(r"Programs\AoE4 Spotify\_internal\config.json")].into_iter().find(|p| p.is_file());
    // Nothing of 1.0.9's user data left (fresh install, or already imported and cleaned): quietly do nothing -
    // no "NOT verified" log line. An old "not verified" import.json from when 1.0.9 data still existed is replaced
    // (that data is gone, so there is nothing left to verify or keep).
    if !ad.join("config.json").exists() && !ad.join("token.json").exists() && !inst.join("game_music.json").is_file() {
        let old: Value = std::fs::read_to_string(dir.join("import.json")).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
        if old.is_object() && old["ok"] != true { let _ = std::fs::write(dir.join("import.json"), json!({ "from": "1.0.9", "ok": true, "nothing_left": true, "cleaned": true, "earlier": old, "at": iso_now() }).to_string()); }
        return Err("no 1.0.9 data".into());
    }
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
    // a copy is verified when everything in the 1.0.9 original is in 1.1's copy (1.1 may already have more of its own)
    let has = |a: &std::path::Path, b: &std::path::Path, key: &str| { let (x, y) = (read_json(a), read_json(b)); covered(&x[key], &y[key]) };
    let src_cfg = ad.join("config.json");
    let checks = json!({
        "custom_songs": [k(&src_cfg, "custom_songs"), k(&dir.join("intros.json"), "custom_songs")],
        "intro_presets": [k(&src_cfg, "intro_presets"), k(&dir.join("intros.json"), "intro_presets")],
        "intro_pools": [k(&src_cfg, "intro_pools"), k(&dir.join("intros.json"), "intro_pools")],
        "playlists": [k(&src_cfg, "playlists"), k(&dir.join("config.json"), "playlists")],
        "covers": [src, n] });
    let i2 = dir.join("intros.json"); let c2 = dir.join("config.json");
    let counts_ok = src == n && has(&src_cfg, &i2, "custom_songs") && has(&src_cfg, &i2, "intro_presets") && has(&src_cfg, &i2, "intro_pools") && has(&src_cfg, &c2, "playlists");
    let ok = ok_base && ok_cfg && ok_names && ok_tok && ok_music && counts_ok;
    let sum = json!({ "from": "1.0.9", "ok": ok, "base": ok_base, "config": ok_cfg, "playlist_names": ok_names, "token": rt.is_some() && ok_tok, "music_level": gm.is_file(), "counts": checks, "at": iso_now() });
    let _ = std::fs::write(dir.join("import.json"), sum.to_string());
    if !ok { crate::sys::log("1.0.9 import NOT verified - 1.0.9 data kept"); return Err(sum.to_string()); }
    crate::sys::log("1.0.9 settings, intros, presets, covers and login imported (verified)");
    if cleanup {
        let _ = std::fs::remove_dir_all(&ad); let _ = std::fs::remove_file(&gm);
        let mut s2 = sum.clone(); s2["cleaned"] = serde_json::json!(true); let _ = std::fs::write(dir.join("import.json"), s2.to_string());
        crate::sys::log(if ad.exists() { "1.0.9 data removed after the verified import (an open log file goes on next start)" } else { "1.0.9 data removed after the verified import" });
    }
    Ok(sum)
}
/// Every entry of `src` is in `dst` (objects: same keys; arrays: same elements). Nothing in `src` = covered.
pub fn covered(src: &serde_json::Value, dst: &serde_json::Value) -> bool {
    match src {
        serde_json::Value::Object(o) => o.keys().all(|k| dst.get(k).is_some()),
        serde_json::Value::Array(a) => a.iter().all(|x| dst.as_array().map_or(false, |d| d.contains(x))),
        _ => true,
    }
}
/// UTC timestamp like 2026-10-15T03:19:48Z (import.json).
pub fn iso_now() -> String {
    let s = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) as i64;
    let (days, t) = (s.div_euclid(86400), s.rem_euclid(86400));
    // civil-from-days (Howard Hinnant)
    let z = days + 719468; let era = z.div_euclid(146097); let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365; let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153; let d = doy - (153 * mp + 2) / 5 + 1; let m = if mp < 10 { mp + 3 } else { mp - 9 }; let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    format!("{y:04}-{m:02}-{d:02}T{:02}:{:02}:{:02}Z", t / 3600, t / 60 % 60, t % 60)
}
pub fn with_ed(s: &Settings, ed: &serde_json::Value) -> Settings {
    let mut s = s.clone(); s.user_pools = ed["intro_pools"].clone(); s.custom_songs = ed["custom_songs"].clone();
    s.intro_ages = ed["intro_ages"].as_object().map(|o| o.iter().filter_map(|(k, v)| v.as_bool().map(|b| (k.clone(), b))).collect()).unwrap_or_default(); s
}
pub fn save_prefs(app: &Engine) {
    let _ = std::fs::create_dir_all(&app.dir);
    let p = app.dir.join("settings.json");
    let mut u = aoe4core::userstore::read_json(&p);
    u["music_in_replays"] = serde_json::json!(app.replays.load(Ordering::SeqCst));
    u["finish_song"] = serde_json::json!(app.finish.load(Ordering::SeqCst));
    let _ = aoe4core::userstore::write_atomic(&p, &u);
}

/// Your settings (config.json), parsed once and reused until the file changes (size / modified time) or set_user_ writes it.
pub type UserCache = Option<(PathBuf, Option<(SystemTime, u64)>, serde_json::Value)>;
pub static USER: Mutex<UserCache> = Mutex::new(None);
pub fn read_user(dir: &std::path::Path) -> serde_json::Value {
    let p = dir.join("config.json"); let key = std::fs::metadata(&p).ok().and_then(|m| Some((m.modified().ok()?, m.len())));
    let mut c = USER.lock().unwrap();
    if let Some((cp, ck, v)) = c.as_ref() { if *cp == p && *ck == key && key.is_some() { return v.clone(); } }
    let v = std::fs::read_to_string(&p).ok().and_then(|s| serde_json::from_str(&s).ok()).filter(|v: &serde_json::Value| v.is_object()).unwrap_or_else(|| serde_json::json!({}));
    *c = Some((p, key, v.clone())); v
}
pub const LIST_PREFIX: &str = "aoe4s:list:";
/// Age playlists with app-only lists (1.0.9 custom_lists) expanded to "uris:" + their tracks.
pub fn resolve(s: &Settings) -> std::collections::HashMap<String, String> {
    let u = read_user(&crate::sys::data_dir());
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
    let a = &s.after_match; let u = read_user(&crate::sys::data_dir());
    let g = |k: &str| a[k].as_str().filter(|v| v.starts_with("spotify:playlist:") || v.starts_with("spotify:track:") || v.starts_with(LIST_PREFIX)).map(|v| expand(&u, v)).unwrap_or_default();
    let old_wl = a["mode"] == "winloss";
    let mode = match a["mode"].as_str() { Some(m @ ("resume" | "playlist" | "stop")) => m.to_string(), None => "resume".into(), _ => "stop".into() };
    let pl = g("playlist"); let pl = if pl.starts_with("spotify:track:") { String::new() } else { pl };
    aoe4core::switcher::AfterMatch { mode, wl: a["winloss_on"].as_bool().unwrap_or(old_wl), playlist: pl, win: g("win"), loss: g("loss") }
}
/// 1.0.9 set_user: one key of %APPDATA%\AoE4Spotify-1.1\config.json (null removes it), then live everywhere.
pub fn set_user_(app: &Engine, k: &str, v: serde_json::Value) {
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
/// 1.1 `set_user` allow-list (the panel may only write these keys).
pub fn set_user(app: &Engine, k: &str, v: serde_json::Value) -> bool { if aoe4core::userstore::USER_KEYS.contains(&k) { set_user_(app, k, v); true } else { false } }
/// Enabled switch (1.0.9): save, then mute / give back the game music in the background.
pub fn set_enabled(app: &Engine, on: bool) {
    set_user_(app, "enabled", serde_json::json!(on));
    app.push(if on { "Enabled".into() } else { "Disabled".into() });
    std::thread::spawn(move || { crate::sys::music_sync(on); });
}

pub fn read_json(p: &std::path::Path) -> serde_json::Value { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(&s).ok()).filter(|v: &serde_json::Value| v.is_object()).unwrap_or_else(|| serde_json::json!({})) }
