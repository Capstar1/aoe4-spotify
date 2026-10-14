// 1.1 UI: drawn with the same primitives and coordinates as the 1.0.9 Tk canvas (core/ui/panel.py, intros.py)
// so the pages match pixel-closely. Icons are the 1.0.9 renders (ui/img/*@1 / @1.5).
const invoke = (c, a) => window.__TAURI__.core.invoke(c, a);
const $ = (id) => document.getElementById(id);
const C = { bg: "#121212", card: "#1f1f1f", tx: "#f2f2f2", mu: "#9a9a9a", off: "#3a3a3a", line: "#2a2a2a", ib: "#2a2a2a",
            idle: "#8a8a8a", red: "#e5484d", acc: "#1DB954", dis: "#555555", org: "#f0a030" };
const ROMAN = ["I", "II", "III", "IV"];
const G0 = "#1DB954", GREY_ACC = "#5a5a5a";
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
function sprite(name, x0, y0, x1, y1) {
  const e = el("img", "a", { left: x0 + "px", top: y0 + "px", width: (x1 - x0) + "px", height: (y1 - y0) + "px" });
  e.srcset = `img/${name}@1.png 1x, img/${name}@1.5.png 1.5x`; e.src = `img/${name}@1.png`; e.draggable = false; return e;
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
function hov(e, on, off) { e.addEventListener("mouseenter", on); e.addEventListener("mouseleave", off); return e; }
function toggle(x, y, on, w = 44, h = 24, col, disabled) {
  const t = rr(x, y, x + w, y + h, h / 2, disabled ? "#2e2e2e" : on ? (col || C.acc) : C.off, null, true);
  const cx = on ? x + w - h / 2 : x + h / 2; oval(cx - h / 2 + 3, y + 3, cx + h / 2 - 3, y + h - 3, disabled ? "#6a6a6a" : "#fff");
  return t;
}
function hline(x0, y, x1, c) { el("div", "a", { left: x0 + "px", top: y + "px", width: (x1 - x0) + "px", height: "1px", background: c }); }
function begin(id, w, h) { host = $(id); host.innerHTML = ""; host._w = w; host.style.width = w + "px"; host.style.height = h + "px"; }
function hit(e, fn) { e.classList.add("hit"); e.onclick = fn; return e; }

function revert(rx, y, isDef, tag) {   // 1.0.9 undo button: outlined pill, greyed when already default
  const b = rr(rx, y, rx + 30, y + 24, 12, C.card, isDef ? C.dis : C.mu); sprite("undo_" + (isDef ? "dis" : "mu"), rx + 5, y + 2, rx + 25, y + 22).style.pointerEvents = "none";
  b.title = isDef ? "Revert (already default)" : "Revert"; if (!isDef) { b.classList.add("hit"); hov(b, () => b.style.background = "#262626", () => b.style.background = C.card); }
  return b;
}
// ---------- main panel (panel.py draw) ----------
const W = 430, M = 16, R_ = W - M;
const ui = { open: true, menu: false };
const PL_TOP = 172 + 46 + 10;
function mainH(n) { const PL_H = 36 + 6 + n * 46 + 4; const base = PL_TOP + (ui.open ? PL_H : 36) + 10; return base + 56 + 46 + M; }
function drawMain(s) {
  const set = s.settings, st = s.status, sp = s.spotify, n = s.ages.length, H = mainH(n);
  begin("main", W, H);
  sprite("logo", M, 14, M + 32, 46);
  text(M + 44, 30, "AoE4 Spotify", 19, C.tx, true);
  let px = M + 44 + measure("AoE4 Spotify", 19, true) + 8;
  rr(px, 21, px + 44, 39, 9, C.card); text(px + 22, 30, "v1.1", 10, C.mu, false, "center");
  const gx = R_ - 32; hit(rr(gx, 14, R_, 46, 10, "#2a2a2a"), () => { ui.menu = !ui.menu; redraw(); }); sprite("gear", gx + 6, 20, gx + 26, 40).style.pointerEvents = "none";
  hline(M, 62, R_, C.line);
  // Enabled
  C.acc = set.enabled ? G0 : GREY_ACC;
  if (set.enabled) rr(M, 72, R_, 120, 12, C.card); else rr(M, 72, R_, 120, 12, "#2a1c1c", "#5a3330");
  sprite("power", M + 10, 82, M + 38, 110); if (!set.enabled) host.lastChild.style.filter = "grayscale(1) brightness(0.8)";
  text(M + 50, 96, set.enabled ? "Enabled" : "Disabled", 16, set.enabled ? C.tx : "#f08a80", true); toggle(R_ - 12 - 52, 96 - 14, set.enabled, 52, 28);
  // Spotify / Game chips
  const cw = (W - 2 * M - 10) / 2; let x = M;
  const sc = hit(rr(x, 130, x + cw, 162, 16, "#242424", "#3a3a3a"), () => invoke(sp.logged_in ? "logout" : "login"));
  sc.title = sp.logged_in ? "Log in again" : "Log in to Spotify";
  oval(x + 14, 141, x + 24, 151, sp.logged_in ? C.acc : (sp.busy ? C.idle : C.org)); text(x + 32, 146, "Spotify", 12, C.mu);
  if (sp.logged_in) { text(x + cw - 26, 146, "Connected", 12, C.acc, true, "e"); sprite("chevr12", x + cw - 22, 140, x + cw - 10, 152); }
  else if (sp.busy) text(x + cw - 14, 146, "...", 12, C.mu, true, "e");
  else { rr(x + cw - 86, 136, x + cw - 8, 156, 10, "#4a3216", C.org); text(x + cw - 52, 146, "Log in", 11, C.org, true, "center"); }
  x = M + cw + 10; const gv = st.in_match, gc = gv ? C.acc : C.idle;
  rr(x, 130, x + cw, 162, 16, C.card); oval(x + 14, 141, x + 24, 151, gc); text(x + 32, 146, "Game", 12, C.mu);
  text(x + cw - 14, 146, gv ? "Running" : "Not running", 12, gc, true, "e");
  // Fade
  let y = 172; const fv = set.fade_seconds, fcol = fv ? C.acc : "#5a5a5a";
  rr(M, y, R_, y + 46, 10, C.card); sprite("fade", M + 12, y + 11, M + 36, y + 35); text(M + 46, y + 23, "Fade", 13, C.tx, true);
  const x0 = M + 94, x1 = W - M - 12 - 30 - 62, xv = x0 + (x1 - x0) * fv / 5;
  rr(x0, y + 20, x1, y + 26, 3, C.off); rr(x0, y + 20, Math.max(xv, x0 + 6), y + 26, 3, fcol);
  oval(xv - 9, y + 14, xv + 9, y + 32, "#fff", fcol, 2);
  text(R_ - 12 - 30 - 10, y + 23, fv ? fv.toFixed(1) + "s" : "Off", 12, fcol, true, "e");
  revert(R_ - 12 - 30, y + 11, Math.abs(fv - (set.default_fade ?? 2)) < 1e-6, "revf");
  // Playlists
  const PL_H = 36 + 6 + n * 46 + 4;
  if (ui.open) { rr(M, PL_TOP, R_, PL_TOP + PL_H, 10, C.card); hline(M + 12, PL_TOP + 36, R_ - 12, C.line); }
  hit(rr(M, PL_TOP, R_, PL_TOP + 36, 10, C.card), () => { ui.open = !ui.open; redraw(true); });
  sprite("plicon", M + 12, PL_TOP + 6, M + 36, PL_TOP + 30).style.pointerEvents = "none";
  text(M + 46, PL_TOP + 18, "Playlists", 13, C.tx, true).style.pointerEvents = "none";
  sprite(ui.open ? "chevup" : "chevdown", R_ - 28, PL_TOP + 8, R_ - 8, PL_TOP + 28).style.pointerEvents = "none";
  const X = M + 22, XR = R_ - 22;
  if (ui.open) s.ages.forEach(([k, lab], i) => {
    const yy = PL_TOP + 42 + i * 46, uri = set.playlists[k] || "", id = uri.split(":").pop();
    if (i < n - 1) hline(X + 48, yy + 44, XR, "#2a2a2a");
    const row = rr(X - 6, yy, XR + 6, yy + 42, 9, "transparent"); row.onmouseenter = () => row.style.background = "#262626"; row.onmouseleave = () => row.style.background = "transparent";
    if (st.age === k) row.style.boxShadow = "inset 0 0 0 1px " + C.acc;
    if (!coverImg(uri, X + 9, yy + 6, 30, 6)) { rr(X + 9, yy + 6, X + 39, yy + 36, 6, C.ib); }
    text(X + 48, yy + 21, lab.replace(" Age", ""), 13, C.tx, true);
    const nm = set.playlist_names[id] || (uri.includes(":list:liked") ? "Liked Songs" : uri ? "Playlist" : "Not set");
    oval(X + 118, yy + 17, X + 126, yy + 25, uri ? C.acc : C.idle); text(X + 132, yy + 21, nm, 12, C.mu);
    revert(XR - 6 - 30, yy + 9, uri === (set.default_playlists[k] || ""), "rev" + i);
  });
  // Age Intros
  const base = PL_TOP + (ui.open ? PL_H : 36) + 10; y = base;
  hit(rr(M, y, R_, y + 46, 10, C.card), () => go("intros"));
  sprite("crown", M + 12, y + 11, M + 36, y + 35).style.pointerEvents = "none";
  text(M + 46, y + 23, "Age Intros", 13, C.tx, true).style.pointerEvents = "none";
  const sx = M + 46 + measure("Age Intros", 13, true) + 14;
  s.ages.forEach(([k], j) => { const lit = s.intros[k].on && set.boss_on; const p = sx + 11 + j * 25;
    oval(p - 10, y + 13, p + 10, y + 33, lit ? C.acc : "#2a2a2a", lit ? null : "#3a3a3a").style.pointerEvents = "none";
    text(p, y + 23, ROMAN[j], 9, lit ? "#121212" : C.mu, true, "center").style.pointerEvents = "none"; });
  toggle(R_ - 30 - 44, y + 11, set.boss_on);
  sprite("chevr16", R_ - 23, y + 15, R_ - 7, y + 31).style.pointerEvents = "none";
  // After match
  y = base + 56; rr(M, y, R_, y + 46, 10, C.card); sprite("flag", M + 12, y + 11, M + 36, y + 35);
  text(M + 46, y + 23, "After match", 13, C.tx, true); sprite("chevdown", R_ - 28, y + 13, R_ - 8, y + 33);
  const am = set.after_match || {}, mode = ["resume", "playlist", "stop"].includes(am.mode) ? am.mode : (am.mode ? "stop" : "resume");
  const suri = mode === "playlist" ? (am.playlist || "") : "";
  const trunc = (t, n) => t.length <= n ? t : t.slice(0, n - 1) + "\u2026";
  const lab = suri ? trunc(set.playlist_names[suri.split(":").pop()] || "Playlist", 14) : { resume: "Resume", playlist: "Playlist", stop: "Stop" }[mode];
  text(R_ - 36, y + 23, lab, 12, C.acc, true, "e");
  const hx = R_ - 36 - measure(lab, 12, true) - 8; if (suri) coverImg(suri, hx - 22, y + 12, 22, 5);
  if (ui.menu) drawMenu(H, sp, set);
  return H;
}
function drawMenu(H, sp, set) {
  hit(rr(0, 0, W, H, 0, "rgba(0,0,0,0.353)"), () => { ui.menu = false; redraw(); });
  const gx = R_ - 32; rr(gx, 14, R_, 46, 10, "#2a2a2a"); sprite("gear", gx + 6, 20, gx + 26, 40);   // (green when open: 1.0.9 gear_img[True])
  const mx0 = R_ - 190; let my0 = 52; const XTRA = 32;                       // 1.1: one extra row (Real playback)
  rr(mx0, my0, R_, my0 + 180 + 38 - 32 + XTRA, 10, "#262626", "#3a3a3a");
  const gw = measure("\u2630  ", 12);
  const item = (y0, h, fn) => { const r = hit(rr(mx0 + 6, y0, R_ - 6, y0 + h, 7, "#262626"), fn); hov(r, () => r.style.background = "#303030", () => r.style.background = "#262626"); return r; };
  item(my0 + 6, 32, () => invoke("noop").catch(() => {}));
  sprite("m_rep", mx0 + 20 + (gw - 8) / 2 - 9, my0 + 13, mx0 + 20 + (gw - 8) / 2 + 9, my0 + 31).style.pointerEvents = "none";
  text(mx0 + 20 + gw, my0 + 22, "Music in replays", 12, C.tx); toggle(R_ - 14 - 30, my0 + 22 - 8, set.music_in_replays, 30, 16).style.pointerEvents = "none";
  hline(mx0 + 10, my0 + 41, R_ - 10, "#3a3a3a"); my0 += 38;
  item(my0 + 6, 32); text(mx0 + 20, my0 + 22, "\u21bb  Check for updates", 12, C.tx);
  item(my0 + 38, 32); text(mx0 + 20, my0 + 54, "\u2630  Open log", 12, C.tx);
  item(my0 + 70, 32); sprite("m_gh", mx0 + 20 + (gw - 8) / 2 - 9, my0 + 77, mx0 + 20 + (gw - 8) / 2 + 9, my0 + 95).style.pointerEvents = "none";
  text(mx0 + 20 + gw, my0 + 86, "GitHub", 12, C.tx);
  item(my0 + 102, 32, () => invoke("set_real", { on: !sp.real }));
  text(mx0 + 20, my0 + 118, "\u25b6  Real playback (1.1)", 12, C.tx); toggle(R_ - 14 - 30, my0 + 118 - 8, sp.real, 30, 16).style.pointerEvents = "none";
  const dy = -32 + XTRA;
  hline(mx0 + 10, my0 + 140 + dy, R_ - 10, "#3a3a3a");
  item(my0 + 144 + dy, 30); text(mx0 + 20, my0 + 159 + dy, "\u2715  Uninstall", 12, C.red, true);
}

// ---------- Age Intros overview (intros.py draw_overview) ----------
const IW = 520, OV_TOP = 124, OV_STEP = 106, OV_CARD = 96, OV_FOOT = 48, HY = 40;
function introsH(n, mainh) { return Math.max(OV_TOP + n * OV_STEP - (OV_STEP - OV_CARD) + OV_FOOT, mainh); }
function drawIntros(s) {
  const n = s.ages.length, H = introsH(n, mainH(n)); begin("intros", IW, H);
  const bk = hit(oval(18, 24, 50, 56, C.card), () => go("main")); sprite("back", 18, 24, 50, 56).style.pointerEvents = "none";
  hov(bk, () => { bk.style.background = "#2a2a2a"; bk.nextSibling.style.opacity = 0; }, () => { bk.style.background = C.card; bk.nextSibling.style.opacity = 1; });
  sprite("icrown", 64, 28, 92, 52); text(102, HY, "Age Intros", 18, C.tx, true);
  // preset bar
  const y = 84; rr(20, y - 18, IW - 140, y + 18, 18, C.card, "#3e3e3e"); oval(34, y - 6, 46, y + 6, C.acc);
  text(56, y, "Custom", 13, C.tx, true); text(IW - 176, y, "Auto-saved", 10, C.mu, true, "e"); sprite("pchev", IW - 166, y - 6, IW - 154, y + 6);
  sprite("share", IW - 121, y - 15, IW - 91, y + 15); sprite("import", IW - 73, y - 15, IW - 43, y + 15);
  s.ages.forEach(([k, lab], i) => {
    const cy = OV_TOP + i * OV_STEP, o = s.intros[k], on = o.on, n = o.n;
    const card = rr(20, cy, IW - 20, cy + OV_CARD, 18, C.card); card.classList.add("hit");
    let more = null;
    hov(card, () => { card.style.background = "#262626"; card.style.border = "1px solid #464646"; if (more) more.style.background = "#262626"; },
              () => { card.style.background = C.card; card.style.border = "none"; if (more) more.style.background = C.card; });
    oval(62 - 18, cy + 32 - 18, 62 + 18, cy + 32 + 18, on ? "#1e3c28" : "#2c2c2c").style.pointerEvents = "none";
    text(62, cy + 31, ROMAN[i], 18 * 0.62, on ? C.acc : C.mu, true, "center");
    text(100, cy + 22, lab.replace(" Age", ""), 17, C.tx, true);
    text(100, cy + 40, n ? `${n}/${o.civs} civs` : "Empty", 11, n && on ? C.acc : C.mu, true);
    toggle(IW - 66 - 44, cy + 32 - 12, on, 44, 24, null, !n); sprite("ichev", IW - 51, cy + 21, IW - 29, cy + 43).style.pointerEvents = "none";
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
  text(IW / 2, H - 20, "Click an age to edit", 10, "#5a5a5a", false, "center");
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
  const r = frameRect(p), f = $("frame"); Object.assign(f.style, { left: r.x + "px", top: r.y + "px", width: r.w + "px", height: r.h + "px" });
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
function render(s) { S = s; const mh = drawMain(s), ih = drawIntros(s); sizes = { main: [W, mh], intros: [IW, ih] }; }
async function redraw(geom) { if (!S) return; render(S); if (geom || (applied && frameRect(applied).h !== parseFloat($("frame").style.height))) await apply(page); }
async function go(p) { await apply(p); }
window.go = go;
document.addEventListener("keydown", (e) => { if ((e.key === "Escape" || e.key === "Backspace") && page === "intros") go("main"); });
const W_ = window.__TAURI__.window.getCurrentWindow();
$("tbmin").onclick = () => W_.minimize(); $("tbclose").onclick = () => W_.close();
window.addEventListener("blur", () => document.body.classList.add("inactive")); window.addEventListener("focus", () => document.body.classList.remove("inactive"));
let lastJ = "";
async function tick() {
  try { const s = await invoke("get_state"); const j = JSON.stringify([s.settings, s.spotify, s.status.in_match, s.status.age, s.status.watching, s.intros]);
    if (j !== lastJ) { const first = !lastJ; lastJ = j; render(s); if (first) await apply("main"); else await redraw(); } } catch (e) { console.error(e); }
  setTimeout(tick, 500);
}
tick();
