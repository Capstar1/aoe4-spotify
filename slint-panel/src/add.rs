//! "Add a song" window (Tauri 1.1 ui/add.js): search / paste a link / what's playing / your playlists; adds to YOURS via the editor.
use crate::{intros, netimg, paths, AddList, AddRow, AddWin};
use aoe4engine::{picker, Engine};
use serde_json::Value;
use slint::{ComponentHandle, Image, ModelRc, Timer, TimerMode, VecModel};
use std::{cell::RefCell, sync::Arc, time::Duration};

struct Add { w: AddWin, eng: Arc<Engine>, items: Vec<Value>, lists: Option<Vec<Value>>, cur: Option<String>, seq: u64, search: Timer, _tick: Timer, ver: u64 }
thread_local! { static ADD: RefCell<Option<Add>> = const { RefCell::new(None) }; }
fn with<R>(f: impl FnOnce(&mut Add) -> R) -> Option<R> { ADD.with(|a| a.borrow_mut().as_mut().map(f)) }

/// Spotify song / link ids in a text (open.spotify.com/track/..., spotify:track:...).
pub fn track_ids(t: &str) -> Vec<String> {
    let mut out: Vec<String> = vec![];
    for pat in ["open.spotify.com/track/", "spotify:track:"] { let mut s = t;
        while let Some(i) = s.find(pat) { let r = &s[i + pat.len()..]; let id: String = r.chars().take_while(|c| c.is_ascii_alphanumeric()).collect(); if id.len() == 22 && !out.contains(&id) { out.push(id); } s = r; } }
    // open.spotify.com/intl-xx/track/...
    let mut s = t; while let Some(i) = s.find("open.spotify.com/intl-") { let r = &s[i..]; if let Some(j) = r.find("/track/") { let id: String = r[j + 7..].chars().take_while(|c| c.is_ascii_alphanumeric()).collect(); if id.len() == 22 && !out.contains(&id) { out.push(id); } } s = &s[i + 22..]; }
    out
}

pub fn open(eng: &Arc<Engine>) {
    if let Some(w) = with(|a| a.w.clone_strong()) { let _ = w.show(); return; }
    let Ok(w) = AddWin::new() else { return };
    w.set_zone_path(paths::dashed_rect(384.0, 56.0, 10.0, 2.0, 7.0, 5.0).into());
    w.on_dismiss(close); w.window().on_close_requested(|| { close(); slint::CloseRequestResponse::HideWindow });
    w.on_edited(edited); w.on_enter(|| { let q = with(|a| a.w.get_query().to_string()).unwrap_or_default(); if !track_ids(&q).is_empty() { with(|a| a.w.set_query("".into())); intros::drop_text(q); } });
    w.on_playing(|| api("playing", String::new(), |v| { let items = v.as_array().cloned().unwrap_or_default(); if items.is_empty() { say("Nothing is playing on Spotify", true); return; }
        intros::add_songs(items); Timer::single_shot(Duration::from_millis(150), close); }));
    w.on_open_menu(|| { if with(|a| a.lists.is_some()).unwrap_or(false) { show_menu(); return; } say("Loading your playlists\u{2026}", false);
        api("playlists", String::new(), |v| { with(|a| a.lists = Some(v.as_array().cloned().unwrap_or_default())); say("Click a song to add it", false); show_menu(); }); });
    w.on_pick(|i| { let Some(p) = with(|a| a.lists.as_ref().and_then(|l| l.get(i as usize).cloned())).flatten() else { return }; pick(p); });
    let ww = w.as_weak();
    w.on_drag(move |i, k, x, y| { let Some(w) = ww.upgrade() else { return };
        let drop = k == "drop"; let over = crate::panel_point(w.window(), x, y).is_some();
        intros::drag_over(over && !drop);
        if drop && over { if let Some(it) = with(|a| a.items.get(i as usize).cloned()).flatten() { intros::drop_on_page_items(vec![it]); } } });
    w.on_add(|i| { if let Some(it) = with(|a| a.items.get(i as usize).cloned()).flatten() { intros::add_songs(vec![it]); } });
    let tick = Timer::default();
    tick.start(TimerMode::Repeated, Duration::from_millis(250), || { let v = netimg::VER.load(std::sync::atomic::Ordering::SeqCst); if with(|a| { let c = a.ver != v; a.ver = v; c }).unwrap_or(false) { paint(); } });
    ADD.with(|a| *a.borrow_mut() = Some(Add { w: w.clone_strong(), eng: eng.clone(), items: vec![], lists: None, cur: None, seq: 0, search: Timer::default(), _tick: tick, ver: 0 }));
    paint(); let _ = w.show();
    crate::dnd::register(&w, crate::dnd::Target::Add);
}
pub fn close() { ADD.with(|a| if let Some(x) = a.borrow_mut().take() { let _ = x.w.hide(); }); }
/// Bottom line of the window (also used by the editor: "Added ...", "Already added").
pub fn say(m: &str, err: bool) { with(|a| { a.w.set_msg(m.into()); a.w.set_err(err); }); }
/// Drop zone highlight while something is dragged over the window.
pub fn zone(on: bool, n: usize) { with(|a| { a.w.set_zone_on(on); a.w.set_zone_text(if !on { "Drop Spotify songs or links here".into() } else if n > 1 { format!("Release to add {n} songs").into() } else { "Release to add".into() }); }); }
/// Redraw the list (after songs were added: the "✓ Added" marks).
pub fn paint() {
    with(|a| {
        let have = intros::have_uris();
        let px = (40.0 * a.w.window().scale_factor()).round() as u32;
        let rows: Vec<AddRow> = a.items.iter().map(|it| { let img = netimg::get(it["img"].as_str().unwrap_or(""), px, (8.0 * a.w.window().scale_factor()) as u32);
            AddRow { name: it["name"].as_str().unwrap_or("Song").into(), artist: it["artist"].as_str().unwrap_or("").into(), has_img: img.is_some(), img: img.unwrap_or_else(Image::default),
                added: it["uri"].as_str().is_some_and(|u| have.iter().any(|h| h == u)) } }).collect();
        a.w.set_rows(ModelRc::new(VecModel::from(rows)));
    });
}
fn show_menu() { with(|a| { let l: Vec<AddList> = a.lists.clone().unwrap_or_default().iter().map(|p| AddList { name: p["name"].as_str().unwrap_or("Playlist").into(),
    n: p["n"].as_i64().map(|n| n.to_string()).unwrap_or_default().into(), cur: p["id"].as_str() == a.cur.as_deref() }).collect(); a.w.set_lists(ModelRc::new(VecModel::from(l))); a.w.set_menu(true); }); }
/// Spotify call off the UI thread; `ok` runs on the UI thread unless the window moved on (seq) or it failed.
fn api(kind: &'static str, arg: String, ok: impl FnOnce(Value) + Send + 'static) {
    let Some((eng, seq)) = with(|a| { a.seq += 1; (a.eng.clone(), a.seq) }) else { return };
    std::thread::spawn(move || { let r = picker::sp(&eng, kind, &arg);
        let _ = slint::invoke_from_event_loop(move || {
            if kind != "playlists" && kind != "playing" && with(|a| a.seq != seq).unwrap_or(true) { return; }
            match r { Ok(v) if v == "login" => say("Log in to Spotify in AoE4 Spotify first", true), Ok(v) => ok(v), Err(e) => say(&e, true) } }); });
}
fn edited(q: slint::SharedString) {
    let q = q.trim().to_string();
    if !track_ids(&q).is_empty() { say("Press Enter to add the pasted song", false); return; }
    if q.is_empty() { say("Click a song to add it", false); return; }
    with(|a| a.search.start(TimerMode::SingleShot, Duration::from_millis(350), move || { say("Searching\u{2026}", false); let q2 = q.clone();
        api("search", q2, |v| { let n = v.as_array().map_or(0, |x| x.len()); with(|a| { a.items = v.as_array().cloned().unwrap_or_default(); a.cur = None; a.w.set_pl_name("Your playlists".into()); a.w.set_sc(0.0); });
            paint(); say(if n > 0 { "Click a song to add it" } else { "No songs found" }, false); }); }));
}
fn pick(p: Value) {
    let id = p["id"].as_str().unwrap_or("").to_string();
    with(|a| { a.cur = Some(id.clone()); a.w.set_pl_name(p["name"].as_str().unwrap_or("Playlist").into()); }); say("Loading\u{2026}", false);
    api("plist", id, |v| { let n = v.as_array().map_or(0, |x| x.len()); with(|a| { a.items = v.as_array().cloned().unwrap_or_default(); a.w.set_sc(0.0); }); paint();
        say(if n > 0 { "Click a song to add it" } else { "This playlist has no songs" }, false); });
}
/// AOE4S_ADD test renders: "list" fills the fake list, "menu" opens the playlists menu, "zone" lights the drop zone.
pub fn test(kind: &str) {
    match kind {
        "list" | "menu" => { with(|a| { a.items = picker::fake_sp("plist", "p1").as_array().cloned().unwrap_or_default(); a.cur = Some("p1".into()); a.w.set_pl_name("Octopath favourites".into()); }); paint();
            if kind == "menu" { with(|a| a.lists = Some(picker::fake_sp("playlists", "").as_array().cloned().unwrap_or_default())); show_menu(); } }
        "zone" => zone(true, 2),
        _ => {}
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn finds_track_links() {
        let a = "a".repeat(22); let b = "B".repeat(22);
        let t = format!("https://open.spotify.com/track/{a}?si=x\r\nhttps://open.spotify.com/intl-de/track/{b}\nspotify:track:{a} https://open.spotify.com/album/{}", "3".repeat(22));
        assert_eq!(super::track_ids(&t), vec![a, b]);
    }
}
/// Test switch: save the window as a PNG.
pub fn snapshot(path: &str) { with(|a| if let Ok(b) = a.w.window().take_snapshot() { let _ = crate::save_png(path, b.as_bytes(), b.width(), b.height()); }); }
/// BTR self-test access: the open window and its list length.
#[cfg_attr(not(windows), allow(dead_code))]
pub fn win() -> Option<crate::AddWin> { with(|a| a.w.clone_strong()) }
#[cfg_attr(not(windows), allow(dead_code))]
pub fn items_len() -> usize { with(|a| a.items.len()).unwrap_or(0) }
#[cfg_attr(not(windows), allow(dead_code))]
pub fn item_uri(i: usize) -> Option<String> { with(|a| a.items.get(i).and_then(|v| v["uri"].as_str().map(String::from))).flatten() }
