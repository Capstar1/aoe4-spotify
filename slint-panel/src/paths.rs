//! Dashed outlines as Path commands (CSS `border: dashed` / SVG stroke-dasharray; Slint paths have no dash).
/// Rounded rectangle inset by half the stroke, dashes `on`/`off` px along the outline, in a w x h viewbox.
pub fn dashed_rect(w: f32, h: f32, r: f32, sw: f32, on: f32, off: f32) -> String {
    let (x0, y0, x1, y1) = (sw / 2.0, sw / 2.0, w - sw / 2.0, h - sw / 2.0); let r = r.min((x1 - x0) / 2.0).min((y1 - y0) / 2.0);
    let (lw, lh, q) = (x1 - x0 - 2.0 * r, y1 - y0 - 2.0 * r, std::f32::consts::FRAC_PI_2 * r);
    let per = 2.0 * (lw + lh) + 4.0 * q;
    let pt = |s: f32| -> (f32, f32) {
        let mut s = s.rem_euclid(per);
        let arc = |cx: f32, cy: f32, a0: f32, t: f32| { let a = a0 + t / r.max(0.001); (cx + r * a.cos(), cy + r * a.sin()) };
        use std::f32::consts::PI;
        if s < lw { return (x0 + r + s, y0); } s -= lw;
        if s < q { return arc(x1 - r, y0 + r, -PI / 2.0, s); } s -= q;
        if s < lh { return (x1, y0 + r + s); } s -= lh;
        if s < q { return arc(x1 - r, y1 - r, 0.0, s); } s -= q;
        if s < lw { return (x1 - r - s, y1); } s -= lw;
        if s < q { return arc(x0 + r, y1 - r, PI / 2.0, s); } s -= q;
        if s < lh { return (x0, y1 - r - s); } s -= lh;
        arc(x0 + r, y0 + r, PI, s)
    };
    let mut out = String::new(); let mut s = 0.0;
    while s < per - 0.5 {
        let e = (s + on).min(per); let (a, b) = pt(s); out += &format!("M {a:.2} {b:.2} ");
        let mut t = s + 1.0; while t < e { let (a, b) = pt(t); out += &format!("L {a:.2} {b:.2} "); t += 1.0; }
        let (a, b) = pt(e); out += &format!("L {a:.2} {b:.2} "); s += on + off;
    }
    out
}
#[cfg(test)]
mod tests {
    #[test]
    fn dashes_cover_the_outline() { let p = super::dashed_rect(384.0, 56.0, 10.0, 2.0, 7.0, 5.0); assert!(p.starts_with("M ") && p.matches('M').count() > 70); }
}
