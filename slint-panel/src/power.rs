//! 1.0.9 power icon (panel.py _pwr_frame / anim_enabled): ring + bar drawn at 4x and rotated about (w/2, 0.54h),
//! one frame per 3 degrees, colour mixed green -> coral by the angle. A toggle spins it forward a half turn
//! (0.45 s, ease-in-out cubic, never reverses, also when toggled again mid-spin); the label colour follows.
//! (The software renderer can't rotate images, so the frames are drawn here.)
use crate::Panel;
use slint::{ComponentHandle, Color, Image, Rgba8Pixel, SharedPixelBuffer, Timer, TimerMode};
use std::{cell::RefCell, collections::HashMap, time::{Duration, Instant}};

const PSTEP: i32 = 3;
const DUR: f32 = 0.45;
const G0: [f32; 3] = [29.0, 185.0, 84.0];        // #1DB954
const CORAL: [f32; 3] = [229.0, 103.0, 95.0];    // #e5675f
const TX: [f32; 3] = [242.0, 242.0, 242.0];      // #f2f2f2
const CORAL_TX: [f32; 3] = [240.0, 214.0, 212.0]; // #f0d6d4

struct St { frames: HashMap<i32, Image>, a: Option<f32>, pos: f32, anim: Option<(f32, f32, f32, Instant)>, timer: Option<Timer>, ui: Option<slint::Weak<Panel>> }
thread_local! {
    static ST: RefCell<St> = RefCell::new(St { frames: HashMap::new(), a: None, pos: 0.0, anim: None, timer: None, ui: None });
    static PAUSED: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}
fn paused() -> bool { PAUSED.with(|p| p.get()) }
/// Minimized: stop the 8 ms redraw. A spin that was in progress finishes from the elapsed clock on restore.
pub fn set_paused(p: bool) {
    PAUSED.with(|c| c.set(p));
    if p { ST.with(|s| s.borrow_mut().timer = None); return; }
    if !ST.with(|s| s.borrow().anim.is_some()) { return; }
    ST.with(|s| { let mut s = s.borrow_mut(); if s.timer.is_none() { let t = Timer::default(); t.start(TimerMode::Repeated, Duration::from_millis(8), step); s.timer = Some(t); } });
    step();
}

/// Colour position: 0 deg = on (green), 180 = off (coral), 360 = on again.
pub fn pwr_t(a: f32) -> f32 { let a = a.rem_euclid(360.0); 1.0 - (a - 180.0).abs() / 180.0 }
fn mix(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] { [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t] }

/// Coverage of the upright icon at a point (high-res coords, size m).
fn inside(x: f32, y: f32, m: f32, lw: f32) -> bool {
    let (cx, cy, r) = (0.5 * m, 0.54 * m, 0.38 * m);
    let (dx, dy) = (x - cx, y - cy); let d = (dx * dx + dy * dy).sqrt();
    if d <= r && d >= r - lw { let th = dy.atan2(dx).to_degrees().rem_euclid(360.0); if !(th > 240.0 && th < 300.0) { return true; } }
    let (bx0, bx1, by0, by1, rr) = (m / 2.0 - lw / 2.0, m / 2.0 + lw / 2.0, 0.04 * m, 0.5 * m, lw / 2.0);
    if x >= bx0 && x <= bx1 && y >= by0 + rr && y <= by1 - rr { return true; }
    let cyc = if y < by0 + rr { by0 + rr } else if y > by1 - rr { by1 - rr } else { return false };
    let (ex, ey) = (x - m / 2.0, y - cyc); x >= bx0 && x <= bx1 && ex * ex + ey * ey <= rr * rr
}
fn frame(k: i32, px: u32) -> Image {
    let ang = (k * PSTEP) as f32; let col = mix(G0, CORAL, pwr_t(ang));
    let q = 4.0; let m = px as f32 * q; let lw = (3.0 * px as f32 / 30.0 * q).round();
    let (s, c) = ang.to_radians().sin_cos(); let (ox, oy) = (m / 2.0, 0.54 * m);
    let mut buf = SharedPixelBuffer::<Rgba8Pixel>::new(px, px);
    for (i, p) in buf.make_mut_slice().iter_mut().enumerate() {
        let (pxx, pyy) = ((i as u32 % px) as f32, (i as u32 / px) as f32); let mut n = 0;
        for sy in 0..4 { for sx in 0..4 {
            let (hx, hy) = ((pxx + (sx as f32 + 0.5) / 4.0) * q, (pyy + (sy as f32 + 0.5) / 4.0) * q);
            let (dx, dy) = (hx - ox, hy - oy);   // rotate back (icon turns clockwise by ang)
            let (ux, uy) = (ox + dx * c + dy * s, oy - dx * s + dy * c);
            if inside(ux, uy, m, lw) { n += 1; }
        } }
        let a = n as f32 / 16.0;   // premultiplied
        *p = Rgba8Pixel { r: (col[0] * a) as u8, g: (col[1] * a) as u8, b: (col[2] * a) as u8, a: (255.0 * a) as u8 };
    }
    Image::from_rgba8_premultiplied(buf)
}
fn apply(ui: &Panel, a: f32) {
    let k = ((a.rem_euclid(360.0) / PSTEP as f32).round() as i32).rem_euclid(360 / PSTEP);
    let px = (30.0f32 * ui.window().scale_factor()).round() as u32; let px = px + px % 2;
    let img = ST.with(|s| s.borrow_mut().frames.entry(k).or_insert_with(|| frame(k, px)).clone());
    let t = mix(TX, CORAL_TX, pwr_t(a));
    ui.set_pwr_img(img); ui.set_pwr_tx(Color::from_rgb_u8(t[0] as u8, t[1] as u8, t[2] as u8));
}
/// Settled icon for the current state (start-up, no animation).
pub fn init(ui: &Panel) {
    let a = if ui.get_enabled() { 0.0 } else { 180.0 };
    ST.with(|s| { let mut s = s.borrow_mut(); s.pos = a; s.ui = Some(ui.as_weak()); });
    apply(ui, a);
}
/// Enabled changed: spin forward to upright (on) or upside down (off); snap while the panel isn't on screen.
pub fn spin(ui: &Panel, to_off: bool, animate: bool) {
    let goal = if to_off { 180.0 } else { 0.0 };
    if !animate { ST.with(|s| { let mut s = s.borrow_mut(); s.anim = None; s.timer = None; s.a = None; s.pos = goal; }); apply(ui, goal); return; }
    let (a0, mid) = ST.with(|s| { let s = s.borrow(); (s.a.unwrap_or(if to_off { 0.0 } else { 180.0 }), s.a.is_some()) });
    let d = (goal - a0).rem_euclid(360.0);
    let b = if mid && d == 0.0 { a0 } else { a0 + if d == 0.0 { 360.0 } else { d } };
    let dur = DUR * ((b - a0) / 180.0).max(0.35);
    ST.with(|s| { let mut s = s.borrow_mut(); s.anim = Some((a0, b, dur, Instant::now())); s.a = Some(a0);
        if s.timer.is_none() && !paused() { let t = Timer::default(); t.start(TimerMode::Repeated, Duration::from_millis(8), step); s.timer = Some(t); } });
    if !paused() { step(); }
}
fn step() {
    let Some((a0, b, dur, t0, ui)) = ST.with(|s| { let s = s.borrow(); s.anim.map(|(a0, b, d, t)| (a0, b, d, t, s.ui.clone())) }) else { return };
    let Some(ui) = ui.and_then(|w| w.upgrade()) else { return };
    let u = if dur > 0.0 { (t0.elapsed().as_secs_f32() / dur).min(1.0) } else { 1.0 };
    let e = if u < 0.5 { 4.0 * u * u * u } else { 1.0 - (-2.0 * u + 2.0).powi(3) / 2.0 };
    let a = a0 + (b - a0) * e; apply(&ui, a);
    ST.with(|s| { let mut s = s.borrow_mut(); if u < 1.0 { s.a = Some(a); } else { s.a = None; s.anim = None; s.pos = b.rem_euclid(360.0); s.timer = None; } });
}
