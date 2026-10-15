//! "You're good to go" window (Tauri 1.1 ui/gtg.html): face animation, check rows, Fix for the launch option.
use crate::{Gtg, GtgRow};
use aoe4engine::{guides::{self, Shell, Win}, Engine};
use slint::{ComponentHandle, Image, ModelRc, Rgba8Pixel, SharedPixelBuffer, Timer, TimerMode, VecModel};
use std::{cell::RefCell, rc::Rc, sync::Arc, time::Duration};

const DUR: [u64; 60] = [70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,70,70,60,60];
static SHEET: &[u8] = include_bytes!("../../ui/img/gtg_face.jpg");

/// The 60 frames of the 10 x 6 sprite sheet, each with the CSS mask (opaque to r - 9 px, fading to the edge).
pub fn frames() -> Vec<Image> {
    let Ok(img) = image::load_from_memory(SHEET) else { return vec![] };
    let img = img.to_rgba8();
    let f = img.width() / 10;
    let (r, fe) = (f as f32 / 2.0, 9.0 * f as f32 / 124.0);
    (0..60).map(|i| {
        let (ox, oy) = ((i % 10) * f, (i / 10) * f);
        let mut b = SharedPixelBuffer::<Rgba8Pixel>::new(f, f);
        for (k, px) in b.make_mut_slice().iter_mut().enumerate() {
            let (x, y) = (k as u32 % f, k as u32 / f);
            let p = img.get_pixel((ox + x).min(img.width() - 1), (oy + y).min(img.height() - 1)).0;
            let d = ((x as f32 + 0.5 - r).powi(2) + (y as f32 + 0.5 - r).powi(2)).sqrt();
            let a = ((r - d) / fe).clamp(0.0, 1.0);
            *px = Rgba8Pixel { r: p[0], g: p[1], b: p[2], a: (a * 255.0).round() as u8 };
        }
        Image::from_rgba8_premultiplied(premul(b))
    }).collect()
}
fn premul(mut b: SharedPixelBuffer<Rgba8Pixel>) -> SharedPixelBuffer<Rgba8Pixel> {
    for p in b.make_mut_slice() { let a = p.a as u16; p.r = (p.r as u16 * a / 255) as u8; p.g = (p.g as u16 * a / 255) as u8; p.b = (p.b as u16 * a / 255) as u8; }
    b
}

/// Rows of gtg.html draw(): Spotify, Age of Empires IV, and the "Skill" joke row (always).
pub fn rows(st: &serde_json::Value) -> Vec<GtgRow> {
    let app_ok = st["spotify_app"].as_bool() != Some(false);
    let sub = st["name"].as_str().map(|n| format!("Connected as {n}")).unwrap_or_else(|| "Connected".into());
    let r = |k: &str, l: &str, d: &str, fix: bool| GtgRow { kind: k.into(), label: l.into(), detail: d.into(), fix };
    let mut v = vec![r(if app_ok { "ok" } else { "warn" }, "Spotify", if app_ok { &sub } else { "Spotify app not installed" }, false)];
    v.push(match st["steam"].as_bool() {
        Some(true) => r("ok", "Age of Empires IV", "Starts with the game", false),
        Some(false) => r("warn", "Age of Empires IV", "Launch option missing", true),
        None => r("warn", "Age of Empires IV", "Steam not found", false),
    });
    v.push(r("warn", "Skill", "Issue detected", false));
    v
}

thread_local! { static OPEN: RefCell<Option<(Gtg, Timer)>> = const { RefCell::new(None) }; }

/// Open (or refresh) the window from engine.gtg (filled by guides::show_gtg).
pub fn open(eng: &Arc<Engine>, sh: &Arc<dyn Shell>) {
    let st = eng.gtg.lock().unwrap().clone();
    let w = match OPEN.with(|o| o.borrow().as_ref().map(|(w, _)| w.clone_strong())) { Some(w) => w, None => match build(eng, sh) { Some(w) => w, None => return } };
    fill(&w, &st);
    let _ = w.show();
}
pub fn close() { OPEN.with(|o| if let Some((w, t)) = o.borrow_mut().take() { t.stop(); let _ = w.hide(); }); }

pub fn fill(w: &Gtg, st: &serde_json::Value) {
    w.set_ok(st["ok"].as_bool().unwrap_or(false));
    w.set_rows(ModelRc::new(VecModel::from(rows(st))));
}

fn build(eng: &Arc<Engine>, sh: &Arc<dyn Shell>) -> Option<Gtg> {
    let w = Gtg::new().ok()?;
    let fr = Rc::new(frames());
    if let Some(f) = fr.first() { w.set_face(f.clone()); }
    // face animation with the gtg.py frame durations
    let t = Timer::default();
    let i = Rc::new(std::cell::Cell::new(0usize));
    let (ww, fr2, i2) = (w.as_weak(), fr.clone(), i.clone());
    t.start(TimerMode::Repeated, Duration::from_millis(10), move || {
        thread_local! { static ACC: std::cell::Cell<u64> = const { std::cell::Cell::new(0) }; }
        let acc = ACC.with(|a| { a.set(a.get() + 10); a.get() });
        if acc < DUR[i2.get()] || fr2.is_empty() { return; }
        ACC.with(|a| a.set(0)); i2.set((i2.get() + 1) % 60);
        if let Some(w) = ww.upgrade() { w.set_face(fr2[i2.get()].clone()); }
    });
    let ww = w.as_weak();
    w.on_close(move || { let _ = ww; close(); });
    w.on_done(close);
    let s = sh.clone();
    w.on_open_panel(move || { s.show(Win::Panel); close(); });
    let (s, e) = (sh.clone(), eng.clone());
    w.on_retry(move || { guides::do_login(s.clone(), e.clone()); close(); });
    let (e, ww) = (eng.clone(), w.as_weak());
    w.on_fix(move || {
        let Some(w) = ww.upgrade() else { return };
        if w.get_fixing() { return; }
        w.set_fixing(true);
        let (e, ww) = (e.clone(), ww.clone());
        std::thread::spawn(move || {
            let st = guides::gtg_fix(&e);
            let _ = slint::invoke_from_event_loop(move || if let Some(w) = ww.upgrade() { w.set_fixing(false); fill(&w, &st); });
        });
    });
    w.window().on_close_requested(|| { close(); slint::CloseRequestResponse::HideWindow });
    OPEN.with(|o| *o.borrow_mut() = Some((w.clone_strong(), t)));
    Some(w)
}
