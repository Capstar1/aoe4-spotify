//! Engine state (the same JSON the Tauri panel got from get_state) -> Panel properties. No logic beyond what
//! ui/app.js drawMain computes for display (names, truncation, covers, after-match config).
use crate::Panel;
use serde_json::Value;
use slint::{Image, ModelRc, VecModel};
use std::cell::RefCell;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

thread_local! { static COVERS: RefCell<(u64, HashMap<String, Option<Image>>)> = RefCell::new((0, HashMap::new())); }

/// 1.1 `trunc`: at most n characters, the last one an ellipsis (width fitting is the view's elide).
pub fn trunc(t: &str, n: usize) -> String { if t.chars().count() <= n { t.to_string() } else { t.chars().take(n - 1).collect::<String>() + "\u{2026}" } }

/// 1.1 plName.
pub fn pl_name(s: &Value, uri: &str) -> String {
    if uri.is_empty() { return String::new(); }
    let id = uri.rsplit(':').next().unwrap_or("");
    if uri.starts_with("aoe4s:list:") { return if id == "liked" { "Liked Songs".into() } else { s["user"]["custom_lists"][id]["name"].as_str().unwrap_or("My list").into() }; }
    s["settings"]["playlist_names"][id].as_str().map(String::from).unwrap_or_else(|| if uri.starts_with("spotify:track:") { "Song".into() } else { "Playlist".into() })
}

/// Cached cover file for a uri (same lookup as the 1.1 `cover` command).
pub fn cover_path(dir: &Path, uri: &str) -> Option<PathBuf> {
    if uri.is_empty() { return None; }
    let d = dir.join("covers"); let id = uri.rsplit(':').next()?;
    if uri.contains(":list:") { let p = d.join(format!("list_{id}.png")); return p.is_file().then_some(p); }
    if uri.starts_with("spotify:track:") { let p = d.join(format!("track_{id}.jpg")); return p.is_file().then_some(p); }
    std::fs::read_dir(&d).ok()?.flatten().filter(|e| e.file_name().to_string_lossy().starts_with(&format!("{id}_")))
        .max_by_key(|e| e.metadata().and_then(|m| m.modified()).ok()).map(|e| e.path())
}
/// Cover image (cached per covers version; misses retried when covers change).
pub fn cover(dir: &Path, uri: &str) -> (Image, bool) {
    let v = aoe4engine::picker::COVERS_VER.load(std::sync::atomic::Ordering::SeqCst);
    COVERS.with(|c| { let mut c = c.borrow_mut(); if c.0 != v { *c = (v, HashMap::new()); }
        let img = c.1.entry(uri.to_string()).or_insert_with(|| cover_path(dir, uri).and_then(|p| Image::load_from_path(&p).ok())).clone();
        match img { Some(i) => (i, true), None => (Image::default(), false) } })
}

/// 1.1 amCfg.
pub fn am_cfg(set: &Value) -> (String, bool, String, String, String) {
    let a = if set["after_match"].is_object() { set["after_match"].clone() } else { serde_json::json!({}) };
    let ok = |v: &Value| -> String { let s = v.as_str().unwrap_or(""); let id_ok = |id: &str, n: Option<usize>| !id.is_empty() && id.chars().all(|c| c.is_ascii_alphanumeric()) && n.map_or(true, |n| id.len() == n);
        if let Some(id) = s.strip_prefix("spotify:playlist:").or_else(|| s.strip_prefix("spotify:track:")) { if id_ok(id, Some(22)) { return s.into(); } }
        if let Some(id) = s.strip_prefix("aoe4s:list:") { if id_ok(id, None) { return s.into(); } } String::new() };
    let pl = ok(&a["playlist"]);
    let mode = match a["mode"].as_str() { Some(m @ ("resume" | "playlist" | "stop")) => m.to_string(), _ if a.get("mode").is_some() => "stop".into(), _ => "resume".into() };
    let wl = a["winloss_on"].as_bool().unwrap_or(a["mode"] == "winloss");
    (mode, wl, if pl.starts_with("spotify:track:") { String::new() } else { pl }, ok(&a["win"]), ok(&a["loss"]))
}

/// Index of the age row with the fire: the age that is playing in a match (1.1: in_match && playing && age == k).
pub fn playing_row(s: &Value) -> i32 {
    let st = &s["status"];
    if st["in_match"] != true || st["playing"].is_null() { return -1; }
    s["ages"].as_array().and_then(|a| a.iter().position(|x| x[0] == st["age"])).map_or(-1, |i| i as i32)
}

/// Fill the main panel from a full state.
pub fn fill(ui: &Panel, s: &Value, dir: &Path) {
    let set = &s["settings"]; let sp = &s["spotify"]; let st = &s["status"];
    ui.set_enabled(set["enabled"].as_bool().unwrap_or(true));
    ui.set_logged_in(sp["logged_in"] == true); ui.set_busy(sp["busy"] == true); ui.set_replays(sp["replays"] == true);
    ui.set_in_match(st["in_match"] == true);
    ui.set_fade(set["fade_seconds"].as_f64().unwrap_or(2.0) as f32);
    ui.set_default_fade(set["default_fade"].as_f64().unwrap_or(2.0) as f32);
    ui.set_boss_on(set["boss_on"].as_bool().unwrap_or(true));
    let ages = s["ages"].as_array().cloned().unwrap_or_default();
    let rows: Vec<crate::AgeRow> = ages.iter().map(|a| {
        let k = a[0].as_str().unwrap_or(""); let lab = a[1].as_str().unwrap_or("");
        let uri = set["playlists"][k].as_str().unwrap_or("").to_string(); let (cover, has) = cover(dir, &uri);
        let n = pl_name(s, &uri); let name = if !n.is_empty() { trunc(&n, 15) } else if !uri.is_empty() { "Playlist".into() } else { "Not set".into() };
        let id = uri.rsplit(':').next().unwrap_or("");
        crate::AgeRow { label: lab.replace(" Age", "").into(), name: name.into(), set: !uri.is_empty(), cover, has_cover: has,
            is_default: uri == set["default_playlists"][k].as_str().unwrap_or(""), openable: !id.is_empty() && !uri.starts_with("aoe4s:list:") }
    }).collect();
    ui.set_ages(ModelRc::new(VecModel::from(rows)));
    ui.set_intros(ModelRc::new(VecModel::from(ages.iter().enumerate().map(|(j, a)| crate::IntroAge {
        roman: ["I", "II", "III", "IV", "V", "VI"].get(j).copied().unwrap_or("").into(), lit: s["intros"][a[0].as_str().unwrap_or("")]["on"] == true }).collect::<Vec<_>>())));
    let (mode, wl, pl, win, loss) = am_cfg(set);
    ui.set_am_mode(mode.into()); ui.set_am_wl(wl);
    ui.set_am_playlist_name(trunc(&pl_name(s, &pl), 10).into()); ui.set_am_header_name(trunc(&pl_name(s, &pl), 14).into());
    let (c, h) = cover(dir, &pl); ui.set_am_playlist_cover(c); ui.set_am_playlist_has(h);
    let (c, h) = cover(dir, &win); ui.set_win_cover(c); ui.set_win_has(h);
    let (c, h) = cover(dir, &loss); ui.set_loss_cover(c); ui.set_loss_has(h);
}

/// Update pill text / error / clickable / gear badge (1.1 drawMain), `msg` = a transient local message.
pub fn pill(upd: &Value, msg: Option<(&str, bool)>, done_gone: bool) -> (String, bool, bool, bool) {
    let ph = upd["phase"].as_str().unwrap_or("idle"); let info = &upd["info"];
    let badge = !info.is_null() && (ph == "avail" || ph == "error");
    if let Some((m, e)) = msg { return (m.into(), e, false, badge); }
    if ph == "idle" || (ph == "done" && done_gone) { return (String::new(), false, false, badge); }
    let lab = match ph { "avail" => format!("\u{2193} Update {}", info["version"].as_str().unwrap_or("")), "dl" => format!("Downloading {}%", upd["pct"].as_i64().unwrap_or(0)),
        "run" => "Installing\u{2026}".into(), "error" => upd["msg"].as_str().unwrap_or("Update failed").into(), "done" => upd["msg"].as_str().unwrap_or("").into(), _ => String::new() };
    (lab, ph == "error", badge, badge)
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    #[test] fn trunc_like_1_1() { assert_eq!(super::trunc("Chill Lofi Study", 15), "Chill Lofi Stu\u{2026}"); assert_eq!(super::trunc("Peaceful Piano", 15), "Peaceful Piano"); }
    #[test] fn am_cfg_like_1_1() {
        let p = "spotify:playlist:37i9dQZF1DX4sWSpwq3LiO";
        assert_eq!(super::am_cfg(&json!({ "after_match": { "mode": "playlist", "playlist": p } })).2, p);
        assert_eq!(super::am_cfg(&json!({ "after_match": { "mode": "winloss" } })).0, "stop");
        assert!(super::am_cfg(&json!({ "after_match": { "mode": "winloss" } })).1);
        assert_eq!(super::am_cfg(&json!({})).0, "resume");
        assert_eq!(super::am_cfg(&json!({ "after_match": { "playlist": "spotify:playlist:bad" } })).2, "");
    }
    #[test] fn pill_like_1_1() {
        assert_eq!(super::pill(&json!({ "phase": "avail", "info": { "version": "1.2.0" } }), None, false), ("\u{2193} Update 1.2.0".into(), false, true, true));
        assert_eq!(super::pill(&json!({ "phase": "dl", "pct": 40, "info": {} }), None, false).0, "Downloading 40%");
        assert_eq!(super::pill(&json!({ "phase": "done", "msg": "Updated to 1.1.0" }), None, true).0, "");
        assert_eq!(super::pill(&json!({ "phase": "idle" }), Some(("Checking\u{2026}", false)), false).0, "Checking\u{2026}");
    }
    #[test] fn fire_row() {
        let s = json!({ "ages": [["dark", "Dark Age"], ["feudal", "Feudal Age"]], "status": { "in_match": true, "playing": "x", "age": "feudal" } });
        assert_eq!(super::playing_row(&s), 1);
        assert_eq!(super::playing_row(&json!({ "ages": [], "status": { "in_match": false } })), -1);
    }
}
