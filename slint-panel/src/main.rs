#![windows_subsystem = "windows"]
#![deny(warnings)]
//! Slint prototype of the 1.1 main panel: the view is ui/*.slint, this file only feeds it data (backend.rs, read-only)
//! and runs the fire animation (fire.rs). Prototype: clicks change the view only, nothing is saved or played.
//! `--fire <row>` starts with the fire on that row (as when that age's music plays in a match).
mod backend;
mod fire;
use slint::{Image, ModelRc, Rgba8Pixel, SharedPixelBuffer, VecModel};
use std::cell::RefCell;
use std::rc::Rc;

slint::include_modules!();

fn img(rgba: &[u8], w: usize, h: usize) -> Image { Image::from_rgba8(SharedPixelBuffer::<Rgba8Pixel>::clone_from_slice(rgba, w as u32, h as u32)) }
fn load_img(p: Option<std::path::PathBuf>) -> (Image, bool) { match p.and_then(|p| Image::load_from_path(&p).ok()) { Some(i) => (i, true), None => (Image::default(), false) } }

fn main() -> Result<(), slint::PlatformError> {
    slint::BackendSelector::new().backend_name("winit".into()).renderer_name("software".into())
        .with_winit_window_attributes_hook(|a| {
            #[cfg(windows)] { use slint::winit_030::winit::platform::windows::WindowAttributesExtWindows; a.with_undecorated_shadow(true) }
            #[cfg(not(windows))] { a }
        })
        .select()?;
    let d = backend::load();
    let ui = Panel::new()?;
    ui.set_enabled(d.set.enabled);
    ui.set_logged_in(d.logged_in);
    ui.set_fade(d.set.fade_seconds);
    ui.set_default_fade(2.0);
    ui.set_boss_on(d.set.boss_on);
    let rows: Vec<AgeRow> = d.ages.iter().map(|(k, lab)| {
        let uri = d.set.playlists.get(k).cloned().unwrap_or_default(); let (cover, has) = load_img(d.cover(&uri));
        let name = { let n = d.name(&uri); if n.is_empty() { "Not set".to_string() } else { n } };
        AgeRow { label: lab.replace(" Age", "").into(), name: name.into(), set: !uri.is_empty(), cover, has_cover: has, is_default: uri == d.set.default_playlists.get(k).cloned().unwrap_or_default() }
    }).collect();
    let nrows = rows.len() as i32;
    ui.set_ages(ModelRc::new(VecModel::from(rows)));
    let lit = d.intro_lit();
    ui.set_intros(ModelRc::new(VecModel::from(["I", "II", "III", "IV"].iter().zip(lit).map(|(r, l)| IntroAge { roman: (*r).into(), lit: l }).collect::<Vec<_>>())));
    let (mode, wl, pl, win, loss) = d.after();
    ui.set_am_mode(mode.into()); ui.set_am_wl(wl); ui.set_am_playlist_name(d.name(&pl).into());
    let (c, h) = load_img(d.cover(&pl)); ui.set_am_playlist_cover(c); ui.set_am_playlist_has(h);
    let (c, h) = load_img(d.cover(&win)); ui.set_win_cover(c); ui.set_win_has(h);
    let (c, h) = load_img(d.cover(&loss)); ui.set_loss_cover(c); ui.set_loss_has(h);

    // fire: 366 x 42 row (1.1 X-6 .. XR+6), scale 1 (96 DPI); glow drawn once
    let scale = ui.window().scale_factor();
    let (rw, rh) = ((366.0 * scale).round() as usize, (42.0 * scale).round() as usize);
    let (g, gw, gh) = fire::glow(rw, rh, 9.0 * scale, scale); ui.set_glow(img(&g, gw, gh));
    let fire = Rc::new(RefCell::new(fire::Fire::new(rw, rh, scale)));
    let timer = Rc::new(slint::Timer::default());
    let run = { let (w, f, t) = (ui.as_weak(), fire.clone(), timer.clone()); move |row: i32| {
        let Some(u) = w.upgrade() else { return }; u.set_playing(row);
        if row < 0 { t.stop(); return; }
        let (w2, f2) = (w.clone(), f.clone());
        t.start(slint::TimerMode::Repeated, std::time::Duration::from_millis(34), move || {
            let Some(u) = w2.upgrade() else { return }; let mut f = f2.borrow_mut(); let px = f.tick(); u.set_fire(img(&px, f.gw, f.gh)); });
    } };
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--fire") { run(args.get(i + 1).and_then(|s| s.parse().ok()).unwrap_or(1).min(nrows - 1)); }

    // view-only actions (prototype)
    let w = ui.as_weak();
    ui.on_toggle_enabled({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { u.set_enabled(!u.get_enabled()); } } });
    ui.on_toggle_boss({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { u.set_boss_on(!u.get_boss_on()); } } });
    ui.on_toggle_wl({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { u.set_am_wl(!u.get_am_wl()); } } });
    ui.on_toggle_playlists({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { u.set_pl_open(!u.get_pl_open()); } } });
    ui.on_toggle_am({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { u.set_am_open(!u.get_am_open()); } } });
    ui.on_set_mode({ let w = w.clone(); move |m| { if let Some(u) = w.upgrade() { u.set_am_mode(m); } } });
    ui.on_revert_fade({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { u.set_fade(u.get_default_fade()); } } });
    ui.on_open_in_spotify({ let run = run.clone(); let w = w.clone(); move |i| { let cur = w.upgrade().map(|u| u.get_playing()).unwrap_or(-1); run(if cur == i { -1 } else { i }); } });
    ui.on_close_app({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { let _ = u.hide(); } let _ = slint::quit_event_loop(); } });
    ui.on_minimize({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { use slint::winit_030::WinitWindowAccessor; u.window().with_winit_window(|ww| ww.set_minimized(true)); } } });
    ui.on_drag({ let w = w.clone(); move || { if let Some(u) = w.upgrade() { use slint::winit_030::WinitWindowAccessor; u.window().with_winit_window(|ww| { let _ = ww.drag_window(); }); } } });
    // round the corners like 1.1 (Windows 11 DWM: 8 px round, 1 px #3a3a3a border drawn by the view)
    ui.show()?;
    #[cfg(windows)] round_corners(&ui);
    slint::run_event_loop()?;
    let _ = timer;
    Ok(())
}

#[cfg(windows)]
fn round_corners(ui: &Panel) {
    use slint::winit_030::winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
    use slint::winit_030::WinitWindowAccessor;
    #[link(name = "dwmapi")] extern "system" { fn DwmSetWindowAttribute(h: isize, a: u32, v: *const u32, n: u32) -> i32; }
    ui.window().with_winit_window(|w| { if let Ok(h) = w.window_handle() { if let RawWindowHandle::Win32(h) = h.as_raw() {
        let pref: u32 = 2; unsafe { DwmSetWindowAttribute(h.hwnd.get(), 33, &pref, 4); } } } });
}
