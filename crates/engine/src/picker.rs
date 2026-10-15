//! Picker / Add a song data: Spotify library + search, app-only lists, picks (Tauri 1.1 picker.rs without windows).
use crate::{Engine, wall, data::{read_user, read_json, set_user_, LIST_PREFIX}};
use std::sync::atomic::Ordering;
use std::sync::Arc;

/// Covers changed on disk (views drop their cover cache when this ticks).
pub static COVERS_VER: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
pub fn covers_changed() { COVERS_VER.fetch_add(1, Ordering::SeqCst); }

/// Age page: click a chip = play that song now, None = pause. "login" when not logged in.
pub fn preview(a: &Engine, uri: Option<String>) -> Result<String, String> {
    let mut sp = a.spotify.lock().unwrap();
    if !sp.logged_in() { return Ok("login".to_string()); }
    match uri { Some(u) => sp.preview(&u), None => sp.pause() }.map(|_| "ok".to_string())
}
/// Add a song (M3): one Spotify track -> {uri,name,artist,img}.
pub fn norm(t: &serde_json::Value) -> Option<serde_json::Value> {
    let u = t["uri"].as_str()?; if !u.starts_with("spotify:track:") { return None; }
    let imgs = t["album"]["images"].as_array().cloned().unwrap_or_default();
    let img = imgs.iter().min_by_key(|i| (i["width"].as_i64().unwrap_or(640) - 64).abs()).and_then(|i| i["url"].as_str()).unwrap_or("");
    let ar = t["artists"].as_array().map(|a| a.iter().take(2).filter_map(|x| x["name"].as_str()).collect::<Vec<_>>().join(", ")).unwrap_or_default();
    Some(serde_json::json!({ "uri": u, "name": t["name"].as_str().unwrap_or("Song"), "artist": ar, "img": img, "ms": t["duration_ms"].as_i64().unwrap_or(0) }))
}
pub fn fake_sp(kind: &str, arg: &str) -> serde_json::Value {
    let tr = |k: usize, n: &str| serde_json::json!({ "uri": format!("spotify:track:{}", k.to_string().repeat(22)), "name": n, "artist": "Yasunori Nishiki", "img": "" });
    match kind {
        "playlists" => serde_json::json!([{ "id": "liked", "name": "Liked Songs", "n": 212 }, { "id": "p1", "name": "Octopath favourites", "n": 38 }, { "id": "p2", "name": "Game OSTs", "n": 64 }]),
        "plist" => serde_json::json!([tr(5, "Main Theme"), tr(6, "Battle at the Gate"), tr(7, "Cyrus, the Scholar"), tr(8, "Decisive Battle II"), tr(9, "Ophilia's Theme"), tr(3, &format!("From {arg}"))]),
        "tracks" => serde_json::Value::Array(arg.split(',').map(|i| serde_json::json!({ "uri": format!("spotify:track:{i}"), "name": format!("Dropped {}", &i[..4.min(i.len())]), "artist": "Test", "img": "" })).collect()),
        "playing" => serde_json::json!([tr(4, "Now Playing Song")]),
        _ => serde_json::json!([tr(1, &format!("{arg} 1")), tr(2, &format!("{arg} 2"))]),
    }
}
/// Spotify data for the picker (blocking: call off the UI thread). kind: search | playlists | plist | tracks | plmeta | playing.
pub fn sp(a: &Engine, kind: &str, arg: &str) -> Result<serde_json::Value, String> {
    use serde_json::{json, Value};
    if std::env::var_os("AOE4S_FAKESP").is_some() { return Ok(fake_sp(kind, arg)); }
    {
        let s = { let mut s = a.spotify.lock().unwrap(); if !s.logged_in() { return Ok(json!("login")); } s.web()? };   // lock released before any request
        let ok = |r: Result<(u16, Value), String>| -> Result<Value, String> { let (c, v) = r?; if (200..300).contains(&c) { Ok(v) } else { Err(format!("Spotify error {c}: {}", v["error"]["message"].as_str().unwrap_or(""))) } };
        let list = |v: &Value| -> Value { Value::Array(v.as_array().cloned().unwrap_or_default().iter().filter_map(|i| norm(if i["track"].is_object() { &i["track"] } else if i["item"].is_object() { &i["item"] } else { i })).collect()) };
        match kind {
            "search" => { let v = ok(s.get(&format!("/search?type=track&limit=10&q={}", aoe4core::spotify::enc(arg))))?; Ok(list(&v["tracks"]["items"])) }
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
    }
}
/// New songs' covers go to 1.1's own cache (the 1.0.9 cache is only read).
pub fn cache_covers(a: Arc<Engine>, items: Vec<serde_json::Value>) {
    std::thread::spawn(move || { let dir = a.dir.join("covers"); let _ = std::fs::create_dir_all(&dir);
        for it in items { let (Some(u), Some(img)) = (it["uri"].as_str(), it["img"].as_str()) else { continue };
            let id: String = u.rsplit(':').next().unwrap_or("").chars().filter(|c| c.is_ascii_alphanumeric()).collect(); let p = dir.join(format!("track_{id}.jpg"));
            if img.starts_with("https://") && !p.exists() { let b = aoe4core::spotify::fetch(img); if let Ok(b) = b { let _ = std::fs::write(&p, b); covers_changed(); } } } });
}
/// 1.0.9 list builder save: app-only list (custom_lists in your settings, max 100 songs) + its 2x2 mosaic cover.
pub fn save_list(app: &Arc<Engine>, id: String, name: String, tracks: serde_json::Value, mosaic: &[u8]) -> String {
    let id: String = if id.chars().all(|c| c.is_ascii_alphanumeric()) && !id.is_empty() && id != "liked" { id } else { format!("{:08x}", (wall() * 1000.0) as u64 as u32) };
    let tr: Vec<serde_json::Value> = tracks.as_array().cloned().unwrap_or_default().into_iter().filter(|t| t["uri"].as_str().map_or(false, |u| u.starts_with("spotify:track:"))).take(100)
        .map(|t| serde_json::json!({ "uri": t["uri"], "name": t["name"], "artist": t["artist"], "ms": t["ms"] })).collect();
    if tr.is_empty() { return String::new(); }
    let name: String = { let n: String = name.trim().chars().take(40).collect(); if n.is_empty() { "My list".into() } else { n } };
    let mut cl = read_user(&app.dir)["custom_lists"].clone(); if !cl.is_object() { cl = serde_json::json!({}); }
    cl[&id] = serde_json::json!({ "name": name, "tracks": tr }); set_user_(app, "custom_lists", cl);
    if !mosaic.is_empty() { let d = app.dir.join("covers"); let _ = std::fs::create_dir_all(&d); let _ = std::fs::write(d.join(format!("list_{id}.png")), mosaic); covers_changed(); }
    format!("{LIST_PREFIX}{id}")
}
/// Delete list (pressed twice): ages and After match picks that used it go back to their defaults / empty.
pub fn delete_list(app: &Arc<Engine>, id: String) {
    let u = read_user(&app.dir); let uri = format!("{LIST_PREFIX}{id}");
    let mut cl = u["custom_lists"].clone(); if let Some(o) = cl.as_object_mut() { o.remove(&id); } set_user_(app, "custom_lists", cl);
    let mut pl = u["playlists"].clone(); if let Some(o) = pl.as_object_mut() { o.retain(|_, v| v.as_str() != Some(uri.as_str())); set_user_(app, "playlists", pl); }
    let mut am = u["after_match"].clone(); if am.is_object() { for k in ["playlist", "win", "loss"] { if am[k].as_str() == Some(uri.as_str()) { am[k] = serde_json::json!(""); } } set_user_(app, "after_match", am); }
    let _ = std::fs::remove_file(app.dir.join("covers").join(format!("list_{id}.png"))); covers_changed();
    crate::sys::log(&format!("Deleted app list {id}"));
}
pub fn pick_info(app: &Arc<Engine>) -> serde_json::Value { let mut v = app.pick.lock().unwrap().clone(); v["custom_lists"] = read_user(&app.dir)["custom_lists"].clone(); v }
/// The picker chose `uri` for the current target (age:<k> | am:playlist | am:win | am:loss).
pub fn pick_done(app: &Arc<Engine>, uri: String, name: String, img: String) {
    let p = app.pick.lock().unwrap().clone(); let t = p["target"].as_str().unwrap_or("").to_string();
    let ok = uri.starts_with("spotify:playlist:") || uri.starts_with(LIST_PREFIX) || (p["tracks"] == true && uri.starts_with("spotify:track:"));
    if !ok { return; }
    let id = uri.rsplit(':').next().unwrap_or("").to_string();
    if !name.is_empty() && !uri.starts_with(LIST_PREFIX) {           // name + cover for the panel rows (1.0.9 playlist_names.json / covers)
        let np = app.dir.join("playlist_names.json"); let mut n = read_json(&np); n[&id] = serde_json::json!(name);
        let _ = std::fs::write(&np, serde_json::to_string_pretty(&n).unwrap_or_default()); app.settings.lock().unwrap().playlist_names.insert(id.clone(), name); app.ver.fetch_add(1, Ordering::SeqCst);
        if img.starts_with("https://") { let a = app.clone(); let tr = uri.starts_with("spotify:track:"); std::thread::spawn(move || {
            let dir = a.dir.join("covers"); let _ = std::fs::create_dir_all(&dir); let f = dir.join(if tr { format!("track_{id}.jpg") } else { format!("{id}_pick.jpg") });
            if let Ok(b) = aoe4core::spotify::fetch(&img) { let _ = std::fs::write(f, b); covers_changed(); } }); }
    }
    let u = read_user(&app.dir);
    if let Some(k) = t.strip_prefix("age:") { let mut pl = u["playlists"].clone(); if !pl.is_object() { pl = serde_json::json!({}); } pl[k] = serde_json::json!(uri); set_user_(app, "playlists", pl); }
    else if let Some(w) = t.strip_prefix("am:") { let mut a = u["after_match"].clone(); if !a.is_object() { a = serde_json::json!({}); } a[w] = serde_json::json!(uri);
        if w == "playlist" { a["mode"] = serde_json::json!("playlist"); } else { a["winloss_on"] = serde_json::json!(true); if a["mode"] == "winloss" { a["mode"] = serde_json::json!("stop"); } }
        set_user_(app, "after_match", a); }
}

/// Open the picker for a target (the view then reads `pick_info`).
pub fn open_pick(app: &Engine, target: &str, title: &str, tracks: bool, current: &str) {
    *app.pick.lock().unwrap() = serde_json::json!({ "target": target, "title": title, "tracks": tracks, "current": current });
}
