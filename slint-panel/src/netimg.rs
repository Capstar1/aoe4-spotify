//! Spotify artwork for the picker / Add a song lists: fetched off the UI thread, resampled, kept for the session.
use slint::{Image, Rgba8Pixel, SharedPixelBuffer};
use std::{cell::RefCell, collections::{HashMap, HashSet}, sync::{atomic::{AtomicU64, Ordering}, Mutex}};

/// Bumped whenever a picture arrives (windows redraw their lists).
pub static VER: AtomicU64 = AtomicU64::new(0);
static DONE: Mutex<Vec<(String, u32, u32, u32, Vec<u8>)>> = Mutex::new(Vec::new());
thread_local! { static CACHE: RefCell<HashMap<(String, u32), Image>> = RefCell::new(HashMap::new()); static ASKED: RefCell<HashSet<(String, u32)>> = RefCell::new(HashSet::new()); }

/// Picture for `url` at `px` physical pixels, rounded corners `rad` px (0 = square). None until it has arrived.
pub fn get(url: &str, px: u32, rad: u32) -> Option<Image> {
    if !url.starts_with("https://") { return None; }
    drain();
    let k = (format!("{url}#{rad}"), px);
    if let Some(i) = CACHE.with(|c| c.borrow().get(&k).cloned()) { return Some(i); }
    if ASKED.with(|a| a.borrow_mut().insert(k.clone())) {
        let u = url.to_string();
        std::thread::spawn(move || {
            let Ok(b) = aoe4core::spotify::fetch(&u) else { return };
            let Ok(i) = image::load_from_memory(&b) else { return };
            let i = image::imageops::resize(&i.to_rgba8(), px, px, image::imageops::FilterType::Lanczos3);
            let i = corners(i, rad);
            DONE.lock().unwrap().push((u, rad, px, px, i.into_raw())); VER.fetch_add(1, Ordering::SeqCst);
        });
    }
    None
}
/// Rounded-corner cut (the software renderer doesn't clip images to rounded rectangles).
pub fn corners(mut i: image::RgbaImage, rad: u32) -> image::RgbaImage {
    if rad == 0 { return i; }
    let (w, h, r) = (i.width() as f32, i.height() as f32, rad as f32);
    for (x, y, p) in i.enumerate_pixels_mut() {
        let (fx, fy) = (x as f32 + 0.5, y as f32 + 0.5);
        let cx = if fx < r { r } else if fx > w - r { w - r } else { fx }; let cy = if fy < r { r } else if fy > h - r { h - r } else { fy };
        let d = ((fx - cx).powi(2) + (fy - cy).powi(2)).sqrt();
        p.0[3] = (p.0[3] as f32 * (r - d + 0.5).clamp(0.0, 1.0)).round() as u8;
    }
    i
}
fn drain() {
    let v: Vec<_> = std::mem::take(&mut *DONE.lock().unwrap());
    for (u, rad, w, h, px) in v { let img = Image::from_rgba8(SharedPixelBuffer::<Rgba8Pixel>::clone_from_slice(&px, w, h)); CACHE.with(|c| c.borrow_mut().insert((format!("{u}#{rad}"), w), img)); }
}
