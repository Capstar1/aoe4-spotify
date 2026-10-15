//! 1.0.9 ui/fire.py 'glow pool' fire (via ui/fire.js), ported 1:1: heat grid, Bayer 4x4 dither, 3 soft greens,
//! 60 % alpha, embers. Sim step 170 ms (every 5th frame), drawn every 34 ms as an EMA blend. Output: RGBA, gw x gh
//! cells; the view scales it up `c` times with pixelated sampling. `glow()` = the static wash + halo layer.
const SUB: u32 = 5;
const EMA: f32 = 0.35;
const DITHER_W: f32 = 0.10;
const CONTRAST: f32 = 0.75;
const FIRE_ALPHA: f32 = 0.6;
const BAY: [[i32; 4]; 4] = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]];
const STOPS: [[f32; 3]; 3] = [[16., 92., 46.], [29., 185., 84.], [110., 225., 160.]];
const GREEN: [f32; 3] = [29., 185., 84.];
const MINT: [f32; 3] = [110., 225., 160.];

fn sm(x: f32) -> f32 { let x = x.clamp(0., 1.); x * x * (3. - 2. * x) }
fn lut(f: impl Fn(f32) -> f32) -> [u8; 256] { let mut t = [0u8; 256]; for (v, o) in t.iter_mut().enumerate() { *o = f(v as f32).floor().clamp(0., 255.) as u8; } t }
fn falloff(u: f32) -> f32 { let t = sm((u - 1. / 3.) / (2. / 3.)); 1. - 0.72 * t }

pub struct Fire {
    pub gw: usize, pub gh: usize, #[allow(dead_code)] pub c: usize, bed: usize,
    edge: Vec<f32>, fg: Vec<f32>, heat: Vec<Vec<f32>>, embers: Vec<[f32; 3]>, yg: Vec<i32>, alpha: u32,
    sub: u32, prev: Vec<f32>, cur: Vec<f32>, ema: Vec<f32>, rng: u64,
    soft: [[f32; 3]; 3], ld: [u8; 256], lf: [u8; 256], lh: [u8; 256], t1: [u8; 256], t2: [u8; 256],
}

impl Fire {
    pub fn new(w: usize, h: usize, scale: f32) -> Self {
        let c = ((2.5 * scale).round() as usize).max(2); let (gw, gh) = (w.div_ceil(c), h.div_ceil(c));
        let mut soft = STOPS; for s in soft.iter_mut() { for i in 0..3 { s[i] = (STOPS[1][i] + (s[i] - STOPS[1][i]) * CONTRAST).round(); } }
        let mut f = Fire { gw, gh, c, bed: ((gh as f32 * 0.48).round() as usize).max(1),
            edge: (0..gw).map(|x| 1. + 0.6 * ((x as f32 - gw as f32 / 2.).abs() / (gw as f32 / 2.)).powi(2)).collect(),
            fg: (0..gw).map(|x| falloff((x as f32 + 0.5) / gw as f32)).collect(),
            heat: vec![vec![0.; gw]; gh], embers: vec![], yg: (0..gh).map(|y| (255. * 0.55 * (y as f32 / (gh.max(2) - 1) as f32)).round() as i32).collect(),
            alpha: (255. * FIRE_ALPHA) as u32, sub: 0, prev: vec![], cur: vec![], ema: vec![], rng: 7, soft,
            ld: lut(|v| 255. * sm(((v - 128.) / 255.) / DITHER_W + 0.5)), lf: lut(|v| 255. * sm((v / 255. - 0.04) / 0.08)), lh: lut(|v| v * 0.45),
            t1: lut(|v| 255. * sm((v / 255. - 0.38) / 0.2 + 0.5)), t2: lut(|v| 255. * sm((v / 255. - 0.72) / 0.2 + 0.5)) };
        f.embers = (0..4).map(|_| [f.rnd(0., gw as f32), f.rnd(0., 1.), f.rnd(-0.3, 0.3)]).collect();
        for _ in 0..gh * 2 { f.step(); }
        f.prev = f.cur.clone(); f.ema = f.cur.clone(); f
    }
    fn rnd(&mut self, a: f32, b: f32) -> f32 { self.rng = (self.rng.wrapping_mul(1103515245).wrapping_add(12345)) & 0x7fff_ffff; a + (b - a) * (self.rng as f32 / 0x7fff_ffff as f32) }
    fn step(&mut self) {
        let (gw, gh, bed) = (self.gw, self.gh, self.bed);
        for (j, y) in (gh - bed..gh).enumerate() { let k = 0.6 + 0.4 * j as f32 / bed as f32;
            for x in 0..gw { let r = self.rnd(0.15, 0.6); self.heat[y][x] = (r * 0.85 * self.edge[x] * self.fg[x] * k).min(1.); } }
        for y in (0..gh - bed).rev() { let f = 1. + (gh - bed - y) as f32 * 1.3;
            for x in 0..gw { let s = &self.heat[y + 1]; let v = (s[(x + gw - 1) % gw] + 2. * s[x] + s[(x + 1) % gw]) * 0.25; let r = self.rnd(0.01, 0.034); self.heat[y][x] = (v - r * f).max(0.); } }
        for i in 0..self.embers.len() { self.embers[i][1] += 1. / 32.; if self.embers[i][1] >= 1. { let (a, b) = (self.rnd(0., gw as f32), self.rnd(-0.3, 0.3)); self.embers[i] = [a, 0., b]; } }
        self.prev = std::mem::take(&mut self.cur);
        self.cur = (0..gw * gh).map(|i| (self.heat[i / gw][i % gw] * 255.).floor()).collect();
        if self.prev.is_empty() { self.prev = self.cur.clone(); }
    }
    /// Next frame (call every 34 ms): RGBA bytes, gw x gh.
    pub fn tick(&mut self) -> Vec<u8> {
        self.sub += 1; if self.sub >= SUB { self.sub = 0; self.step(); }
        let t = self.sub as f32 / SUB as f32;
        for i in 0..self.ema.len() { let target = self.prev[i] + (self.cur[i] - self.prev[i]) * t; self.ema[i] += (target - self.ema[i]) * EMA; }
        self.frame(t)
    }
    fn frame(&self, t: f32) -> Vec<u8> {
        let (gw, gh) = (self.gw, self.gh); let n = gw * gh; let h = &self.ema;
        let mut a = vec![0u8; n]; let mut col = vec![0f32; n * 3];
        for y in 0..gh { for x in 0..gw { let i = y * gw + x; let v = (h[i].round() as i32).clamp(0, 255);
            let d = (v - (BAY[y % 4][x % 4] * 255 / 16) + 128).clamp(0, 255) as usize;
            a[i] = (self.ld[d] as u32 * self.lf[v as usize] as u32 / 255) as u8; } }
        let mut nb = vec![0u32; n];
        for y in 0..gh { for x in 0..gw { let mut s = 0u32;
            for dy in -1i32..=1 { for dx in -1i32..=1 { if dx == 0 && dy == 0 { continue; }
                let yy = (y as i32 + dy).clamp(0, gh as i32 - 1) as usize; let xx = (x as i32 + dx).clamp(0, gw as i32 - 1) as usize; s += a[yy * gw + xx] as u32; } }
            nb[y * gw + x] = if y >= gh - gh.min(3) { 255 } else { s.min(255) }; } }
        for i in 0..n { a[i] = (a[i] as u32 * nb[i] / 255) as u8; }
        for y in 0..gh { for x in 0..gw { let i = y * gw + x;
            let tt = ((self.lh[(h[i].round() as i32).clamp(0, 255) as usize] as i32 + self.yg[y]).min(255)) as usize;
            let (a1, a2) = (self.t1[tt] as f32 / 255., self.t2[tt] as f32 / 255.);
            for k in 0..3 { let c1 = self.soft[1][k] * a1 + self.soft[0][k] * (1. - a1); col[i * 3 + k] = self.soft[2][k] * a2 + c1 * (1. - a2); } } }
        let top = (gh - self.bed) as f32;
        for e in &self.embers { let ph = e[1] + t / 32.; let ey = top * (1. - ph);
            let x = ((((e[0] + e[2] * ph * 32.).floor() as i64) % gw as i64 + gw as i64) % gw as i64) as usize; let y0 = ey.floor(); let f = ey - y0;
            for (yy, wt) in [(y0 as i64, 1. - f), (y0 as i64 + 1, f)] { if yy >= 3 && (yy as usize) < gh && wt > 0.02 { let i = yy as usize * gw + x;
                for k in 0..3 { col[i * 3 + k] = self.soft[2][k] * wt + col[i * 3 + k] * (1. - wt); } a[i] = a[i].max((255. * wt) as u8); } } }
        let mut out = vec![0u8; n * 4];
        for i in 0..n { for k in 0..3 { out[i * 4 + k] = col[i * 3 + k].clamp(0., 255.) as u8; } out[i * 4 + 3] = (a[i] as u32 * self.alpha / 255) as u8; }
        out
    }
}

fn in_rr(x: f32, y: f32, w: f32, h: f32, r: f32) -> f32 {   // coverage of pixel centre (x, y) in a rounded rect at 0,0 (2x2 supersampled)
    let mut c = 0.; for (ox, oy) in [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)] { let (px, py) = (x + ox, y + oy);
        if px < 0. || py < 0. || px > w || py > h { continue; }
        let dx = (r - px).max(px - (w - r)).max(0.); let dy = (r - py).max(py - (h - r)).max(0.); if dx * dx + dy * dy <= r * r { c += 0.25; } } c
}
/// Static glow: halo outside the row (blurred, rect cut out), green wash rising from the bottom, mint bloom, eased left -> right.
/// Returns (RGBA, width, height) for a (w + 2 pad) x (h + 2 pad) image, pad = 10 * scale.
pub fn glow(w: usize, h: usize, r: f32, scale: f32) -> (Vec<u8>, usize, usize) {
    let pad = (10. * scale).round() as usize; let (cw, ch) = (w + 2 * pad, h + 2 * pad);
    let mut m = vec![0f32; cw * ch];
    for y in 0..ch { for x in 0..cw { m[y * cw + x] = in_rr(x as f32 - pad as f32, y as f32 - pad as f32, w as f32, h as f32, r); } }
    // gaussian blur, sigma 4.5 * scale (separable)
    let s = 4.5 * scale; let rad = (s * 3.).ceil() as i32; let k: Vec<f32> = (-rad..=rad).map(|i| (-(i * i) as f32 / (2. * s * s)).exp()).collect(); let ks: f32 = k.iter().sum();
    let blur = |src: &Vec<f32>, horiz: bool| -> Vec<f32> { let mut o = vec![0f32; cw * ch];
        for y in 0..ch { for x in 0..cw { let mut acc = 0.; for (j, kv) in k.iter().enumerate() { let d = j as i32 - rad;
            let (xx, yy) = if horiz { (x as i32 + d, y as i32) } else { (x as i32, y as i32 + d) };
            if xx >= 0 && yy >= 0 && (xx as usize) < cw && (yy as usize) < ch { acc += src[yy as usize * cw + xx as usize] * kv; } } o[y * cw + x] = acc / ks; } } o };
    let halo = blur(&blur(&m, true), false);
    let mut out = vec![0u8; cw * ch * 4];
    for y in 0..ch { for x in 0..cw { let i = y * cw + x; let inside = m[i];
        let ha = halo[i] * 0.16 * 1.6 * (1. - inside);
        let (mut rgb, mut al) = (GREEN, ha);
        if inside > 0. { let (ix, iy) = (x as f32 - pad as f32, y as f32 - pad as f32); let v = (iy + 0.5) / h as f32;
            let wa = ((v - 0.25) / 0.75).clamp(0., 1.).powf(1.8) * 0.22; let bl = ((v - 0.55) / 0.45).clamp(0., 1.) * 0.18; let fx = falloff((ix + 0.5) / w as f32);
            let (a1, a2) = (wa * fx, bl * fx); let a = a1 + a2 * (1. - a1);
            if a > 0. { for k in 0..3 { rgb[k] = (MINT[k] * a2 + GREEN[k] * a1 * (1. - a2)) / a; } }
            al = ha + a * inside; }
        for kk in 0..3 { out[i * 4 + kk] = rgb[kk].clamp(0., 255.) as u8; } out[i * 4 + 3] = (al.clamp(0., 1.) * 255.) as u8; } }
    (out, cw, ch)
}
