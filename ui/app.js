// 1.1 UI: drawn with the same primitives and coordinates as the 1.0.9 Tk canvas (core/ui/panel.py, intros.py)
// so the pages match pixel-closely. Icons are the 1.0.9 renders (ui/img/*@1 / @1.5).
const invoke = (c, a) => window.__TAURI__.core.invoke(c, a);
const $ = (id) => document.getElementById(id);
const C = { bg: "#121212", card: "#1f1f1f", tx: "#f2f2f2", mu: "#9a9a9a", off: "#3a3a3a", line: "#2a2a2a", ib: "#2a2a2a",
            idle: "#8a8a8a", red: "#e5484d", acc: "#1DB954", dis: "#555555", org: "#f0a030" };
const ROMAN = ["I", "II", "III", "IV"];
const G0 = "#1DB954", GREY_ACC = "#6e6e6e", CORAL = "#e5675f", CORAL_TX = "#f0d6d4";
const ACC_SPRITES = new Set(["fade", "plicon", "crown", "flag", "icrown", "power"]);   // single-colour icons: drawn as masks in the current accent
// 1.0.9 icons with a fixed colour, drawn as masks (transparent, so hover plates and brightening never show a box)
const MASK_COL = { chevr16: "#9a9a9a", chevr12: "#9a9a9a", chevdown: "#9a9a9a", chevup: "#9a9a9a", ichev: "#9a9a9a", pchev: "#9a9a9a", gear: "#f2f2f2", undo_mu: "#9a9a9a", undo_dis: "#555555", m_gh: "#f2f2f2", m_rep: "#f2f2f2" };
const DPR = () => window.devicePixelRatio || 1;
const fpx = (sz) => Math.floor(sz * DPR()) / DPR();          // Tk: font size -int(sz * S) device px
let host = null;
function el(tag, cls, css) { const e = document.createElement(tag); if (cls) e.className = cls; Object.assign(e.style, css || {}); host.appendChild(e); return e; }
function rr(x0, y0, x1, y1, r, fill, outline, tag) {
  return el("div", "a" + (tag ? " hit" : ""), { left: x0 + "px", top: y0 + "px", width: (x1 - x0) + "px", height: (y1 - y0) + "px",
    borderRadius: Math.min(r, (x1 - x0) / 2, (y1 - y0) / 2) + "px", background: fill || "transparent", border: outline ? "1px solid " + outline : "none" });
}
function oval(x0, y0, x1, y1, fill, outline, w) { const e = rr(x0, y0, x1, y1, 999, fill, null); if (outline) e.style.border = (w || 1) + "px solid " + outline; return e; }
const MC = document.createElement("canvas").getContext("2d");
function measure(s, sz, b) { MC.font = `${b ? 700 : 400} ${fpx(sz)}px "Segoe UI"`; return MC.measureText(s).width; }
function text(x, y, s, sz, c, b, anchor) {
  const e = el("div", "t", { font: `${b ? 700 : 400} ${fpx(sz)}px "Segoe UI"`, color: c || C.tx });
  // Text rows match 1.0.9 (Tk/GDI): Tk baseline = y - floor((A+D)/2) + A with A/D = ceil of Segoe UI ascent/descent;
  // a DirectWrite line box of the rounded linespace, nudged by whole device px to land on the same baseline row.
  const k = DPR(), fd = Math.floor(sz * k), yd = y * k;
  const Ar = Math.round(fd * 2210 / 2048), Dr = Math.round(fd * 514 / 2048), top = Math.floor(yd - (Ar + Dr) / 2);
  const A = Math.ceil(fd * 2210 / 2048), D = Math.ceil(fd * 514 / 2048);
  const bTk = Math.floor(yd - Math.floor((A + D) / 2)) + A, bDw = Math.round(top + (Ar + Dr - fd * 2724 / 2048) / 2 + fd * 2210 / 2048);
  e.textContent = s; e.style.lineHeight = ((Ar + Dr) / k) + "px"; e.style.top = ((top + bTk - bDw) / k) + "px";
  if (anchor === "e") { e.style.right = (host._w - x) + "px"; } else if (anchor === "center") { e.style.left = x + "px"; e.style.transform = "translateX(-50%)"; } else e.style.left = x + "px";
  return e;
}
function sprite(name, x0, y0, x1, y1, col) {
  if (ACC_SPRITES.has(name) || name in MASK_COL || name.startsWith("am_") || name.startsWith("pk_")) {
    if (name in MASK_COL && !col) col = MASK_COL[name];
    const m = `image-set(url(img/mk_${name}@1.png) 1x, url(img/mk_${name}@1.5.png) 1.5x)`;
    return el("div", "a", { left: x0 + "px", top: y0 + "px", width: (x1 - x0) + "px", height: (y1 - y0) + "px", background: col || C.acc,
      webkitMaskImage: m, webkitMaskSize: "100% 100%", pointerEvents: "none" });
  }
  const e = el("img", "a", { left: x0 + "px", top: y0 + "px", width: (x1 - x0) + "px", height: (y1 - y0) + "px" });
  e.srcset = `img/${name}@1.png 1x, img/${name}@1.5.png 1.5x`; e.src = `img/${name}@1.png`; e.draggable = false;
  return e;
}
const covers = {};
function coverImg(uri, x0, y0, sz, r) {
  if (!uri) return null;
  if (!(uri in covers)) { covers[uri] = null; invoke("cover", { uri }).then((d) => { if (d) { covers[uri] = d; redraw(); } }); }
  if (!covers[uri]) return null;
  const e = el("img", "a", { left: x0 + "px", top: y0 + "px", width: sz + "px", height: sz + "px", borderRadius: r + "px", pointerEvents: "none" });
  e.src = covers[uri]; return e;
}
function chip(key, col, cx, cy, r) {   // 1.0.9 Art.chip: ring-colour disc (2r+4) with the round portrait 2px inside
  const D = 2 * r + 4, e = el("div", "chip", { left: (cx - D / 2) + "px", top: (cy - D / 2) + "px", width: D + "px", height: D + "px", background: col });
  const i = document.createElement("img"); i.src = `img/portraits/${key}.jpg`; i.style.width = i.style.height = (D - 4) + "px"; e.appendChild(i); return e;
}
function hov(e, on, off) { e._hov = true; e.addEventListener("mouseenter", on); e.addEventListener("mouseleave", off); return e; }
function toggle(x, y, on, w = 44, h = 24, col, disabled) {
  const t = rr(x, y, x + w, y + h, h / 2, disabled ? "#2e2e2e" : on ? (col || C.acc) : C.off, null, true);
  const cx = on ? x + w - h / 2 : x + h / 2; oval(cx - h / 2 + 3, y + 3, cx + h / 2 - 3, y + h - 3, disabled ? "#6a6a6a" : "#fff");
  return t;
}
function hline(x0, y, x1, c) { el("div", "a", { left: x0 + "px", top: y + "px", width: (x1 - x0) + "px", height: "1px", background: c }); }
function begin(id, w, h) { host = $(id); if (!host._mo) { const hh = host; let q = 0; hh._mo = new MutationObserver(() => { if (!q) q = requestAnimationFrame(() => { q = 0; clickables(hh); }); }); hh._mo.observe(hh, { childList: true }); } host.innerHTML = ""; host._w = w; host.style.width = w + "px"; host.style.height = h + "px"; }
// Every clickable gets the hand cursor AND a hover highlight (1.0.9 used hand2 on all tagged items):
// decorations drawn on top of a clickable (labels, dots, icons, inner pills) let the pointer through to it, and
// clickables without their own hover get a subtle light overlay.
function clickables(h) {
  const kids = [...h.children], hits = kids.filter((e) => e.classList.contains("hit")).map((e) => [e, e.getBoundingClientRect()]), hr = h.getBoundingClientRect();
  for (const e of kids) { if (e.classList.contains("hit") || e._tip || e.title) continue; const r = e.getBoundingClientRect(); if (!r.width) continue;
    const own = hits.filter(([, b]) => r.left >= b.left - 1 && r.right <= b.right + 1 && r.top >= b.top - 1 && r.bottom <= b.bottom + 1);
    if (own.length) { e.style.pointerEvents = "none"; own.forEach(([he]) => (he._deco = he._deco || []).push(e)); } }
  for (const [e, b] of hits) { if (e._hov || e._hl || (e.style.cursor && e.style.cursor !== "pointer") || b.width * b.height > hr.width * hr.height * 0.4) continue;
    // never cover the glyph: the hit's own fill gets a light tint only when it is an opaque plate (it sits beneath its
    // content); icons/labels inside are brightened, whether drawn above or below a transparent hit overlay.
    e._hl = true; const plate = getComputedStyle(e).backgroundColor !== "rgba(0, 0, 0, 0)";
    const on = (v) => { if (plate) e.classList.toggle("hl", v); (e._deco || []).forEach((d) => d.classList.toggle("hld", v)); };
    e.addEventListener("mouseenter", () => on(true)); e.addEventListener("mouseleave", () => on(false)); }
}
// 1.0.9 chev_right: open ">" of two 1.6px strokes, ~sz/2.4 tall, centred at (cx, cy)
function chevR(cx, cy, col, sz) { const s = sz / 2.6; const e = el("div", "a", { left: (cx - s * 0.75) + "px", top: (cy - s / 2) + "px", width: s + "px", height: s + "px",
  borderTop: "1.6px solid " + col, borderRight: "1.6px solid " + col, transform: "rotate(45deg)", pointerEvents: "none" }); return e; }
function hit(e, fn) { e.classList.add("hit"); e.onclick = fn; return e; }

function revert(rx, y, isDef, fn) {   // 1.0.9 undo button: outlined pill, greyed when already default
  const b = rr(rx, y, rx + 30, y + 24, 12, C.card, isDef ? C.dis : C.mu); const g = sprite("undo_" + (isDef ? "dis" : "mu"), rx + 5, y + 2, rx + 25, y + 22); g.style.pointerEvents = "none";
  tipOn(b, ["rev", rx, y], isDef ? "Revert (already default)" : "Revert", [rx, y, rx + 30, y + 24]);
  if (!isDef) { b.classList.add("hit"); if (fn) b.onclick = (e) => { e.stopPropagation(); fn(); }; hov(b, () => { b.style.background = "#2e2e2e"; b.style.borderColor = C.tx; g.style.background = C.tx; }, () => { b.style.background = C.card; b.style.borderColor = C.mu; g.style.background = C.mu; }); }
  else b.style.cursor = "default";
  return b;
}
// ---------- main panel (panel.py draw) ----------
const W = 430, M = 16, R_ = W - M;
const ui = { open: true, am: false, menu: false, pmenu: false, dialog: null }; const upd = { msg: "", err: false };
function pill(msg, err, keep) { Object.assign(upd, { msg, err }); redraw(); if (!keep) setTimeout(() => { if (upd.msg === msg) { upd.msg = ""; redraw(); } }, 2000); }
const closeMenu = () => { ui.menu = false; redraw(); };
const PL_TOP = 172 + 46 + 10;
const AM_ROWS = [["resume", "Resume"], ["playlist", "Playlist"], ["stop", "Stop"]];
const AM_H = 46 + 6 + 40 + 26 + AM_ROWS.length * 42 + 8;
function mainH(n) { const PL_H = 36 + 6 + n * 46 + 4; const base = PL_TOP + (ui.open ? PL_H : 36) + 10; return base + 56 + (ui.am ? AM_H : 46) + M; }
const FX0 = M + 94, FX1 = W - M - 12 - 30 - 62;                     // fade slider track (leaves room for value + revert)
function mix(a, b, t) { const h = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16)); const A = h(a), B = h(b); return "#" + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join(""); }
const pwrT = (a) => { a = ((a % 360) + 360) % 360; return 1 - Math.abs(a - 180) / 180; };
const EN = { a: null, raf: 0, el: null, tx: null };                   // power icon spin (1.0.9 anim_enabled)
function pwrPaint(a) { if (!EN.el) return; const t = pwrT(a); EN.el.style.background = mix(G0, CORAL, t); EN.el.style.transform = `rotate(${a}deg)`; if (EN.tx) EN.tx.style.color = mix(C.tx, CORAL_TX, t); }
function animEnabled(toOff) {   // forward-only spin to the next upright (on) / upside-down (off) spot, ease-in-out cubic, 0.45 s per half turn
  cancelAnimationFrame(EN.raf); const a0 = EN.a != null ? EN.a : (toOff ? 0 : 180), goal = toOff ? 180 : 0;
  let b = a0 + (((goal - a0) % 360 + 360) % 360 || 360); if (EN.a != null && ((goal - a0) % 360 + 360) % 360 === 0) b = a0;
  const dur = 450 * Math.max(0.35, (b - a0) / 180), t0 = performance.now();
  const step = () => { const u = Math.min(1, (performance.now() - t0) / dur), e = u < 0.5 ? 4 * u ** 3 : 1 - (-2 * u + 2) ** 3 / 2; const a = a0 + (b - a0) * e; EN.a = a; pwrPaint(a);
    if (u < 1) EN.raf = requestAnimationFrame(step); else { EN.a = null; } };
  step();
}
function setUser(k, v) { S.settings = S.settings; return invoke("set_user", { k, v }).then(() => tickNow()); }
const amCfg = (set) => { const a = (set.after_match && typeof set.after_match === "object") ? set.after_match : {};
  const ok = (v) => typeof v === "string" && /^(spotify:(playlist|track):[A-Za-z0-9]{22}|aoe4s:list:[A-Za-z0-9]+)$/.test(v) ? v : "";
  const pl = ok(a.playlist); return { mode: ["resume", "playlist", "stop"].includes(a.mode) ? a.mode : ("mode" in a ? "stop" : "resume"), wl: typeof a.winloss_on === "boolean" ? a.winloss_on : a.mode === "winloss",
    playlist: pl.startsWith("spotify:track:") ? "" : pl, win: ok(a.win), loss: ok(a.loss) }; };
function amSet(fn) { const a = Object.assign({}, (S.settings.after_match && typeof S.settings.after_match === "object") ? S.settings.after_match : {}); fn(a); S.settings.after_match = a; redraw(); setUser("after_match", a); }
function plName(set, uri) { if (!uri) return ""; if (uri.startsWith("aoe4s:list:")) { if (uri.endsWith(":liked")) return "Liked Songs"; const l = ((S.user || {}).custom_lists || {})[uri.split(":").pop()]; return (l && l.name) || "My list"; }
  return set.playlist_names[uri.split(":").pop()] || (uri.startsWith("spotify:track:") ? "Song" : "Playlist"); }
const trunc = (t, n) => t.length <= n ? t : t.slice(0, n - 1) + "\u2026";
function pick(target, title, tracks, current) { invoke("open_pick", { target, title, tracks, current: current || "" }); }
function drawMain(s) {
  const set = s.settings, st = s.status, sp = s.spotify, n = s.ages.length, H = mainH(n); S.user = s.user || S.user;
  begin("main", W, H);
  sprite("logo", M, 14, M + 32, 46);
  text(M + 44, 30, "AoE4 Spotify", 19, C.tx, true);
  let px = M + 44 + measure("AoE4 Spotify", 19, true) + 8;
  rr(px, 21, px + 44, 39, 9, C.card); text(px + 22, 30, "v1.1", 10, C.mu, false, "center"); px += 52;
  const u = s.upd || {}, ph = u.phase || "idle", info = u.info;      // 1.0.9 update pill: Update x / Downloading n% / Installing / error / done
  let lab = upd.msg, err = upd.err;
  if (!lab && ph !== "idle" && !(ph === "done" && doneGone())) { lab = { avail: "\u2193 Update " + ((info || {}).version || ""), dl: `Downloading ${u.pct || 0}%`, run: "Installing\u2026", error: u.msg || "Update failed", done: u.msg || "" }[ph] || ""; err = ph === "error"; }
  if (lab) { const col = err ? C.red : G0, pw = measure(lab, 10, true) + 20;
    const p = rr(px, 21, px + pw, 39, 9, err ? "#3d1a1a" : "#183d26", col); text(px + pw / 2, 30, lab, 10, col, true, "center");
    if (!upd.msg && (ph === "avail" || ph === "error") && info) { p.classList.add("hit"); p.onclick = () => { S.upd = { phase: "dl", pct: 0, info }; invoke("start_update"); redraw(); };
      hov(p, () => p.style.background = err ? "#552424" : "#225234", () => p.style.background = err ? "#3d1a1a" : "#183d26"); } }
  const gx = R_ - 32; const gb = hit(rr(gx, 14, R_, 46, 10, "#2a2a2a"), () => { ui.menu = !ui.menu; redraw(); }); sprite("gear", gx + 6, 20, gx + 26, 40, ui.menu ? G0 : null).style.pointerEvents = "none";
  hov(gb, () => gb.style.background = "#333333", () => gb.style.background = "#2a2a2a");
  if (info && (ph === "avail" || ph === "error")) oval(R_ - 8, 10, R_ + 2, 20, G0, C.bg, 2).style.pointerEvents = "none";
  hline(M, 62, R_, C.line);
  // Enabled
  const en = !!set.enabled; C.acc = en ? G0 : GREY_ACC;
  let card;
  if (en) card = rr(M, 72, R_, 120, 12, C.card);
  else { card = rr(M, 72, R_, 120, 12, "#2a1c1c", "#5a3330"); card.style.boxShadow = "0 0 9px 1px rgba(229,103,95,0.27)"; }   // 1.0.9 red tint + soft glow
  const pa = EN.a != null ? EN.a : (en ? 0 : 180);
  const pw = sprite("power", M + 10, 82, M + 38, 110, G0); pw.style.transformOrigin = "50% 54%"; EN.el = pw;
  EN.tx = text(M + 50, 96, en ? "Enabled" : "Disabled", 16, C.tx, true); pwrPaint(pa);
  const etg = toggle(R_ - 12 - 52, 96 - 14, en, 52, 28); etg.onclick = () => { const on = !en; S.settings.enabled = on; animEnabled(!on); redraw(); invoke("set_enabled", { on }).then(() => tickNow()); };
  tipOn(card, ["encard"], en ? "Runs automatically when you launch Age of Empires IV from Steam and mutes the game's own music. You don't need this window open." : "Off: music won't switch when you play, and the game's music is back on.", [M, 72, R_, 120]);
  // Spotify / Game chips
  const cw = (W - 2 * M - 10) / 2; let x = M;
  const sc = hit(rr(x, 130, x + cw, 162, 16, "#242424", "#3a3a3a"), () => invoke("login"));   // 1.0.9: click always (re)logs in
  sc.title = sp.logged_in ? "Log in again" : "Log in to Spotify";
  oval(x + 14, 141, x + 24, 151, sp.logged_in ? C.acc : (sp.busy ? C.idle : C.org)); text(x + 32, 145, "Spotify", 12, C.mu);   // 145: caps optically on the row centre (approved)
  if (sp.logged_in) { text(x + cw - 26, 146, "Connected", 12, C.acc, true, "e"); sprite("chevr12", x + cw - 22, 140, x + cw - 10, 152); }
  else if (sp.busy) text(x + cw - 14, 146, "...", 12, C.mu, true, "e");
  else { const lp = rr(x + cw - 86, 136, x + cw - 8, 156, 10, "#4a3216", C.org); text(x + cw - 52, 145, "Log in", 11, C.org, true, "center"); chevR(x + cw - 22, 146, C.org, 18.6); sc._pill = lp; }   // chevron ~9px tall like 1.0.9
  hov(sc, () => { sc.style.background = "#323232"; sc.style.borderColor = "#5a5a5a"; if (sc._pill) sc._pill.style.background = "#6e4a1c"; },
          () => { sc.style.background = "#242424"; sc.style.borderColor = "#3a3a3a"; if (sc._pill) sc._pill.style.background = "#4a3216"; });
  x = M + cw + 10; const gv = st.in_match, gc = gv ? C.acc : C.idle;
  rr(x, 130, x + cw, 162, 16, C.card); oval(x + 14, 141, x + 24, 151, gc); text(x + 32, 146, "Game", 12, C.mu);
  text(x + cw - 14, 146, gv ? "Running" : "Not running", 12, gc, true, "e");
  // Fade
  let y = 172; const fv = drag.v != null ? drag.v : set.fade_seconds, fcol = fv ? C.acc : GREY_ACC;
  rr(M, y, R_, y + 46, 10, C.card); sprite("fade", M + 12, y + 11, M + 36, y + 35, fcol); text(M + 46, y + 23, "Fade", 13, C.tx, true);
  const xv = FX0 + (FX1 - FX0) * fv / 5;
  rr(FX0, y + 20, FX1, y + 26, 3, C.off).style.pointerEvents = "none"; rr(FX0, y + 20, Math.max(xv, FX0 + 6), y + 26, 3, fcol).style.pointerEvents = "none";
  const knob = oval(xv - 9, y + 14, xv + 9, y + 32, "#fff", fcol, 2); knob.style.pointerEvents = "none";
  const ft = rr(FX0 - 9, y + 12, FX1 + 9, y + 34, 0, "transparent"); ft.classList.add("hit"); ft._hl = true; ft.onmousedown = (e) => { drag.on = true; slide(e); e.preventDefault(); };
  hov(ft, () => knob.style.boxShadow = "0 0 0 4px rgba(255,255,255,.10)", () => knob.style.boxShadow = "none");
  text(R_ - 12 - 30 - 10, y + 23, fv ? fv.toFixed(1) + "s" : "Off", 12, fcol, true, "e");
  revert(R_ - 12 - 30, y + 11, Math.abs(fv - (set.default_fade ?? 2)) < 1e-6, () => { S.settings.fade_seconds = set.default_fade ?? 2; redraw(); setUser("fade_seconds", null); });
  // Playlists
  const PL_H = 36 + 6 + n * 46 + 4;
  if (ui.open) { rr(M, PL_TOP, R_, PL_TOP + PL_H, 10, C.card); hline(M + 12, PL_TOP + 36, R_ - 12, C.line); }
  const plh = hit(rr(M, PL_TOP, R_, PL_TOP + 36, 10, C.card), () => { ui.open = !ui.open; ui.am = false; redraw(true); });
  sprite("plicon", M + 12, PL_TOP + 6, M + 36, PL_TOP + 30).style.pointerEvents = "none";
  text(M + 46, PL_TOP + 18, "Playlists", 13, C.tx, true).style.pointerEvents = "none";
  sprite(ui.open ? "chevup" : "chevdown", R_ - 28, PL_TOP + 8, R_ - 8, PL_TOP + 28).style.pointerEvents = "none";
  const X = M + 22, XR = R_ - 22;
  if (ui.open) s.ages.forEach(([k, lab], i) => {
    const yy = PL_TOP + 42 + i * 46, uri = set.playlists[k] || "", id = uri.split(":").pop(), rx = XR - 6 - 30, isDef = uri === (set.default_playlists[k] || "");
    if (i < n - 1) hline(X + 48, yy + 44, XR, "#2a2a2a");
    const row = rr(X - 6, yy, XR + 6, yy + 42, 9, "transparent");
    if (st.in_match && st.playing && st.age === k) FIRE.place(host, X - 6, yy, XR + 6, yy + 42, 9);   // 1.0.9 glow pool fire, under the row's text
    if (!coverImg(uri, X + 9, yy + 6, 30, 6)) { rr(X + 9, yy + 6, X + 39, yy + 36, 6, C.ib).style.pointerEvents = "none"; }
    const zone = rr(X + 38, yy + 7, rx - 76, yy + 35, 8, "transparent");            // name zone: open in Spotify (1.0.9 opn%d)
    text(X + 48, yy + 21, lab.replace(" Age", ""), 13, C.tx, true);
    const nm = trunc(plName(set, uri) || (uri ? "Playlist" : "Not set"), 15);
    oval(X + 118, yy + 17, X + 126, yy + 25, uri ? C.acc : C.idle).style.pointerEvents = "none"; text(X + 132, yy + 21, nm, 12, C.mu);
    if (id && uri) { const custom = uri.startsWith("aoe4s:list:"); hit(zone, () => custom ? pick("age:" + k, lab, false, uri) : invoke("menu", { kind: "pl:" + id })); zone._hl = true; tipOn(zone, ["opn", i], custom ? "Edit list" : "Open in Spotify", [X + 38, yy + 7, rx - 76, yy + 35]); }
    const hb = en ? "#1ed760" : "#8a8a8a", hf = en ? "#1f3b29" : "#2a2a2a";
    const chg = hit(rr(rx - 70, yy + 9, rx - 8, yy + 33, 12, C.card, C.acc), () => pick("age:" + k, lab, false, uri)); const ct = text(rx - 39, yy + 21, "Change", 10, C.acc, true, "center");
    chg.style.visibility = ct.style.visibility = "hidden"; chg._hov = true;            // hover-only, its space always reserved
    const show = (v) => { row.style.background = v ? "#262626" : "transparent"; chg.style.visibility = ct.style.visibility = v ? "visible" : "hidden"; };
    [row, zone, chg].forEach((e) => { e.addEventListener("mouseenter", () => show(true)); e.addEventListener("mouseleave", (ev) => { if (![row, zone, chg, ...(e._deco || [])].includes(ev.relatedTarget)) show(false); }); });
    chg.addEventListener("mouseenter", () => { chg.style.background = hf; chg.style.borderColor = hb; ct.style.color = hb; }); chg.addEventListener("mouseleave", () => { chg.style.background = C.card; chg.style.borderColor = C.acc; ct.style.color = C.acc; });
    const rv = revert(rx, yy + 9, isDef, () => { const pl = Object.assign({}, S.settings.playlists); delete pl[k]; const up = Object.fromEntries(Object.entries(set.playlists).filter(([a]) => a !== k && (set.playlists[a] || "") !== (set.default_playlists[a] || "")));
      S.settings.playlists[k] = set.default_playlists[k] || ""; redraw(); setUser("playlists", up); });
    rv.addEventListener("mouseenter", () => show(true));
  });
  // Age Intros
  const base = PL_TOP + (ui.open ? PL_H : 36) + 10; y = base;
  const ic = hit(rr(M, y, R_, y + 46, 10, C.card), () => go("intros"));
  hov(ic, () => ic.style.background = "#262626", () => ic.style.background = C.card); tipOn(ic, ["intro"], "Intro song per age and civ", [M, y, R_, y + 46]);
  sprite("crown", M + 12, y + 11, M + 36, y + 35, set.enabled && set.boss_on ? G0 : GREY_ACC).style.pointerEvents = "none";   // crown_color: green only when intros AND app are on
  text(M + 46, y + 23, "Age Intros", 13, C.tx, true).style.pointerEvents = "none";
  const sx = M + 46 + measure("Age Intros", 13, true) + 14;
  s.ages.forEach(([k], j) => { const lit = s.intros[k].on && set.boss_on; const p = sx + 11 + j * 25;
    oval(p - 10, y + 13, p + 10, y + 33, lit ? C.acc : "#2a2a2a", lit ? null : "#3a3a3a").style.pointerEvents = "none";
    text(p, y + 23, ROMAN[j], 9, lit ? "#121212" : C.mu, true, "center").style.pointerEvents = "none"; });
  const btg = toggle(R_ - 30 - 44, y + 11, set.boss_on); btg.onclick = (e) => { e.stopPropagation(); const on = !set.boss_on; S.settings.boss_on = on; redraw(); setUser("boss_intro_enabled", on); };
  sprite("chevr16", R_ - 23, y + 15, R_ - 7, y + 31).style.pointerEvents = "none";
  // After match: expandable radio list (what the music does when a match ends)
  y = base + 56; const am = amCfg(set), mode = am.mode, aopen = ui.am;
  if (aopen) rr(M, y, R_, y + AM_H, 10, C.card);
  const amh = hit(rr(M, y, R_, y + 46, 10, C.card), () => { ui.am = !ui.am; ui.open = false; redraw(true); });
  sprite("am_flag", M + 13, y + 12, M + 35, y + 34, C.acc).style.pointerEvents = "none";
  text(M + 46, y + 23, "After match", 13, C.tx, true); sprite(aopen ? "chevup" : "chevdown", R_ - 28, y + 13, R_ - 8, y + 33).style.pointerEvents = "none";
  const suri = mode === "playlist" ? am.playlist : "";
  const hl = suri ? trunc(plName(set, suri), 14) : Object.fromEntries(AM_ROWS)[mode];
  text(R_ - 36, y + 23, hl, 12, C.acc, true, "e");
  let hx = R_ - 36 - measure(hl, 12, true) - 8; if (suri) { if (coverImg(suri, hx - 22, y + 12, 22, 5)) hx -= 22 + 8; }
  if (am.wl) { sprite("am_then", hx - 19, y + 12, hx + 3, y + 34, C.mu); sprite("am_trophy", hx - 41, y + 12, hx - 19, y + 34, "#e0b040"); }
  if (aopen) {
    hline(M + 12, y + 46, R_ - 12, C.line);
    const XL = M + 22, XR2 = R_ - 22, CC = XR2 - 72, wl = am.wl, wy = y + 52 + 20, wbg = wl ? "#232a25" : C.card;
    const wrow = hit(rr(XL - 6, wy - 20, XR2 + 6, wy + 20, 9, wbg), () => amSet((a) => { a.winloss_on = !wl; if (a.mode === "winloss") a.mode = "stop"; }));
    hov(wrow, () => wrow.style.background = wl ? "#28322b" : "#262626", () => wrow.style.background = wbg);
    sprite("am_trophy", XL - 3, wy - 11, XL + 19, wy + 11, wl ? C.acc : C.mu).style.pointerEvents = "none";
    text(XL + 28, wy, "Win / Loss", 12, wl ? C.tx : C.mu, true);
    if (wl) {
      sprite("am_trophy", CC - 87, wy - 11, CC - 65, wy + 11, "#e0b040").style.pointerEvents = "none"; amSlot(CC - 50, wy, am.win, "win", "Victory", "Victory: click to pick a song / playlist");
      sprite("am_skull", CC - 35, wy - 11, CC - 13, wy + 11, C.red).style.pointerEvents = "none"; amSlot(CC, wy, am.loss, "loss", "Defeat", "Defeat: click to pick a song / playlist");
    }
    const wt = toggle(XR2 - 44, wy - 12, wl); wt.onclick = (e) => { e.stopPropagation(); amSet((a) => { a.winloss_on = !wl; if (a.mode === "winloss") a.mode = "stop"; }); };
    const ty = wy + 20 + 13; text(XL + 48, ty, "Then", 10.5, C.mu, true);
    const lx = XL + 48 + measure("Then", 10.5, true) + 10; hline(lx, ty, XR2, C.line);
    AM_ROWS.forEach(([k, lab], i) => {
      const ry = ty + 13 + i * 42 + 21, on = k === mode, bgc = on ? "#262a27" : C.card;
      if (i < AM_ROWS.length - 1 && !on && AM_ROWS[i + 1][0] !== mode) hline(XL + 54, ry + 21, XR2, "#2a2a2a");
      const r = hit(rr(XL - 6, ry - 19, XR2 + 6, ry + 19, 9, bgc), () => { amSet((a) => { a.mode = k; }); if (k === "playlist" && !am.playlist) pick("am:playlist", "After match playlist", false, ""); });
      hov(r, () => r.style.background = on ? "#2b302c" : "#262626", () => r.style.background = bgc);
      const rad = oval(XL + 1, ry - 7, XL + 15, ry + 7, "transparent", on ? C.acc : "#5a5a5a", 1.6); rad.style.pointerEvents = "none";
      if (on) oval(XL + 4.5, ry - 3.5, XL + 11.5, ry + 3.5, C.acc).style.pointerEvents = "none";
      sprite("am_" + k, XL + 23, ry - 11, XL + 45, ry + 11, on ? C.acc : C.mu).style.pointerEvents = "none";
      text(XL + 54, ry, lab, 12, on ? C.tx : C.mu, on);
      if (k === "resume") text(XR2, ry, "Pre-match", 11, C.mu, false, "e");
      else if (k === "playlist") {
        const pz = hit(rr(CC - 14, ry - 15, XR2 + 4, ry + 15, 8, "transparent"), (e) => { e.stopPropagation(); pick("am:playlist", "After match playlist", false, am.playlist); });
        pz._hl = true; tipOn(pz, ["amp"], "Pick a playlist", [CC - 14, ry - 15, XR2 + 4, ry + 15]);
        amSlotDraw(CC, ry, am.playlist); text(CC + 16, ry, am.playlist ? trunc(plName(set, am.playlist), 10) : "Pick", 11.5, on ? C.tx : C.mu, on);
        const cv_ = el("div", "a", { left: (XR2 - 2 - 7) + "px", top: (ry - 7) + "px", width: "14px", height: "14px", pointerEvents: "none" }); cv_.appendChild(chevSvg(C.mu, 14));
        pz.addEventListener("mouseenter", () => pz.style.background = "rgba(255,255,255,.06)"); pz.addEventListener("mouseleave", () => pz.style.background = "transparent"); pz._hov = true;
      }
    });
  }
  if (ui.menu) drawMenu(H, sp, set);
  return H;
}
function chevSvg(col, size) {   // 1.0.9 chev_right: '>' through (0.38,0.2) (0.64,0.5) (0.38,0.8), 2.2px round strokes
  const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg"); s.setAttribute("width", size); s.setAttribute("height", size); s.setAttribute("viewBox", `0 0 ${size} ${size}`);
  const p = document.createElementNS(ns, "polyline"); p.setAttribute("points", `${size * .38},${size * .2} ${size * .64},${size * .5} ${size * .38},${size * .8}`);
  Object.entries({ fill: "none", stroke: col, "stroke-width": 2.2, "stroke-linecap": "round", "stroke-linejoin": "round" }).forEach(([k, v]) => p.setAttribute(k, v)); s.appendChild(p); return s;
}
function amSlotDraw(cx, cy, uri) {   // 24 px cover, or an empty '+' slot
  if (uri && coverImg(uri, cx - 12, cy - 12, 24, 5)) return;
  rr(cx - 12, cy - 12, cx + 12, cy + 12, 5, C.ib).style.pointerEvents = "none"; sprite("am_plus", cx - 11, cy - 11, cx + 11, cy + 11, C.mu).style.pointerEvents = "none";
}
function amSlot(cx, cy, uri, which, title, tipTxt) {
  amSlotDraw(cx, cy, uri);
  const h = hit(rr(cx - 13, cy - 13, cx + 13, cy + 13, 6, "transparent"), (e) => { e.stopPropagation(); pick("am:" + which, title, true, uri); });
  h._hl = true; tipOn(h, ["am", which], tipTxt, [cx - 13, cy - 13, cx + 13, cy + 13]);
  hov(h, () => h.style.boxShadow = "0 0 0 1.5px " + C.acc, () => h.style.boxShadow = "none");
}
const drag = { on: false, v: null };
function slide(e, save) {
  if (!drag.on) return; const hr = $("main").getBoundingClientRect();
  const v = Math.round(Math.max(0, Math.min(5, ((e.clientX - hr.left) - FX0) / (FX1 - FX0) * 5)) * 2) / 2;
  if (save) { drag.on = false; drag.v = null; S.settings.fade_seconds = v; redraw(); setUser("fade_seconds", v); }
  else if (v !== drag.v) { drag.v = v; redraw(); }
}
document.addEventListener("mousemove", (e) => { if (drag.on) slide(e); });
document.addEventListener("mouseup", (e) => { if (drag.on) slide(e, true); });
let doneT0 = 0; function doneGone() { if (!doneT0) doneT0 = performance.now(); return performance.now() - doneT0 > 6000; }
function drawMenu(H, sp, set) {
  hit(rr(0, 0, W, H, 0, "rgba(0,0,0,0.353)"), () => { ui.menu = false; redraw(); }).style.cursor = "default";
  const gx = R_ - 32; hit(rr(gx, 14, R_, 46, 10, "#2a2a2a"), closeMenu); sprite("gear", gx + 6, 20, gx + 26, 40, G0).style.pointerEvents = "none";   // green when open: 1.0.9 gear_img[True]
  const mx0 = R_ - 190; let my0 = 52; const XTRA = 32;                       // 1.1: one extra row (Your Spotify app)
  rr(mx0, my0, R_, my0 + 180 + 38 - 32 + XTRA, 10, "#262626", "#3a3a3a");
  const gw = measure("\u2630  ", 12);
  let rowN = 0; const item = (y0, h, fn) => { const r = hit(rr(mx0 + 6, y0, R_ - 6, y0 + h, 7, "#262626"), fn); hov(r, () => r.style.background = "#303030", () => r.style.background = "#262626"); r.dataset.row = rowN++; return r; };
  item(my0 + 6, 32, () => invoke("menu", { kind: "replays" }).then(() => tickNow()));          // stays open: you see it flip
  sprite("m_rep", mx0 + 20 + (gw - 8) / 2 - 9, my0 + 13, mx0 + 20 + (gw - 8) / 2 + 9, my0 + 31).style.pointerEvents = "none";
  text(mx0 + 20 + gw, my0 + 22, "Music in replays", 12, C.tx); toggle(R_ - 14 - 30, my0 + 22 - 8, sp.replays, 30, 16).style.pointerEvents = "none";
  hline(mx0 + 10, my0 + 41, R_ - 10, "#3a3a3a"); my0 += 38;
  item(my0 + 6, 32, () => { if (S.upd && ["dl", "run"].includes(S.upd.phase)) return closeMenu(); closeMenu(); pill("Checking\u2026", false, true); invoke("check_update").then((r) => { if (r.startsWith("\u2193")) { upd.msg = ""; tickNow(); } else pill(r, r.startsWith("Couldn")); }); }); text(mx0 + 20, my0 + 22, "\u21bb  Check for updates", 12, C.tx);
  item(my0 + 38, 32, () => { closeMenu(); invoke("menu", { kind: "log" }); }); text(mx0 + 20, my0 + 54, "\u2630  Open log", 12, C.tx);
  item(my0 + 70, 32, () => { closeMenu(); invoke("menu", { kind: "github" }); }); sprite("m_gh", mx0 + 20 + (gw - 8) / 2 - 9, my0 + 77, mx0 + 20 + (gw - 8) / 2 + 9, my0 + 95).style.pointerEvents = "none";
  text(mx0 + 20 + gw, my0 + 86, "GitHub", 12, C.tx);
  item(my0 + 102, 32, () => { closeMenu(); invoke("open_own"); }); text(mx0 + 20, my0 + 118, "\u266b  Your Spotify app", 12, C.tx); my0 += 32;
  const dy = -32 + XTRA - 32;   // (my0 already moved down one row for Your Spotify app)
  hline(mx0 + 10, my0 + 140 + dy, R_ - 10, "#3a3a3a");
  item(my0 + 144 + dy, 30, () => { closeMenu(); invoke("menu", { kind: "uninstall" }); }); text(mx0 + 20, my0 + 159 + dy, "\u2715  Uninstall", 12, C.red, true);
}

// ---------- Age Intros overview (intros.py draw_overview) ----------
const IW = 520, OV_TOP = 124, OV_STEP = 106, OV_CARD = 96, OV_FOOT = 48, HY = 40;
function introsH(n, mainh) { return Math.max(OV_TOP + n * OV_STEP - (OV_STEP - OV_CARD) + OV_FOOT, mainh); }
function drawIntros(s) {
  const n = s.ages.length, H = introsH(n, mainH(n)); begin("intros", IW, H);
  // 1.0.9: the back chevron stays and only its disc goes #1f1f1f -> #2a2a2a on hover. The sprite has the disc baked in
  // (opaque), so swap to the hover render (back_h) instead of hiding the sprite (which made the arrow vanish).
  const bk = hit(oval(18, 24, 50, 56, C.card), () => go("main")); const bs = sprite("back", 18, 24, 50, 56); bs.style.pointerEvents = "none";
  const bsrc = (n) => { bs.srcset = `img/${n}@1.png 1x, img/${n}@1.5.png 1.5x`; bs.src = `img/${n}@1.png`; };
  hov(bk, () => { bk.style.background = "#2a2a2a"; bsrc("back_h"); }, () => { bk.style.background = C.card; bsrc("back"); });
  sprite("icrown", 64, 28, 92, 52, S && S.settings.enabled && S.settings.boss_on ? G0 : GREY_ACC); text(102, HY, "Age Intros", 18, C.tx, true);
  // preset bar (intros.py draw_bar): current preset, menu, share, import
  const y = 84, u = s.ed || {}, menuOpen = ui.pmenu, pb = hit(rr(20, y - 18, IW - 140, y + 18, 18, menuOpen ? "#2a2a2a" : C.card, menuOpen ? C.acc : "#3e3e3e"), () => { ui.pmenu = !ui.pmenu; redraw(); });
  if (!menuOpen) hov(pb, () => pb.style.background = "#2a2a2a", () => pb.style.background = C.card);
  oval(34, y - 6, 46, y + 6, C.acc).style.pointerEvents = "none"; const nm = u.intro_preset || "Default";
  text(56, y, nm.length <= 30 ? nm : nm.slice(0, 29) + "\u2026", 13, C.tx, true); text(IW - 176, y, "Auto-saved", 10, C.mu, true, "e"); sprite("pchev", IW - 166, y - 6, IW - 154, y + 6).style.pointerEvents = "none";
  const sh = hit(oval(IW - 121, y - 15, IW - 91, y + 15, "transparent"), () => sharePreset()); sprite("share", IW - 121, y - 15, IW - 91, y + 15).style.pointerEvents = "none";
  const im = hit(oval(IW - 73, y - 15, IW - 43, y + 15, "transparent"), () => importDialog()); sprite("import", IW - 73, y - 15, IW - 43, y + 15).style.pointerEvents = "none";
  hov(sh, () => sh.style.background = "rgba(255,255,255,.07)", () => sh.style.background = "transparent"); hov(im, () => im.style.background = "rgba(255,255,255,.07)", () => im.style.background = "transparent");
  if (typeof tipOn === "function") { tipOn(sh, ["share"], "Share preset (copies a code)", [IW - 122, y - 16, IW - 90, y + 16]); tipOn(im, ["import"], "Import preset from code", [IW - 74, y - 16, IW - 42, y + 16]); }
  s.ages.forEach(([k, lab], i) => {
    const cy = OV_TOP + i * OV_STEP, o = s.intros[k], on = o.on, n = o.n;
    const card = rr(20, cy, IW - 20, cy + OV_CARD, 18, C.card); card.classList.add("hit"); card.onclick = () => openAge(k);
    let more = null;
    hov(card, () => { card.style.background = "#262626"; card.style.border = "1px solid #464646"; if (more) more.style.background = "#262626"; },
              () => { card.style.background = C.card; card.style.border = "none"; if (more) more.style.background = C.card; });
    oval(62 - 18, cy + 32 - 18, 62 + 18, cy + 32 + 18, on ? "#1e3c28" : "#2c2c2c").style.pointerEvents = "none";
    text(62, cy + 31, ROMAN[i], 18 * 0.62, on ? C.acc : C.mu, true, "center");
    text(100, cy + 22, lab.replace(" Age", ""), 17, C.tx, true);
    text(100, cy + 40, n ? `${n}/${o.civs} civs` : "Empty", 11, n && on ? C.acc : C.mu, true);
    toggle(IW - 66 - 44, cy + 32 - 12, on, 44, 24, null, !n);
    const tg = hit(rr(IW - 112, cy + 18, IW - 64, cy + 46, 0, "transparent"), (e) => { e.stopPropagation(); if (n) setAgeOn(k, !on); }); if (!n) { tg.style.cursor = "not-allowed"; tipOn(tg, ["swoff", k], "Add a song first", [IW - 78, cy + 20, IW - 54, cy + 44]); } sprite("ichev", IW - 51, cy + 21, IW - 29, cy + 43).style.pointerEvents = "none";
    rr(100, cy + 62, IW - 270, cy + 66, 3, "#323232").style.pointerEvents = "none";
    if (n) rr(100, cy + 62, 100 + Math.max(6, Math.floor((IW - 370) * n / o.civs)), cy + 66, 3, on ? C.acc : "#5a5a5a").style.pointerEvents = "none";
    if (o.chips.length) {
      o.chips.forEach(([key, col], j) => chip(key, col, IW - 225 + j * 24, cy + 64, 13));
      if (o.more > 0) { const ox = IW - 225 + o.chips.length * 24;
        more = oval(ox - 16.5, cy + 64 - 16.5, ox + 16.5, cy + 64 + 16.5, C.card); more.style.pointerEvents = "none";
        oval(ox - 15, cy + 49, ox + 15, cy + 79, "#2c2c2c", "#6e6e6e", 2.5).style.pointerEvents = "none";
        text(ox, cy + 64, "+" + o.more, 11, "#dcdcdc", true, "center"); }
    } else for (let j = 0; j < 3; j++) oval(IW - 240 + j * 24, cy + 48, IW - 210 + j * 24, cy + 78, C.card, "#464646").style.pointerEvents = "none";
  });
  if (age.toast) { const tw = measure(age.toast, 13, true) + 70, x0 = IW / 2 - tw / 2; rr(x0, H - 46, x0 + tw, H - 8, 19, "#282828", C.acc);
    oval(x0 + 14, H - 38, x0 + 36, H - 16, C.acc); text(x0 + 25, H - 27, "\u2713", 13, "#0a0a0a", true, "center"); text(x0 + 45, H - 27, age.toast, 13, C.tx, true); }
  else text(IW / 2, H - 20, "Click an age to edit", 10, "#5a5a5a", false, "center");
  if (ui.pmenu && s.agedata) drawPresetMenu(s);
  if (ui.dialog) ui.dialog(H);
  return H;
}

// ---------- window: fixed transparent borderless window; the drawn frame takes each page's 1.0.9 size,
// centred horizontally, caption fixed, extra height down. Page switches are a pure DOM change (one composited
// frame); the OS clip region is widened before / narrowed after, so no stale or blank pixels can show.
const SH = 16, WW = 522, TB = 30;
let S = null, page = "main", sizes = { main: [430, 586], intros: [520, 586] }, applied = null;
function frameRect(p) { const [w, h] = sizes[p]; const fw = w + 2, fh = h + TB + 2; return { x: SH + (WW - fw) / 2, y: SH, w: fw, h: fh }; }
function regionOf(r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; }   // exactly the drawn frame: everything else is click-through
function setFrame(p) {
  const r = frameRect(p), f = $("frame"); invoke("shadow", r); Object.assign(f.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
  $("client").style.height = sizes[p][1] + "px";
  const w = sizes[p][0]; $("tbmin").style.left = (w - 138) + "px"; $("tbmax").style.left = (w - 92) + "px"; $("tbclose").style.left = (w - 46) + "px";
  document.querySelectorAll(".page").forEach((e) => e.classList.toggle("on", e.id === p));
}
const frames = (n) => new Promise((res) => { const f = () => (n-- <= 0 ? res() : requestAnimationFrame(f)); requestAnimationFrame(f); });
async function apply(p) {
  const a = applied ? regionOf(frameRect(applied)) : null, b = regionOf(frameRect(p));
  if (a) { const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y); await invoke("region", { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y }); }
  setFrame(p); page = p; applied = p;
  await frames(3); await invoke("region", b);
}
function render(s) { S = s; const mh = drawMain(s), ih = drawIntros(s), ah = drawAge(s); sizes = { main: [W, mh], intros: [IW, ih], age: [IW, ah] }; }
async function redraw(geom) { if (!S) return; render(S); if (geom || (applied && frameRect(applied).h !== parseFloat($("frame").style.height))) await apply(page); }
async function go(p) { await apply(p); }
window.go = go;
document.addEventListener("keydown", (e) => { if (e.target && e.target.tagName === "INPUT") return;
  if (e.key === "Escape" && page === "main") { if (ui.menu) closeMenu(); else W_.close(); return; }
  if ((e.key === "Escape" || e.key === "Backspace") && page === "intros") go("main"); else if ((e.key === "Escape" || e.key === "Backspace") && page === "age") { go("intros"); age.k = null; } });
const W_ = window.__TAURI__.window.getCurrentWindow();
$("tbmin").onclick = () => W_.minimize(); $("tbclose").onclick = () => W_.close();
window.addEventListener("blur", () => document.body.classList.add("inactive")); window.addEventListener("focus", () => document.body.classList.remove("inactive"));
let lastJ = "";
async function tick() {
  try { const v0 = window.EDV || 0; const s = await invoke("get_state"); if ((window.EDV || 0) !== v0) { setTimeout(tick, 100); return; } const j = JSON.stringify([s.settings, s.spotify, s.status.in_match, s.status.age, s.status.watching, s.intros, s.upd, s.user]);
    if (j !== lastJ) { const first = !lastJ; lastJ = j; render(s); if (first) { await apply("main"); invoke("cfg").then((c) => { if (c.open) setTimeout(() => { const [pg, k, tr, hv, pl, x] = c.open.split(":"); if (tr) S.ed.intro_pack_open = tr === "octo"; if (pg === "age") openAge(k); else go(pg);
      setTimeout(() => { const d = S.agedata; if (hv) { age.hovTray = +hv; redraw(); } if (pl) { age.song = d.songs[+pl][0]; redraw(); } shotState(x); if (x === "dom") domDump(); }, 300); }, 300); if (c.addtest) setTimeout(addTest, 1500); if (c.edtest) setTimeout(() => edTest().catch((e) => invoke("dbg", { s: "ERROR " + e.stack })), 1500); if (c.menutest) setTimeout(() => menuTest().catch((e) => invoke("dbg", { s: "ERROR " + e + "\n" + (window.__mt || []).join("\n") })), 1500); }); } else await redraw(); } } catch (e) { console.error(e); }
  setTimeout(tick, 500);
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", tick); else tick();   // age.js (tipOn) loaded first
async function tickNow() { try { const s = await invoke("get_state"); lastJ = JSON.stringify([s.settings, s.spotify, s.status.in_match, s.status.age, s.status.watching, s.intros, s.upd, s.user]); if (!drag.on) { render(s); await redraw(); } } catch (e) { console.error(e); } }
window.addEventListener("focus", () => tickNow());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function menuTest() {   // AOE4S_MENUTEST: click every cog row like a user and record what happened
  const out = window.__mt = []; const row = (i) => document.querySelector(`#main [data-row="${i}"]`);
  const gear = () => [...document.querySelectorAll("#main .hit")].find((e) => e.style.top === "14px" && parseFloat(e.style.left) > 300);
  const st = async () => (await invoke("get_state")).spotify;
  gear().click(); await sleep(150); out.push("menu open: " + ui.menu + ", rows " + document.querySelectorAll("#main [data-row]").length);
  const r0 = (await st()).replays; row(0).click(); await sleep(300); out.push(`replays ${r0} -> ${(await st()).replays}, menu still open ${ui.menu}`);
  row(0).click(); await sleep(300); out.push(`replays back -> ${(await st()).replays}`);
  row(1).click(); out.push("check: pill " + JSON.stringify(upd.msg) + ", menu open " + ui.menu);
  for (let k = 0; k < 40 && upd.msg.startsWith("Checking"); k++) await sleep(250); out.push("check result pill " + JSON.stringify(upd.msg));
  await sleep(2300); out.push("pill after 2.3s " + JSON.stringify(upd.msg));
  for (const [i, n] of [[2, "log"], [3, "github"], [5, "uninstall"]]) {
    gear().click(); await sleep(150); const before = (await st()).real; row(i).click(); await sleep(300);
    out.push(`${n}: clicked, menu open ${ui.menu}` + (n === "real" ? `, real ${before} -> ${(await st()).real}` : ""));
    if (n === "real") { row(i).click(); await sleep(300); out.push("real back -> " + (await st()).real); if (ui.menu) gear().click(); await sleep(100); }
  }
  await invoke("dbg", { s: out.join("\n") }); await sleep(200); W_.close();
}
