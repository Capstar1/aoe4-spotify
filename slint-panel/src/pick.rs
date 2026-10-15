//! Playlist picker window (Tauri 1.1 ui/pick.js, 1.0.9 list_picker): Your playlists grid with search, Paste link (paste / drop),
//! your app lists, Use. Opened for an age row, the After match playlist, or Victory / Defeat (songs too). Builder: off, as in 1.1.
use crate::{netimg, paths, view, PickWin, SavedList, Tile};
use aoe4engine::{picker, Engine};
use serde_json::{json, Value};
use slint::{ComponentHandle, Image, ModelRc, Timer, TimerMode, VecModel};
use std::{cell::RefCell, sync::Arc, time::Duration};

const LIKED: &str = "aoe4s:list:liked";
struct Pick { w: PickWin, eng: Arc<Engine>, info: Value, items: Vec<Value>, sel: Option<String>, err: String, drag: bool, tick: Timer, ver: u64, busy: bool }
thread_local! { static PICK: RefCell<Option<Pick>> = const { RefCell::new(None) }; }
fn with<R>(f: impl FnOnce(&mut Pick) -> R) -> Option<R> { PICK.with(|a| a.borrow_mut().as_mut().map(f)) }

/// A Spotify playlist link (or a song link when the target takes songs) -> uri.
pub fn parse_link(t: &str, tracks: bool) -> Option<String> {
    let find = |kind: &str| -> Option<String> {
        for pat in [format!("open.spotify.com/{kind}/"), format!("spotify:{kind}:")] { if let Some(i) = t.find(&pat) { let id: String = t[i + pat.len()..].chars().take_while(|c| c.is_ascii_alphanumeric()).collect(); if id.len() == 22 { return Some(format!("spotify:{kind}:{id}")); } } }
        let mut s = t; while let Some(i) = s.find("open.spotify.com/intl-") { let r = &s[i..]; if let Some(j) = r.find(&format!("/{kind}/")) { let id: String = r[j + kind.len() + 2..].chars().take_while(|c| c.is_ascii_alphanumeric()).collect(); if id.len() == 22 { return Some(format!("spotify:{kind}:{id}")); } } s = &s[i + 22..]; }
        None
    };
    find("playlist").or_else(|| if tracks { find("track") } else { None })
}

pub fn open(eng: &Arc<Engine>) {
    close();   // like 1.1 small_window: one picker, re-read for its new target
    let Ok(w) = PickWin::new() else { return };
    w.set_drop_path(paths::dashed_rect(364.0, 46.0, 10.0, 1.4, 5.0, 4.0).into());
    w.on_close(close); w.window().on_close_requested(|| { close(); slint::CloseRequestResponse::HideWindow });
    w.on_select(|i| { with(|p| { let f = shown(p); if let Some(it) = f.get(i as usize) { p.sel = it["uri"].as_str().map(String::from); p.err.clear(); } }); draw(); });
    w.on_use_it(use_sel);
    w.on_ok(ok_link);
    w.on_pasted(|t| { let tracks = with(|p| p.info["tracks"] == json!(true)).unwrap_or(false); if t.len() > 30 { if let Some(u) = parse_link(t.trim(), tracks) { finish(u, String::new(), String::new()); } } });
    w.on_retry(load);
    w.on_filtered(draw);
    w.on_pick_saved(|i| { let l = with(|p| saved(p)).unwrap_or_default(); if let Some((k, v)) = l.get(i as usize) { finish(format!("aoe4s:list:{k}"), v["name"].as_str().unwrap_or("My list").into(), String::new()); } });
    let tick = Timer::default();
    tick.start(TimerMode::Repeated, Duration::from_millis(250), || { let v = netimg::VER.load(std::sync::atomic::Ordering::SeqCst); if with(|p| { let c = p.ver != v; p.ver = v; c }).unwrap_or(false) { draw(); } });
    let info = picker::pick_info(eng);
    PICK.with(|a| *a.borrow_mut() = Some(Pick { w: w.clone_strong(), eng: eng.clone(), info, items: vec![], sel: None, err: String::new(), drag: false, tick, ver: 0, busy: false }));
    draw(); let _ = w.show();
    crate::dnd::register(w.window(), crate::dnd::Target::Pick);
    load();
}
pub fn close() { PICK.with(|a| if let Some(x) = a.borrow_mut().take() { x.tick.stop(); let _ = x.w.hide(); }); }

fn shown(p: &Pick) -> Vec<Value> { let f = p.w.get_filter().trim().to_lowercase(); p.items.iter().filter(|it| f.is_empty() || it["name"].as_str().unwrap_or("").to_lowercase().contains(&f)).cloned().collect() }
/// Your app lists (1.0.9 'Your lists': the last 4, not the current one).
fn saved(p: &Pick) -> Vec<(String, Value)> {
    let cur = p.info["current"].as_str().unwrap_or("");
    let l: Vec<(String, Value)> = p.info["custom_lists"].as_object().map(|o| o.iter().filter(|(k, v)| v.is_object() && format!("aoe4s:list:{k}") != cur && *k != "liked").map(|(k, v)| (k.clone(), v.clone())).collect()).unwrap_or_default();
    let n = l.len(); l.into_iter().skip(n.saturating_sub(4)).collect()
}
fn load() {
    let Some(eng) = with(|p| { p.w.set_state(if p.items.is_empty() { "load".into() } else { "ok".into() }); p.eng.clone() }) else { return };
    std::thread::spawn(move || { let r = picker::sp(&eng, "playlists", "");
        let _ = slint::invoke_from_event_loop(move || { with(|p| {
            match r {
                Ok(v) if v == "login" => p.w.set_state("login".into()),
                Ok(v) => { p.items = v.as_array().cloned().unwrap_or_default().iter().map(|x| { let liked = x["id"] == json!("liked");
                        json!({ "uri": if liked { LIKED.to_string() } else { format!("spotify:playlist:{}", x["id"].as_str().unwrap_or("")) }, "name": x["name"].as_str().unwrap_or("Playlist"), "n": x["n"].as_i64().unwrap_or(0), "img": x["img"].as_str().unwrap_or(""), "liked": liked }) }).collect();
                    p.w.set_state("ok".into());
                    let cur = p.info["current"].as_str().unwrap_or("").to_string(); if p.sel.is_none() && p.items.iter().any(|x| x["uri"] == json!(cur)) { p.sel = Some(cur); } }
                Err(_) => p.w.set_state("off".into()),
            } }); draw(); }); });
}
pub fn draw() {
    with(|p| {
        let w = &p.w; let tracks = p.info["tracks"] == json!(true); let s = w.window().scale_factor();
        w.set_head(p.info["title"].as_str().unwrap_or("Playlist").into());
        let f = shown(p); let px = (79.5 * s).round() as u32;
        let tiles: Vec<Tile> = f.iter().map(|it| { let img = netimg::get(it["img"].as_str().unwrap_or(""), px, (8.0 * s) as u32); let n = it["n"].as_i64().unwrap_or(0);
            Tile { name: it["name"].as_str().unwrap_or("").into(), count: format!("{n} song{}", if n == 1 { "" } else { "s" }).into(), has_img: img.is_some(), img: img.unwrap_or_else(Image::default),
                liked: it["liked"] == json!(true), sel: it["uri"].as_str() == p.sel.as_deref() } }).collect();
        let rows = (tiles.len() as f32 / 4.0).ceil(); let mx = (rows * 121.5 + 4.0 - 6.0 - 241.0).max(0.0);
        w.set_max_sc(mx); if w.get_sc() > mx { w.set_sc(mx); }
        w.set_tiles(ModelRc::new(VecModel::from(tiles)));
        let (hint, col) = if !p.err.is_empty() { (p.err.clone(), slint::Color::from_rgb_u8(0xe5, 0x67, 0x5f)) } else if p.drag { ("Drop here".into(), slint::Color::from_rgb_u8(0x1d, 0xb9, 0x54)) }
            else { (format!("Paste a link or drag a {} from Spotify", if tracks { "playlist or song" } else { "playlist" }), slint::Color::from_rgb_u8(0x9a, 0x9a, 0x9a)) };
        w.set_hint(hint.into()); w.set_hint_col(col); w.set_drag(p.drag);
        let dir = p.eng.dir.clone();
        let sv: Vec<SavedList> = saved(p).iter().map(|(k, v)| { let (img, has) = view::cover(&dir, &format!("aoe4s:list:{k}")); let n = v["tracks"].as_array().map_or(0, |t| t.len());
            SavedList { name: view::trunc(v["name"].as_str().unwrap_or("My list"), 28).into(), count: format!("{n} songs").into(), img, has_img: has } }).collect();
        w.set_saved(ModelRc::new(VecModel::from(sv)));
        let sel = p.items.iter().find(|x| x["uri"].as_str() == p.sel.as_deref());
        w.set_use_on(sel.is_some());
        w.set_use_text(match sel { Some(s) => format!("Use {}", view::trunc(s["name"].as_str().unwrap_or(""), 34)).into(), None if !p.err.is_empty() => p.err.clone().into(), None => "Pick a playlist".into() });
    });
}
fn use_sel() { let it = with(|p| p.items.iter().find(|x| x["uri"].as_str() == p.sel.as_deref()).cloned()).flatten(); if let Some(it) = it {
    finish(it["uri"].as_str().unwrap_or("").into(), it["name"].as_str().unwrap_or("").into(), it["img"].as_str().unwrap_or("").into()); } }
fn ok_link() {
    let Some((v, tracks)) = with(|p| (p.w.get_link().trim().to_string(), p.info["tracks"] == json!(true))) else { return };
    if v.is_empty() { with(|p| p.err = "Paste a link first".into()); return draw(); }
    match parse_link(&v, tracks) { Some(u) => finish(u, String::new(), String::new()), None => { with(|p| p.err = format!("Not a Spotify {} link", if tracks { "playlist or song" } else { "playlist" })); draw(); } }
}
/// Apply the choice (pasted links: look up name + cover first, for the panel row) and close.
fn finish(uri: String, name: String, img: String) {
    let Some(eng) = with(|p| { if p.busy { return None; } p.busy = true; Some(p.eng.clone()) }).flatten() else { return };
    std::thread::spawn(move || {
        let (mut name, mut img) = (name, img);
        if name.is_empty() && uri.starts_with("spotify:") {
            let kind = if uri.starts_with("spotify:track:") { "tracks" } else { "plmeta" };
            if let Ok(r) = picker::sp(&eng, kind, uri.rsplit(':').next().unwrap_or("")) { if let Some(it) = r.as_array().and_then(|a| a.first()) { name = it["name"].as_str().unwrap_or("").into(); img = it["img"].as_str().unwrap_or("").into(); } }
        }
        picker::pick_done(&eng, uri, name, img);
        let _ = slint::invoke_from_event_loop(close);
    });
}
/// Drag from Spotify over the window (None = left), drop = released.
pub fn drag(text: Option<String>, drop: bool) {
    let tracks = with(|p| { p.drag = text.is_some() && !drop; p.info["tracks"] == json!(true) }).unwrap_or(false);
    if drop { if let Some(t) = text { match parse_link(&t, tracks) { Some(u) => return finish(u, String::new(), String::new()), None => { with(|p| p.err = format!("Not a Spotify {} link", if tracks { "playlist or song" } else { "playlist" })); } } } }
    draw();
}
/// AOE4S_PICK test render: fake playlists (AOE4S_FAKESP), one selected.
pub fn test() { with(|p| { p.items = picker::fake_sp("playlists", "").as_array().cloned().unwrap_or_default().iter().map(|x| { let liked = x["id"] == json!("liked");
    json!({ "uri": if liked { LIKED.to_string() } else { format!("spotify:playlist:{}", x["id"].as_str().unwrap_or("")) }, "name": x["name"], "n": x["n"], "img": "", "liked": liked }) }).collect();
    p.sel = Some("spotify:playlist:p1".into()); p.w.set_state("ok".into()); }); draw(); }

#[cfg(test)]
mod tests {
    #[test]
    fn links() {
        let id = "37i9dQZF1DX8Uebhn9wzrS"; let tr = "4uLU6hMCjMI75M1A2tKUQC";
        assert_eq!(super::parse_link(&format!("https://open.spotify.com/playlist/{id}?si=1"), false).as_deref(), Some(&*format!("spotify:playlist:{id}")));
        assert_eq!(super::parse_link(&format!("https://open.spotify.com/intl-de/playlist/{id}"), false).as_deref(), Some(&*format!("spotify:playlist:{id}")));
        assert_eq!(super::parse_link(&format!("https://open.spotify.com/track/{tr}"), false), None);
        assert_eq!(super::parse_link(&format!("spotify:track:{tr}"), true).as_deref(), Some(&*format!("spotify:track:{tr}")));
    }
}
/// Test switch: save the window as a PNG.
pub fn snapshot(path: &str) { with(|a| if let Ok(b) = a.w.window().take_snapshot() { let _ = crate::save_png(path, b.as_bytes(), b.width(), b.height()); }); }
