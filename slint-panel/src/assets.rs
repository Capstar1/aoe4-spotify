//! Embedded runtime art (ui/img/age, ui/img/portraits), decoded on first use and cached.
use slint::{Image, Rgba8Pixel, SharedPixelBuffer};
use std::{cell::RefCell, collections::HashMap};

include!(concat!(env!("OUT_DIR"), "/assets.rs"));

thread_local! { static CACHE: RefCell<HashMap<String, Image>> = RefCell::new(HashMap::new()); static SCALE: std::cell::Cell<f32> = const { std::cell::Cell::new(1.0) }; }
/// Window scale factor: picks @1 / @1.5 renders and the pixel size of resampled portraits.
pub fn set_scale(f: f32) { SCALE.with(|s| s.set(f)); }
fn hi() -> bool { SCALE.with(|s| s.get()) > 1.25 }

fn bytes(path: &str) -> Option<&'static [u8]> { ASSETS.iter().find(|(n, _)| *n == path).map(|(_, b)| *b) }
fn decode(b: &[u8]) -> Option<image::RgbaImage> { image::load_from_memory(b).ok().map(|i| i.to_rgba8()) }
/// Round (anti-aliased) cut: the software renderer can't clip images to a rounded rectangle.
fn round(mut i: image::RgbaImage) -> image::RgbaImage {
    let r = i.width() as f32 / 2.0;
    for (x, y, p) in i.enumerate_pixels_mut() { let d = ((x as f32 + 0.5 - r).powi(2) + (y as f32 + 0.5 - r).powi(2)).sqrt(); p.0[3] = (p.0[3] as f32 * (r - d + 0.5).clamp(0.0, 1.0)).round() as u8; }
    i
}
fn to_image(i: &image::RgbaImage) -> Image { Image::from_rgba8(SharedPixelBuffer::<Rgba8Pixel>::clone_from_slice(i.as_raw(), i.width(), i.height())) }

/// age/<name> render for the current scale (1.0.9 renders exist at 100 % and 150 %).
pub fn age(name: &str) -> Image { load(&format!("age/{name}@{}.png", if hi() { "1.5" } else { "1" })) }
/// Octopath portrait by song key, resampled (Lanczos) to `d` logical px and cut round: the software renderer's own downscale is coarse.
pub fn portrait(key: &str, d: f32) -> Image {
    let px = (d * SCALE.with(|s| s.get())).round().max(1.0) as u32; let k = format!("portraits/{key}.jpg#{px}");
    CACHE.with(|c| c.borrow_mut().entry(k).or_insert_with(|| bytes(&format!("portraits/{key}.jpg")).and_then(decode).map(|i| to_image(&round(image::imageops::resize(&i, px, px, image::imageops::FilterType::Lanczos3)))).unwrap_or_default()).clone())
}
/// Any image file (cached song covers), resampled and cut round the same way; None when missing.
pub fn file(path: &std::path::Path, d: f32) -> Option<Image> {
    let px = (d * SCALE.with(|s| s.get())).round().max(1.0) as u32; let k = format!("{}#{px}", path.display());
    if let Some(i) = CACHE.with(|c| c.borrow().get(&k).cloned()) { return Some(i); }
    let i = image::open(path).ok()?.to_rgba8(); let i = to_image(&round(image::imageops::resize(&i, px, px, image::imageops::FilterType::Lanczos3)));
    CACHE.with(|c| c.borrow_mut().insert(k, i.clone())); Some(i)
}
fn load(path: &str) -> Image {
    CACHE.with(|c| c.borrow_mut().entry(path.to_string()).or_insert_with(|| bytes(path).and_then(decode).map(|i| to_image(&i)).unwrap_or_default()).clone())
}
/// The 54 frames of a 1.0.9 glow / equalizer strip (genglow.py), e.g. "glow19" (webp) or "eq19" (png).
pub fn strip(name: &str) -> Vec<Image> {
    let r = if hi() { "1.5" } else { "1" }; let path = if name.starts_with("glow") { format!("age/{name}@{r}.webp") } else { format!("age/{name}@{r}.png") };
    let Some(i) = bytes(&path).and_then(decode) else { return vec![] };
    let f = i.width() / 54;
    (0..54).map(|k| to_image(&image::imageops::crop_imm(&i, k * f, 0, f, i.height()).to_image())).collect()
}
