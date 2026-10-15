// 1.0.9 ui/fire.py 'glow pool' fire on the age row that is playing, ported 1:1 (heat grid, Bayer 4x4 dither, 3 soft greens,
// 60 % alpha, embers, glow wash + bloom + halo). Sim step 170 ms, drawn every 34 ms as an EMA blend. Runs only while visible.
const FIRE = (() => {
  const STEP_MS = 170, SUB = 5, FRAME_MS = 34, EMA = 0.35, DITHER_W = 0.10, CONTRAST = 0.75, FIRE_ALPHA = 0.6;
  const BAY = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], STOPS = [[16, 92, 46], [29, 185, 84], [110, 225, 160]], GREEN = [29, 185, 84], MINT = [110, 225, 160];
  const SOFT = STOPS.map((s) => s.map((v, i) => Math.round(STOPS[1][i] + (v - STOPS[1][i]) * CONTRAST)));
  const sm = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
  const L = (f) => Array.from({ length: 256 }, (_, v) => Math.floor(f(v)));
  const LD = L((v) => 255 * sm(((v - 128) / 255) / DITHER_W + 0.5)), LF = L((v) => 255 * sm((v / 255 - 0.04) / 0.08)), LH = L((v) => v * 0.45);
  const T1 = L((v) => 255 * sm((v / 255 - 0.38) / 0.2 + 0.5)), T2 = L((v) => 255 * sm((v / 255 - 0.72) / 0.2 + 0.5));
  const falloff = (u) => { let t = Math.min(1, Math.max(0, (u - 1 / 3) / (2 / 3))); t = t * t * (3 - 2 * t); return 1 - 0.72 * t; };
  let rng = 7; const rnd = (a, b) => { rng = (rng * 1103515245 + 12345) & 0x7fffffff; return a + (b - a) * (rng / 0x7fffffff); };
  class Fire {
    constructor(w, h, r, S) {
      Object.assign(this, { w, h, r, S }); const c = this.c = Math.max(2, Math.round(2.5 * S)); const gw = this.gw = Math.ceil(w / c), gh = this.gh = Math.ceil(h / c);
      this.bed = Math.max(1, Math.round(gh * 0.48)); this.edge = []; this.fg = [];
      for (let x = 0; x < gw; x++) { this.edge.push(1 + 0.6 * (Math.abs(x - gw / 2) / (gw / 2)) ** 2); this.fg.push(falloff((x + 0.5) / gw)); }
      this.heat = Array.from({ length: gh }, () => new Float32Array(gw)); this.embers = [0, 1, 2, 3].map(() => [rnd(0, gw), rnd(0, 1), rnd(-0.3, 0.3)]);
      this.yg = Array.from({ length: gh }, (_, y) => Math.round(255 * 0.55 * (y / Math.max(1, gh - 1)))); this.alpha = Math.floor(255 * FIRE_ALPHA);
      this.cv = document.createElement("canvas"); this.cv.width = gw; this.cv.height = gh; this.g = this.cv.getContext("2d"); this.id = this.g.createImageData(gw, gh);
      this.sub = 0; for (let i = 0; i < gh * 2; i++) this.step(); this.prev = this.cur; this.ema = Float32Array.from(this.cur);
    }
    step() {
      const { gw, gh, bed, heat, edge, fg } = this;
      for (let j = 0, y = gh - bed; y < gh; y++, j++) { const k = 0.6 + 0.4 * j / bed; for (let x = 0; x < gw; x++) heat[y][x] = Math.min(1, rnd(0.15, 0.6) * 0.85 * edge[x] * fg[x] * k); }
      for (let y = gh - bed - 1; y >= 0; y--) { const s = heat[y + 1], f = 1 + (gh - bed - y) * 1.3; for (let x = 0; x < gw; x++) heat[y][x] = Math.max(0, (s[(x - 1 + gw) % gw] + 2 * s[x] + s[(x + 1) % gw]) * 0.25 - rnd(0.01, 0.034) * f); }
      for (const e of this.embers) { e[1] += 1 / 32; if (e[1] >= 1) { e[0] = rnd(0, gw); e[1] = 0; e[2] = rnd(-0.3, 0.3); } }
      this.prev = this.cur; const g = new Float32Array(gw * gh); for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) g[y * gw + x] = Math.floor(heat[y][x] * 255); this.cur = g; if (!this.prev) this.prev = g;
    }
    tick() { if (++this.sub >= SUB) { this.sub = 0; this.step(); } const t = this.sub / SUB, e = this.ema, p = this.prev, c = this.cur;
      for (let i = 0; i < e.length; i++) e[i] = e[i] + ((p[i] + (c[i] - p[i]) * t) - e[i]) * EMA; return this.frame(t); }
    frame(t) {
      const { gw, gh } = this, n = gw * gh, h = this.ema, A = new Uint8ClampedArray(n), col = new Uint8ClampedArray(n * 3);
      for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) { const i = y * gw + x, v = Math.round(h[i]); A[i] = (LD[Math.max(0, Math.min(255, v - Math.floor(BAY[y % 4][x % 4] * 255 / 16) + 128))] * LF[v]) / 255; }
      const nbA = new Uint8ClampedArray(n);
      for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) { let s = 0; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { if (!dx && !dy) continue; const yy = Math.min(gh - 1, Math.max(0, y + dy)), xx = Math.min(gw - 1, Math.max(0, x + dx)); s += A[yy * gw + xx]; } nbA[y * gw + x] = y >= gh - Math.min(3, gh) ? 255 : s; }
      for (let i = 0; i < n; i++) A[i] = (A[i] * nbA[i]) / 255;
      for (let y = 0; y < gh; y++) for (let x = 0; x < gw; x++) { const i = y * gw + x, tt = Math.min(255, LH[Math.round(h[i])] + this.yg[y]), a1 = T1[tt] / 255, a2 = T2[tt] / 255;
        for (let k = 0; k < 3; k++) { const c1 = SOFT[1][k] * a1 + SOFT[0][k] * (1 - a1); col[i * 3 + k] = SOFT[2][k] * a2 + c1 * (1 - a2); } }
      const top = gh - this.bed;
      for (const [ex, ph0, dx] of this.embers) { const ph = ph0 + t / 32, ey = top * (1 - ph), x = ((Math.floor(ex + dx * ph * 32) % gw) + gw) % gw, y0 = Math.floor(ey), f = ey - y0;
        for (const [yy, wt] of [[y0, 1 - f], [y0 + 1, f]]) if (yy >= 3 && yy < gh && wt > 0.02) { const i = yy * gw + x; for (let k = 0; k < 3; k++) col[i * 3 + k] = SOFT[2][k] * wt + col[i * 3 + k] * (1 - wt); A[i] = Math.max(A[i], 255 * wt); } }
      const d = this.id.data; for (let i = 0; i < n; i++) { d[i * 4] = col[i * 3]; d[i * 4 + 1] = col[i * 3 + 1]; d[i * 4 + 2] = col[i * 3 + 2]; d[i * 4 + 3] = Math.floor(A[i] * this.alpha / 255); }
      this.g.putImageData(this.id, 0, 0); return this.cv;
    }
  }
  // glow layer (static): halo outside the row, green wash rising from the bottom, mint bloom low, eased left -> right
  function glow(w, h, r, S) {
    const pad = Math.round(10 * S), c = document.createElement("canvas"); c.width = w + 2 * pad; c.height = h + 2 * pad; const g = c.getContext("2d");
    const rrp = (x, y, ww, hh, rr) => { g.beginPath(); g.roundRect(x, y, ww, hh, rr); };
    g.save(); g.filter = `blur(${4.5 * S}px)`; rrp(pad, pad, w, h, r); g.fillStyle = `rgba(29,185,84,${0.16 * 1.6})`; g.fill(); g.restore();
    g.save(); g.globalCompositeOperation = "destination-out"; rrp(pad, pad, w, h, r); g.fillStyle = "#000"; g.fill(); g.restore();
    const inner = document.createElement("canvas"); inner.width = w; inner.height = h; const q = inner.getContext("2d"), im = q.createImageData(w, h);
    for (let y = 0; y < h; y++) { const v = (y + 0.5) / h, wa = Math.min(1, Math.max(0, (v - 0.25) / 0.75)) ** 1.8 * 0.22, bl = Math.min(1, Math.max(0, (v - 0.55) / 0.45)) * 0.18;
      for (let x = 0; x < w; x++) { const fx = falloff((x + 0.5) / w), a1 = wa * fx, a2 = bl * fx, a = a1 + a2 * (1 - a1), i = (y * w + x) * 4;
        for (let k = 0; k < 3; k++) im.data[i + k] = a ? (MINT[k] * a2 + GREEN[k] * a1 * (1 - a2)) / a : 0; im.data[i + 3] = a * 255; } }
    q.putImageData(im, 0, 0); q.globalCompositeOperation = "destination-in"; q.beginPath(); q.roundRect(0, 0, w, h, r); q.fill();
    g.drawImage(inner, pad, pad); return { c, pad };
  }
  let st = null;   // { el, fire, key, job }
  function place(parent, x0, y0, x1, y1, r) {   // called on every redraw of the playing row; reuses the running fire
    const S = window.devicePixelRatio || 1, w = Math.round((x1 - x0) * S), h = Math.round((y1 - y0) * S), rp = Math.round(r * S), key = [w, h, rp].join();
    if (!st || st.key !== key) { stop(); const f = new Fire(w, h, rp, S), gl = glow(w, h, rp, S), el = document.createElement("div"), out = document.createElement("canvas");
      out.width = w; out.height = h; el.style.cssText = "position:absolute;pointer-events:none"; const gi = gl.c; gi.style.cssText = `position:absolute;left:${-gl.pad / S}px;top:${-gl.pad / S}px;width:${gi.width / S}px;height:${gi.height / S}px`;
      out.style.cssText = `position:absolute;left:0;top:0;width:${w / S}px;height:${h / S}px;border-radius:${r}px;filter:blur(${0.3}px)`; el.append(gi, out); st = { el, out, fire: f, key, job: 0 }; }
    Object.assign(st.el.style, { left: x0 + "px", top: y0 + "px" }); parent.appendChild(st.el); start(); return st.el;
  }
  function render() { const o = st.out.getContext("2d"); o.clearRect(0, 0, st.out.width, st.out.height); o.imageSmoothingEnabled = false; const f = st.fire; o.drawImage(f.tick(), 0, 0, f.gw * f.c, f.gh * f.c); }
  function start() { if (!st || st.job) return; const loop = () => { st.job = 0; if (!st.el.isConnected || document.hidden) return; render(); st.job = setTimeout(loop, FRAME_MS); }; st.job = setTimeout(loop, FRAME_MS); }
  function stop() { if (st && st.job) { clearTimeout(st.job); st.job = 0; } }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && st && st.el.isConnected) start(); });
  return { place, stop, Fire };
})();
