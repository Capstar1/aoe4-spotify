#![windows_subsystem = "windows"]
#![deny(warnings)]
//! AoE4 Spotify, Slint front end. The views are ui/*.slint (pure: data in, callbacks out); all behaviour lives in
//! the aoe4engine crate (the Tauri 1.1 logic without a toolkit). This file only connects the two: it pushes engine
//! state into the views when it changes (checked every 250 ms, like the Tauri notifier) and turns callbacks into
//! engine calls. `fire.rs` animates the 1.0.9 glow-pool fire on the age row that is playing.
//! Test switches: AOE4S_SHOT=<png> (render once and quit), AOE4S_NOWATCH (no game-log watcher), `--fire <row>`.
mod fire;
mod gtg;
mod startup;
mod view;
mod assets;
mod intros;
mod add;
mod pick;
mod dnd;
mod netimg;
mod paths;
use aoe4engine::{guides::{Shell, Win}, menu, updater, Engine};
use slint::{ComponentHandle, Image, Rgba8Pixel, SharedPixelBuffer};
use std::cell::RefCell;
use std::rc::Rc;
use std::sync::Arc;
use std::time::{Duration, Instant};

slint::include_modules!();

fn img(rgba: &[u8], w: usize, h: usize) -> Image { Image::from_rgba8(SharedPixelBuffer::<Rgba8Pixel>::clone_from_slice(rgba, w as u32, h as u32)) }

/// Windows the engine asks for (good to go, guides, picker...): handed to the UI thread.
struct UiShell;
impl Shell for UiShell {
    fn show(&self, w: Win) { let _ = slint::invoke_from_event_loop(move || windows::show(w)); }
    fn close(&self, w: Win) { let _ = slint::invoke_from_event_loop(move || windows::close(w)); }
}
thread_local! { static CTX: RefCell<Option<(Arc<Engine>, Arc<dyn Shell>)>> = const { RefCell::new(None) }; }
thread_local! { static PANEL: RefCell<Option<slint::Weak<Panel>>> = const { RefCell::new(None) }; static PANEL_SHOWN: std::cell::Cell<bool> = const { std::cell::Cell::new(false) }; }
mod windows {
    use super::{CTX, PANEL, PANEL_SHOWN};
    use aoe4engine::guides::Win;
    use slint::ComponentHandle;
    #[cfg_attr(not(windows), allow(dead_code))]
    pub fn panel_visible() -> bool { PANEL_SHOWN.with(|v| v.get()) }
    /// Show a window. Not yet ported windows fall back to the panel (never leave an invisible process).
    pub fn show(w: Win) {
        if let Some((e, s)) = CTX.with(|c| c.borrow().clone()) {
            match w { Win::Gtg => return crate::gtg::open(&e, &s), Win::Add => return crate::add::open(&e), Win::Pick => return crate::pick::open(&e), _ => {} }
        }
        if w != Win::Panel { aoe4engine::sys::log(&format!("window {w:?} requested (not ported yet: showing the panel)")); }
        PANEL.with(|p| if let Some(u) = p.borrow().as_ref().and_then(|w| w.upgrade()) { let _ = u.show(); PANEL_SHOWN.with(|v| v.set(true)); crate::first_show(&u); })
    }
    pub fn close(w: Win) { match w { Win::Gtg => crate::gtg::close(), Win::Add => crate::add::close(), Win::Pick => crate::pick::close(), _ => {} } }
}

/// Transient pill message (Checking..., Up to date) and when the "Updated to" pill appeared.
#[derive(Default)]
struct PillMsg { msg: Option<(String, bool, Option<Instant>)>, done_t0: Option<Instant> }

fn main() -> Result<(), slint::PlatformError> {
    slint::BackendSelector::new().backend_name("winit".into()).renderer_name("software".into())
        .with_winit_window_attributes_hook(|a| {
            let a = a.with_theme(Some(slint::winit_030::winit::window::Theme::Dark));   // dark native title bars (good to go, picker, Add a song)
            #[cfg(windows)] { use slint::winit_030::winit::platform::windows::WindowAttributesExtWindows; a.with_undecorated_shadow(true) }
            #[cfg(not(windows))] { a }
        })
        .select()?;
    let dir = aoe4core::userstore::data_dir();
    let test = std::env::var_os("AOE4S_SHOT").is_some();
    let Some(st) = (if test { Some(startup::Start { hidden: false, login_first: false }) } else { startup::startup(&dir) }) else { return Ok(()) };
    let (eng, rx, log_path) = Engine::new(dir.clone());
    if std::env::var_os("AOE4S_NOWATCH").is_none() && !test { eng.start(rx, log_path); }
    let shell: Arc<dyn Shell> = Arc::new(UiShell);
    CTX.with(|c| *c.borrow_mut() = Some((eng.clone(), shell.clone())));
    if let Ok(k) = std::env::var("AOE4S_GTG") { return gtg_shot(&k); }
    if let Ok(k) = std::env::var("AOE4S_ADD") { add::open(&eng); add::test(&k); return sub_shot(); }
    if std::env::var_os("AOE4S_PICK").is_some() { aoe4engine::picker::open_pick(&eng, "age:castle", "Castle Age playlist", false, "spotify:playlist:p1"); pick::open(&eng); pick::test(); return sub_shot(); }
    let ui = Panel::new()?;
    PANEL.with(|p| *p.borrow_mut() = Some(ui.as_weak()));
    let pillm = Rc::new(RefCell::new(PillMsg::default()));
    let forced_fire: Option<i32> = { let a: Vec<String> = std::env::args().collect(); a.iter().position(|x| x == "--fire").map(|i| a.get(i + 1).and_then(|s| s.parse().ok()).unwrap_or(1)) };

    // ---- fire: 366 x 42 row (1.1 X-6 .. XR+6); glow drawn once, frames every 34 ms while a row plays
    let scale = ui.window().scale_factor();
    let (rw, rh) = ((366.0 * scale).round() as usize, (42.0 * scale).round() as usize);
    let (g, gw, gh) = fire::glow(rw, rh, 9.0 * scale, scale); ui.set_glow(img(&g, gw, gh));
    let fire = Rc::new(RefCell::new(fire::Fire::new(rw, rh, scale)));
    let fire_timer = Rc::new(slint::Timer::default());
    let set_fire = { let (w, f, t) = (ui.as_weak(), fire.clone(), fire_timer.clone()); move |row: i32| {
        let Some(u) = w.upgrade() else { return }; if u.get_playing() == row && (row < 0 || t.running()) { return; }
        u.set_playing(row);
        if row < 0 { t.stop(); return; }
        let (w2, f2) = (w.clone(), f.clone());
        t.start(slint::TimerMode::Repeated, Duration::from_millis(34), move || {
            let Some(u) = w2.upgrade() else { return }; let mut f = f2.borrow_mut(); let px = f.tick(); u.set_fire(img(&px, f.gw, f.gh)); });
    } };

    // ---- state -> view (250 ms change check, like the Tauri notifier; transient pill expiry)
    let refresh = { let (w, e, d, pm, sf) = (ui.as_weak(), eng.clone(), dir.clone(), pillm.clone(), set_fire.clone()); move |force: bool, last: &mut String| {
        let Some(u) = w.upgrade() else { return };
        let fp = format!("{}|{}", e.fingerprint(), aoe4engine::picker::COVERS_VER.load(std::sync::atomic::Ordering::SeqCst));
        let mut pm = pm.borrow_mut();
        if let Some((_, _, Some(t))) = &pm.msg { if t.elapsed() > Duration::from_secs(2) { pm.msg = None; } }
        let s = e.state(None);
        if force || fp != *last { *last = fp; view::fill(&u, &s, &d); intros::tick(true); sf(forced_fire.unwrap_or_else(|| view::playing_row(&s))); }
        if s["upd"]["phase"] == "done" && pm.done_t0.is_none() { pm.done_t0 = Some(Instant::now()); }
        let gone = pm.done_t0.is_some_and(|t| t.elapsed() > Duration::from_secs(6));
        let (t, err, click, badge) = view::pill(&s["upd"], pm.msg.as_ref().map(|(m, e, _)| (m.as_str(), *e)), gone);
        u.set_pill_text(t.into()); u.set_pill_err(err); u.set_pill_click(click); u.set_badge(badge);
    } };
    let last = Rc::new(RefCell::new(String::new()));
    refresh(true, &mut last.borrow_mut());
    let poll = slint::Timer::default();
    { let (r, l) = (refresh.clone(), last.clone()); poll.start(slint::TimerMode::Repeated, Duration::from_millis(250), move || r(false, &mut l.borrow_mut())); }
    let now = { let (r, l) = (refresh.clone(), last.clone()); move || r(true, &mut l.borrow_mut()) };

    // ---- actions (same files, keys and rules as the Tauri 1.1 commands)
    let w = ui.as_weak();
    let save = { let (e, n) = (eng.clone(), now.clone()); move |k: &str, v: serde_json::Value| { aoe4engine::data::set_user(&e, k, v); n(); } };
    let state = { let e = eng.clone(); move || e.state(None) };
    ui.on_toggle_enabled({ let (e, n, w) = (eng.clone(), now.clone(), w.clone()); move || { let Some(u) = w.upgrade() else { return }; aoe4engine::data::set_enabled(&e, !u.get_enabled()); n(); } });
    ui.on_toggle_boss({ let (s, w) = (save.clone(), w.clone()); move || { if let Some(u) = w.upgrade() { s("boss_intro_enabled", serde_json::json!(!u.get_boss_on())); } } });
    ui.on_set_fade({ let s = save.clone(); move |v| s("fade_seconds", serde_json::json!(((v * 2.0).round() / 2.0) as f64)) });
    ui.on_revert_fade({ let s = save.clone(); move || s("fade_seconds", serde_json::Value::Null) });
    ui.on_revert_playlist({ let (s, st) = (save.clone(), state.clone()); move |i| {   // 1.1: your playlists without this age and without defaults
        let x = st(); let set = &x["settings"]; let Some(k) = x["ages"][i as usize][0].as_str().map(String::from) else { return };
        let up: serde_json::Map<String, serde_json::Value> = set["playlists"].as_object().cloned().unwrap_or_default().into_iter()
            .filter(|(a, v)| *a != k && v.as_str().unwrap_or("") != set["default_playlists"][a].as_str().unwrap_or("")).collect();
        s("playlists", serde_json::Value::Object(up)); } });
    let am_set = { let (s, st) = (save.clone(), state.clone()); move |f: &dyn Fn(&mut serde_json::Value)| {
        let x = st(); let mut a = if x["settings"]["after_match"].is_object() { x["settings"]["after_match"].clone() } else { serde_json::json!({}) }; f(&mut a); s("after_match", a); } };
    ui.on_toggle_wl({ let (a, w) = (am_set.clone(), w.clone()); move || { let Some(u) = w.upgrade() else { return }; let wl = u.get_am_wl();
        a(&|x| { x["winloss_on"] = serde_json::json!(!wl); if x["mode"] == "winloss" { x["mode"] = serde_json::json!("stop"); } }); } });
    let pick = { let (e, sh) = (eng.clone(), shell.clone()); move |target: &str, title: &str, tracks: bool, current: &str| { aoe4engine::picker::open_pick(&e, target, title, tracks, current); sh.show(Win::Pick); } };
    ui.on_set_mode({ let (a, st, p) = (am_set.clone(), state.clone(), pick.clone()); move |m| { let m = m.to_string(); a(&|x| x["mode"] = serde_json::json!(m.as_str()));
        if m == "playlist" && view::am_cfg(&st()["settings"]).2.is_empty() { p("am:playlist", "After match playlist", false, ""); } } });
    ui.on_pick({ let (st, p) = (state.clone(), pick.clone()); move |which| { let (_, _, pl, win, loss) = view::am_cfg(&st()["settings"]);
        match which.as_str() { "win" => p("am:win", "Victory", true, &win), "loss" => p("am:loss", "Defeat", true, &loss), _ => p("am:playlist", "After match playlist", false, &pl) } } });
    ui.on_change_playlist({ let (st, p) = (state.clone(), pick.clone()); move |i| { let x = st(); let (Some(k), Some(lab)) = (x["ages"][i as usize][0].as_str(), x["ages"][i as usize][1].as_str()) else { return };
        p(&format!("age:{k}"), lab, false, x["settings"]["playlists"][k].as_str().unwrap_or("")); } });
    ui.on_open_in_spotify({ let (e, st) = (eng.clone(), state.clone()); move |i| { let x = st(); let k = x["ages"][i as usize][0].as_str().unwrap_or("").to_string();
        let uri = x["settings"]["playlists"][&k].as_str().unwrap_or(""); if !uri.starts_with("aoe4s:list:") { menu::menu(&e, &format!("pl:{}", uri.rsplit(':').next().unwrap_or(""))); } } });
    ui.on_login({ let (e, sh) = (eng.clone(), shell.clone()); move || aoe4engine::guides::do_login(sh.clone(), e.clone()) });
    ui.on_pill_clicked({ let (e, n) = (eng.clone(), now.clone()); move || { updater::start_update(e.clone()); n(); } });
    ui.on_menu_action({ let (e, sh, pm, n) = (eng.clone(), shell.clone(), pillm.clone(), now.clone()); move |k| match k.as_str() {
        "check" => { let ph = e.upd.lock().unwrap()["phase"].as_str().unwrap_or("").to_string(); if ph == "dl" || ph == "run" { return; }
            pm.borrow_mut().msg = Some(("Checking\u{2026}".into(), false, None)); n();
            let e2 = e.clone();
            std::thread::spawn(move || { let r = updater::check_update(&e2); let _ = slint::invoke_from_event_loop(move || PILL_RESULT.with(|p| *p.borrow_mut() = Some(r))); }); }
        "own" => sh.show(Win::Own),
        other => { menu::menu(&e, other); n(); }
    } });
    intros::init(&ui, eng.clone(), shell.clone());
    ui.on_open_intros(|| intros::set_page("intros"));
    // close: a game-launched switcher keeps running hidden (its window just hides); a panel quits
    ui.on_close_app({ let w = w.clone(); let hidden = st.hidden; move || { if let Some(u) = w.upgrade() { let _ = u.hide(); } PANEL_SHOWN.with(|v| v.set(false)); if !hidden { let _ = slint::quit_event_loop(); } } });
    ui.on_minimize({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { use slint::winit_030::WinitWindowAccessor; u.window().with_winit_window(|ww| ww.set_minimized(true)); } } });
    ui.on_drag({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { use slint::winit_030::WinitWindowAccessor; u.window().with_winit_window(|ww| { let _ = ww.drag_window(); }); } } });
    ui.on_gear(|| {});
    // "Check for updates" result -> pill (2 s), or the update pill itself when one was found
    let pr = slint::Timer::default();
    { let (pm, n) = (pillm.clone(), now.clone()); pr.start(slint::TimerMode::Repeated, Duration::from_millis(100), move || {
        if let Some(r) = PILL_RESULT.with(|p| p.borrow_mut().take()) {
            pm.borrow_mut().msg = if r.starts_with('\u{2193}') { None } else { let err = r.starts_with("Couldn"); Some((r, err, Some(Instant::now()))) }; n(); } }); }

    if let Ok(p) = std::env::var("AOE4S_SHOT") { shot(&ui, p); }
    // ---- start-up (Tauri 1.1 setup): hidden switcher follows the game and auto-updates between matches;
    // a panel checks for an update; started without arguments: log in first, then good to go
    if st.hidden {
        let e = eng.clone(); std::thread::spawn(move || updater::auto_update(e));
        #[cfg(windows)] {
            std::thread::spawn(|| aoe4winsys::signal::serve(|| { let _ = slint::invoke_from_event_loop(|| windows::show(Win::Panel)); }));
            let e = eng.clone(); std::thread::spawn(move || aoe4winsys::launcher::follow_game(move || {
                updater::install_pending(&e); let _ = slint::invoke_from_event_loop(|| { if !windows::panel_visible() { let _ = slint::quit_event_loop(); } }); }));
        }
    } else if !test { updater::check_at_start(eng.clone()); }
    if st.login_first && !test {
        let (e, sh) = (eng.clone(), shell.clone());
        if e.spotify.lock().unwrap().logged_in() { std::thread::spawn(move || aoe4engine::guides::after_login(&sh, &e)); } else { aoe4engine::guides::do_login(sh, e); }
    } else if !st.hidden { windows::show(Win::Panel); }
    slint::run_event_loop_until_quit()?;
    drop((poll, pr, fire_timer));
    Ok(())
}
thread_local! { static PILL_RESULT: RefCell<Option<String>> = const { RefCell::new(None) }; }

#[cfg(windows)]
fn round_corners(ui: &Panel) {
    use slint::winit_030::winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
    use slint::winit_030::WinitWindowAccessor;
    #[link(name = "dwmapi")] extern "system" { fn DwmSetWindowAttribute(h: isize, a: u32, v: *const u32, n: u32) -> i32; }
    ui.window().with_winit_window(|w| { if let Ok(h) = w.window_handle() { if let RawWindowHandle::Win32(h) = h.as_raw() {
        let pref: u32 = 2; unsafe { DwmSetWindowAttribute(h.hwnd.get(), 33, &pref, 4); } } } });
}

/// AOE4S_SHOT=<file.png>: render once (software renderer snapshot), save, quit. AOE4S_SHOT_MENU=1 opens the cog menu first.
fn shot(ui: &Panel, path: String) {
    if std::env::var_os("AOE4S_SHOT_MENU").is_some() { ui.set_menu_open(true); }
    if std::env::var_os("AOE4S_AM").is_some() { ui.set_am_open(true); }
    if let Ok(p) = std::env::var("AOE4S_PAGE") { intros::test_state(&p); }
    let w = ui.as_weak();
    slint::Timer::single_shot(Duration::from_millis(900), move || {
        if let Some(u) = w.upgrade() { if let Ok(b) = u.window().take_snapshot() { let _ = save_png(&path, b.as_bytes(), b.width(), b.height()); } }
        let _ = slint::quit_event_loop();
    });
}
/// Once the panel has a native window: DWM rounded corners, text drops (age page).
fn first_show(ui: &Panel) {
    thread_local! { static DONE: std::cell::Cell<bool> = const { std::cell::Cell::new(false) }; }
    if DONE.with(|d| d.replace(true)) { return; }
    #[cfg(windows)] round_corners(ui);
    dnd::register(ui.window(), dnd::Target::Panel);
}
/// Hide the tooltip (page switches, drags).
pub fn tips_hide(ui: &Panel) { ui.global::<Tips>().invoke_hide(); }
pub fn save_png(path: &str, rgba: &[u8], w: u32, h: u32) -> Result<(), Box<dyn std::error::Error>> {
    let f = std::io::BufWriter::new(std::fs::File::create(path)?);
    let mut e = png::Encoder::new(f, w, h); e.set_color(png::ColorType::Rgba); e.set_depth(png::BitDepth::Eight);
    e.write_header()?.write_image_data(rgba)?; Ok(())
}

/// Test render of the good-to-go window: AOE4S_GTG=ok|fix|nosteam|bad, AOE4S_SHOT=<png>.
fn gtg_shot(kind: &str) -> Result<(), slint::PlatformError> {
    let w = Gtg::new()?;
    let st = serde_json::json!({ "ok": kind != "bad", "name": "Capstar", "steam": match kind { "fix" => serde_json::json!(false), "nosteam" => serde_json::Value::Null, _ => serde_json::json!(true) }, "spotify_app": true });
    gtg::fill(&w, &st);
    if let Some(f) = gtg::frames().into_iter().nth(12) { w.set_face(f); }
    w.show()?;
    let out = std::env::var("AOE4S_SHOT").unwrap_or_default();
    let ww = w.as_weak();
    slint::Timer::single_shot(Duration::from_millis(400), move || { if let Some(w) = ww.upgrade() { if let Ok(b) = w.window().take_snapshot() { let _ = save_png(&out, b.as_bytes(), b.width(), b.height()); } } let _ = slint::quit_event_loop(); });
    slint::run_event_loop()
}

/// Test render of the window that is open besides the (unshown) panel: Add a song / picker.
fn sub_shot() -> Result<(), slint::PlatformError> {
    let out = std::env::var("AOE4S_SHOT").unwrap_or_default();
    slint::Timer::single_shot(Duration::from_millis(600), move || { add::snapshot(&out); pick::snapshot(&out); let _ = slint::quit_event_loop(); });
    slint::run_event_loop()
}
