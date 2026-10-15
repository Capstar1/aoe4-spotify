// ---------- Age page (1.0.9 intros.py draw() for one age) + approved changes:
// either/or tray (no songs of your own: Octopath shown normally, no emblem; >=1: Octopath folds into the spiked
// emblem, one group at a time, a compact Yours count chip switches back) and the squeezed-chip stacking rule
// (normal order = right neighbour on top; hover ring / playing glow sit directly above their own chip, so the right
// neighbour covers them; the audio badge is a separate top-most item).
const LT = 178, RH = 40, GAP = 4, STEP = RH + GAP, CR = 14, ER = 23, EX = 57, TY = 119, LN = "#2e2e2e";
const AS = {}; fetch("img/age/sizes.json").then((r) => r.json()).then((j) => { Object.assign(AS, j); redraw(); });
const age = { k: null, sc: 0, tray: null, hovTray: null, drag: null, drop: null, press: null, ghost: null, toast: null, song: null, busy: false, msg: null, msgT: 0 };
function aimg(name, cx, cy, sc) {   // a 1.0.9 Art render (genage.py), centred like Tk (even sizes -> exact centre)
  const [w0, h0] = AS[name] || [0, 0], w = w0 * (sc || 1), h = h0 * (sc || 1);
  const e = el("img", "a", { left: (cx - w / 2) + "px", top: (cy - h / 2) + "px", width: w + "px", height: h + "px", pointerEvents: "none" });
  e.draggable = false; e.srcset = `img/age/${name}@1.png 1x, img/age/${name}@1.5.png 1.5x`; e.src = `img/age/${name}@1.png`; return e;
}
function songChip(sg, cx, cy, r) {   // sg = [key, name, artist, uri, colour]; your songs show their cached cover
  const D = 2 * r + 4, e = el("div", "chip", { left: (cx - D / 2) + "px", top: (cy - D / 2) + "px", width: D + "px", height: D + "px", background: sg[4] });
  const i = document.createElement("img"); i.style.width = i.style.height = (D - 4) + "px"; i.draggable = false;
  if (sg[0].startsWith("c_")) { const u = sg[3]; if (!(u in covers)) { covers[u] = null; invoke("cover", { uri: u }).then((v) => { if (v) { covers[u] = v; redraw(); } }); } if (covers[u]) i.src = covers[sg[3]];
    else { i.style.background = "#262626"; i.style.boxShadow = `inset 0 0 0 ${Math.max(2, (D - 4) / 14)}px #262626`; } }
  else i.src = `img/portraits/${sg[0]}.jpg`;
  e.appendChild(i); return e;
}
function glow(cx, cy, r, badgeOnly) {   // render_glow / render_badge as CSS: breathing halo + thin ring; equalizer badge
  if (badgeOnly) {
    const b = el("div", "eq", { left: (cx + r * 0.86 - 6) + "px", top: (cy + r * 0.86 - 6) + "px" });
    for (let i = 0; i < 3; i++) { const s = document.createElement("i"); s.style.left = (6 - 0.85 + (i - 1) * 2.6 - 1.2) + "px"; s.style.animationDelay = (-i * 0.37 * 0.9) + "s"; b.appendChild(s); }
    return b;
  }
  const R1 = r + 16, g = el("div", "glow", { left: (cx - R1) + "px", top: (cy - R1) + "px", width: 2 * R1 + "px", height: 2 * R1 + "px", "--r": r + "px" });
  return g;
}
function ageData() { return S && S.agedata; }
// ---- editor model (1.0.9 intros.py pools/commit/record + settings.py presets), on 1.1's own copy (S.ed -> intros.json)
const clone = (v) => JSON.parse(JSON.stringify(v ?? null)), J = (v) => JSON.stringify(v);
const ED = { undo: [], redo: [], cur: null };
function songsOf(u) { const d = S.agedata; return d.songs.slice(0, d.nb).concat((u.custom_songs || []).filter((c) => c && String(c.uri || "").startsWith("spotify:track:"))
  .map((c) => ["c_" + c.uri.split(":").pop(), c.name || "Song", c.artist || "", c.uri, "#1DB954"])); }
function sorted(u, l) { const idx = new Map(songsOf(u).map((x, i) => [x[3], i])); l = [...new Set(l || [])];
  return l.map((x, i) => [x, i]).sort((a, b) => ((idx.has(a[0]) ? idx.get(a[0]) : 1e9) - (idx.has(b[0]) ? idx.get(b[0]) : 1e9)) || a[1] - b[1]).map((a) => a[0]); }
function poolsOf(u, a) { const d = S.agedata, bp = (u.intro_pools || {})[a] || {}, o = {};
  for (const [c] of d.civs) o[c] = a === d.default_age ? sorted(u, c in bp ? bp[c] : d.defs[c]) : sorted(u, bp[c] || []); return o; }
const agesOn = (u) => Object.fromEntries(S.ages.map(([a]) => [a, typeof (u.intro_ages || {})[a] === "boolean" ? u.intro_ages[a] : a === S.agedata.default_age]));
const ageEmpty = (u, a) => !Object.values(poolsOf(u, a)).some((v) => v.length);
const DEFAULT_PRESET = "Default";
const userPresets = (u) => [{ v: 1, name: DEFAULT_PRESET, pools: {}, ages: {}, custom: [], builtin: true }].concat((u.intro_presets || []).filter((p) => p && p.name));
function presetKey(u, p) { const pools = p ? p.pools : u.intro_pools, ages = p ? p.ages : u.intro_ages, pk = {};
  for (const [a, d] of Object.entries(pools || {})) { const o = {}; for (const [c, v] of Object.entries(d || {})) if (v && v.length) o[c] = [...v].sort(); if (Object.keys(o).length) pk[a] = Object.fromEntries(Object.entries(o).sort()); }
  const on = {}; for (const [a] of S.ages) on[a] = !!((ages || {})[a] ?? (a === S.agedata.default_age));
  return J([Object.fromEntries(Object.entries(pk).sort()), on]); }
function presetFromUser(u, name) { const pools = clone(u.intro_pools || {}), used = new Set(Object.values(pools).flatMap((a) => Object.values(a).flat()));
  return { v: 1, name: String(name).slice(0, 40), pools, ages: { ...(u.intro_ages || {}) }, custom: (u.custom_songs || []).filter((c) => used.has(c.uri)).map((c) => { const o = {}; for (const k of ["uri", "name", "artist", "cover"]) if (c[k]) o[k] = c[k]; return o; }) }; }
function uniqueName(u, name) { const names = new Set(userPresets(u).map((p) => p.name.toLowerCase())); name = (name || "Preset").trim().slice(0, 40) || "Preset";
  if (!names.has(name.toLowerCase())) return name; let n = 2; while (names.has(`${name} (${n})`.toLowerCase())) n++; return `${name} (${n})`; }
function autosave(u) { const n = u.intro_preset || DEFAULT_PRESET, cur = userPresets(u).find((p) => p.name === n);
  if (cur && presetKey(u, cur) === presetKey(u)) return null; const ps = (u.intro_presets || []).filter((p) => p && typeof p === "object");
  if (cur && !cur.builtin) { u.intro_presets = ps.map((p) => p.name === n ? presetFromUser(u, n) : p); return null; }
  const name = uniqueName(u, cur || n === DEFAULT_PRESET ? "Custom" : n); u.intro_presets = ps.concat([presetFromUser(u, name)]); u.intro_preset = name; return name; }
function applyPreset(u, p) { if (p.pools && Object.keys(p.pools).length) u.intro_pools = clone(p.pools); else delete u.intro_pools;
  if (p.ages && Object.keys(p.ages).length) u.intro_ages = { ...p.ages }; else delete u.intro_ages;
  const cs = [...(u.custom_songs || [])], have = new Set(cs.map((c) => c.uri));
  for (const c of p.custom || []) if (!have.has(c.uri)) { cs.push({ ...c }); have.add(c.uri); } if (cs.length) u.custom_songs = cs; u.intro_preset = p.name || DEFAULT_PRESET; }
const snap = (u) => clone(Object.fromEntries(["intro_pools", "intro_ages", "custom_songs", "intro_preset", "intro_presets"].map((k) => [k, u[k] ?? null])));
async function saveEd(u) { window.EDV = (window.EDV || 0) + 1; S.ed = u; const t = performance.now(); await invoke("save_ed", { u }); const s = await invoke("get_state"); render(s); lastJ = "edited"; ED.ms = performance.now() - t; }
function record(u) {
  if (!ED.cur) ED.cur = snap(S.ed);
  const on = agesOn(u); for (const [a] of S.ages) if (ageEmpty(u, a) && on[a]) u.intro_ages = { ...(u.intro_ages || {}), [a]: false };
  const np = autosave(u), sn = snap(u);
  if (J(sn) !== J(ED.cur)) { ED.undo.push(ED.cur); ED.redo = []; ED.cur = sn; ED.undo.splice(0, Math.max(0, ED.undo.length - 500)); }
  saveEd(u); if (np) toast(`Saved as \u201c${np}\u201d`);
}
function undoRedo(back) { const src = back ? ED.undo : ED.redo, dst = back ? ED.redo : ED.undo; if (!src.length || age.drag) return;
  dst.push(ED.cur); ED.cur = src.pop(); const u = { ...clone(S.ed), ...clone(ED.cur) }; for (const k in ED.cur) if (ED.cur[k] == null) delete u[k];
  if (autosave(u) !== null) ED.cur = snap(u); saveEd(u); }
function commitPools(p) { const u = clone(S.ed), a = age.k, d = S.agedata, bp = {};
  for (const c in p) { const v = sorted(u, p[c]); if (a === d.default_age) { if (J(v) !== J(sorted(u, d.defs[c]))) bp[c] = v; } else if (v.length) bp[c] = v; }
  const ip = { ...(u.intro_pools || {}) }; if (Object.keys(bp).length) ip[a] = bp; else delete ip[a]; if (Object.keys(ip).length) u.intro_pools = ip; else delete u.intro_pools; record(u); }
function setAgeOn(a, on) { const u = clone(S.ed); if (on && ageEmpty(u, a)) return; u.intro_ages = { ...(u.intro_ages || {}), [a]: !!on }; record(u); }
function removeAt(civ, j) { const p = poolsOf(S.ed, age.k); p[civ].splice(j, 1); commitPools(p); }
function removeCustom(uri) { const u = clone(S.ed); u.custom_songs = (u.custom_songs || []).filter((c) => c.uri !== uri); const ip = u.intro_pools || {};
  for (const a in ip) for (const c in ip[a]) { ip[a][c] = ip[a][c].filter((x) => x !== uri); if (!ip[a][c].length && a !== S.agedata.default_age) delete ip[a][c]; } record(u); }
function setPackOpen(open) { const u = clone(S.ed); u.intro_pack_open = open; age.tray = open ? "octo" : "yours"; tip.hide(); saveEd(u); }
let toastT = 0; function toast(m) { age.toast = m; toastT = Date.now(); redraw(); setTimeout(() => { if (Date.now() - toastT >= 1790) { age.toast = null; redraw(); } }, 1800); }
document.addEventListener("keydown", (e) => { if (e.ctrlKey && (e.key === "z" || e.key === "Z")) { undoRedo(true); e.preventDefault(); } else if (e.ctrlKey && (e.key === "y" || e.key === "Y")) { undoRedo(false); e.preventDefault(); } });
// ---- GlassTip (widgets.py): dark glass card + arrow, bold 12, below the item (flips above), 350 ms delay, warm switch, 120 ms fade + 2 px slide
const tip = { el: null, job: 0, key: null, tHide: 0,
  request(key, txt, r) { if (this.key === J(key) && this.el) return; this.hide(true); this.key = J(key); const warm = Date.now() - this.tHide < 400;
    clearTimeout(this.job); this.job = setTimeout(() => this.show(txt, r, !warm), warm ? 0 : 350); },
  show(txt, [x0, y0, x1, y1], slide) { const pg = $(page); if (!pg) return; const e = document.createElement("div"); e.className = "gtip"; e.textContent = txt; pg.appendChild(e);
    const w = e.offsetWidth, h = e.offsetHeight, H = parseFloat(pg.style.height) || 586, Wp = parseFloat(pg.style.width) || IW, below = y1 + 6 + h + 6 <= H;
    const cx = (x0 + x1) / 2, left = Math.min(Math.max(4, cx - w / 2), Wp - 4 - w); e.classList.add(below ? "up" : "down"); e.style.setProperty("--ax", (cx - left) + "px");
    const top = below ? y1 + 6 + 6 : y0 - 6 - 6 - h; e.style.left = left + "px"; e.style.top = (top + (slide ? (below ? 2 : -2) : 0)) + "px";
    requestAnimationFrame(() => { e.style.opacity = 1; e.style.top = top + "px"; }); this.el = e; },
  hide(keepKey) { clearTimeout(this.job); if (this.el) { const e = this.el; e.style.transition = "opacity 80ms"; e.style.opacity = 0; setTimeout(() => e.remove(), 90); this.el = null; this.tHide = Date.now(); } if (!keepKey) this.key = null; } };
function tipOn(h, key, txt, r) { h._tip = true; h.removeAttribute("title"); h.addEventListener("mouseenter", () => { if (!age.drag) tip.request(key, txt, r); }); h.addEventListener("mouseleave", () => tip.hide()); }
document.addEventListener("pointerdown", () => tip.hide(), true); document.addEventListener("wheel", () => tip.hide(), true);
// ---- drag (on_press / on_drag / on_release): tray chip -> civ row = add; row chip -> other row = move; dragged out of its row = remove
function startDrag(e, song, src, cx, cy) { if (e.button !== 0) return; e.preventDefault(); age.press = { x: e.clientX, y: e.clientY, song, src, cx, cy }; }
function pagePt(e) { const r = $("age").getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; }
function dropRow(x, y) { const d = S.agedata, H = sizes.age[1], BOT = H - 12; if (!(LT <= y && y <= BOT && 20 <= x && x <= IW - 32)) return null;
  const i = Math.floor((y - LT + age.sc) / STEP); if (i < 0 || i >= d.civs.length) return null; const ry = LT + i * STEP - age.sc; return ry <= y && y <= ry + RH ? i : null; }
window.addEventListener("pointermove", (e) => { const p = age.press; if (!p) return; const [x, y] = pagePt(e);
  if (!age.drag && Math.abs(e.clientX - p.x) + Math.abs(e.clientY - p.y) < 4) return; tip.hide();
  if (!age.drag) age.drag = { song: p.song, src: p.src }; age.drag.xy = [x, y];
  const H = sizes.age[1], BOT = H - 12, d = S.agedata, maxSc = Math.max(0, d.civs.length * STEP - GAP - (BOT - LT)), sc0 = age.sc;
  if (y > BOT - 24 && age.sc < maxSc) age.sc = Math.min(maxSc, age.sc + 8); else if (LT < y && y < LT + 24 && age.sc > 0) age.sc = Math.max(0, age.sc - 8);
  let drop = dropRow(x, y), uri = p.song[3];
  if (drop != null && p.src[0] === "row" && p.src[1] === drop) drop = null;
  if (drop != null && poolsOf(S.ed, age.k)[d.civs[drop][0]].includes(uri)) drop = null;
  if (drop === age.drop && sc0 === age.sc && age.ghost) { age.ghost.style.left = (x - 21) + "px"; age.ghost.style.top = (y - 21) + "px"; return; }
  age.drop = drop; redraw(); });
window.addEventListener("pointerup", (e) => { const p = age.press; age.press = null; if (!p) return; const dr = age.drag, drop = age.drop; age.drag = null; age.drop = null; age.ghost = null;
  if (!dr) { if (age.press === null) preview(p.song, p.cx, p.cy); return; }
  const d = S.agedata, pools = poolsOf(S.ed, age.k), uri = p.song[3], [x, y] = pagePt(e), h = dropRow(x, y);
  if (drop != null) { const civ = d.civs[drop][0]; if (!pools[civ].includes(uri)) pools[civ].push(uri);
    if (p.src[0] === "row") { const sc_ = d.civs[p.src[1]][0]; if (pools[sc_].length > 1) pools[sc_] = pools[sc_].filter((u) => u !== uri); }
    commitPools(pools); }
  else if (p.src[0] === "row" && h !== p.src[1]) removeAt(d.civs[p.src[1]][0], p.src[2]);
  else redraw(); });
function trayLayout(d, u) {
  const NB = d.nb, U = d.songs.length - NB, W = IW, ysp = Math.min(50, 100 / Math.max(1, U)), yr = Math.max(9, Math.min(19, ysp * 0.45));
  const view = U === 0 ? "octo0" : (u.intro_pack_open ? "octo" : "yours"), out = { view, chips: [], emblem: false, count: null };
  if (view === "octo0") {       // no songs of your own: Octopath shown normally (1.0.9 unfolded spacing, no emblem, no '<')
    const bsp = Math.max(22, Math.min(48, ((W - 24) - (16 + 38 + 4) - 63 - 53) / Math.max(1, NB - 1)));
    for (let i = 0; i < NB; i++) out.chips.push({ i, cx: 53 + i * bsp, r: 19 });
    out.div = 53 + (NB - 1) * bsp + 19 + 16; out.plus = { cx: out.div + 16 + 19, r: 19 };
  } else if (view === "yours") { // Octopath folded into the emblem; your songs
    out.emblem = true; out.div = EX + ER + 16;
    for (let j = 0; j < U; j++) out.chips.push({ i: NB + j, cx: out.div + 16 + yr + j * ysp, r: yr });
    out.plus = { cx: out.div + 16 + yr + U * ysp, r: yr };
  } else {                       // Octopath shown (squeezed); compact Yours count chip switches back
    out.div = W - 213; const bsp = Math.min(48, (out.div - 12 - 19 - 53) / Math.max(1, NB - 1));
    for (let i = 0; i < NB; i++) out.chips.push({ i, cx: 53 + i * bsp, r: 19 });
    out.count = { cx: out.div + 16 + 19, r: 19, n: U }; out.plus = { cx: out.div + 16 + 19 + 44, r: 19 };
  }
  return out;
}
const GL = { n: 54 }; fetch("img/age/glow.json").then((r) => r.json()).then((j) => Object.assign(GL, j));
function glow(cx, cy, r, badge) {   // the 1.0.9 render_glow / render_badge frames (genglow.py), 54 x 33 ms breathing cycle
  const R = r >= 16 ? 19 : 14, k = r / R, D = (GL[(badge ? "eq" : "glow") + R] || (R === 19 ? 74 : 64)) * k, nm = (badge ? "eq" : "glow") + R;
  const e = el("div", "glowf", { left: (cx - D / 2) + "px", top: (cy - D / 2) + "px", width: D + "px", height: D + "px", "--D": D + "px",
    backgroundImage: `image-set(url(img/age/${nm}@1.png) 1x, url(img/age/${nm}@1.5.png) 1.5x)`, backgroundSize: `${D * GL.n}px ${D}px`,
    animationDelay: (-(((Date.now() - (age.t0 || 0)) / 1000) % 1.782)) + "s" });
  e.style.setProperty("--D", D + "px"); if (age.fadeIn) e.classList.add("fadein"); return e;
}
function drawAge(s) {
  const d = s.agedata, H = introsH(s.ages.length, mainH(s.ages.length)); begin("age", IW, H);
  if (!d || !age.k || !s.ed) return H;
  const u = s.ed, W = IW, BOT = H - 12, ai = s.ages.findIndex((a) => a[0] === age.k), lab = (s.ages[ai] || ["", ""])[1].replace(" Age", "");
  const pools = poolsOf(u, age.k), civs = d.civs, byUri = Object.fromEntries(d.songs.map((x) => [x[3], x]));
  const maxSc = Math.max(0, civs.length * STEP - GAP - (BOT - LT)); age.sc = Math.max(0, Math.min(maxSc, age.sc));
  const on = agesOn(u)[age.k], empty = ageEmpty(u, age.k), isDef = age.k === d.default_age, custom = !!(u.intro_pools || {})[age.k];
  const dragging = !!(age.drag && age.drag.xy), tipR = (x0, y0, x1, y1) => [x0, y0, x1, y1];
  // list (clipped like the Tk covers: header above LT-4, bottom below BOT)
  const root = host, list = el("div", "a", { left: "0px", top: (LT - 4) + "px", width: W + "px", height: (BOT - LT + 4) + "px", overflow: "hidden" });
  list.addEventListener("wheel", (e) => { age.sc = Math.max(0, Math.min(maxSc, age.sc + Math.sign(e.deltaY) * 46)); redraw(); }, { passive: true });
  const inner = el("div", "a", { left: "0px", top: (-(LT - 4)) + "px", width: W + "px", height: H + "px" }); list.appendChild(inner); host = inner; host._w = W;
  const firstEmpty = civs.findIndex(([c]) => !pools[c].length), marks = [];
  civs.forEach(([civ, name], i) => {
    const y = LT + i * STEP - age.sc; if (y > BOT || y + RH < LT - 60) return;
    const cy = y + RH / 2, p = pools[civ], drop = age.drop === i;
    rr(20, y, W - 32, y + RH, 10, drop ? "#1c2a20" : C.card, drop ? C.acc : null); const [fw, fh] = AS["flag_" + civ] || [30, 16];
    const f = el("img", "a", { left: "32px", top: (cy - fh / 2) + "px", width: fw + "px", height: fh + "px" }); f.srcset = `img/age/flag_${civ}@1.png 1x, img/age/flag_${civ}@1.5.png 1.5x`; f.src = `img/age/flag_${civ}@1.png`;
    text(72, cy, name, 12, C.tx, true);
    p.forEach((uri, j) => { const sg = byUri[uri]; if (!sg) return; const cx = 205 + j * 34;
      const moving = age.drag && age.drag.src[0] === "row" && age.drag.src[1] === i && age.drag.src[2] === j && dragging;
      const c = songChip(sg, cx, cy, CR); if (moving) c.style.filter = "brightness(.4)";
      if (age.song === sg[0] && !dragging) marks.push([c, cx, cy, CR]);
      const h = hit(oval(cx - 16, cy - 16, cx + 16, cy + 16, "transparent"), null); h.onpointerdown = (e) => startDrag(e, sg, ["row", i, j], cx, cy);
      h.oncontextmenu = (e) => { e.preventDefault(); removeAt(civ, j); };
      tipOn(h, ["chip", i, j], sg[2] ? `${sg[1]} \u2014 ${sg[2]}` : sg[1], tipR(cx - 15, cy - 18, cx + 15, cy + 18));
      // the x badge appears on hover; clicking it removes the song (green while hovered)
      let xb = null; const xh = hit(oval(cx + 4, cy - 18, cx + 18, cy - 4, "transparent"), () => removeAt(civ, j)); xh.style.display = "none";
      hov(h, () => { if (dragging) return; xb = aimg("xbadge", cx + 11, cy - 11); xh.style.display = ""; h.after(xb); }, (e) => { if (e.relatedTarget !== xh && xb) { xb.remove(); xb = null; xh.style.display = "none"; } });
      hov(xh, () => { if (xb) xb.srcset = xb.srcset.replaceAll("xbadge@", "xbadge_h@"); }, (e) => { if (e.relatedTarget !== h && xb) { xb.remove(); xb = null; xh.style.display = "none"; } else if (xb) xb.srcset = xb.srcset.replaceAll("xbadge_h@", "xbadge@"); }); });
    if (drop) { const x = 205 + p.length * 34; aimg("ring15", x, cy); text(x, cy, "+", 13, C.acc, true, "center"); }
    else if (!p.length) { const o = oval(190, cy - 15, 220, cy + 15, null); o.style.border = "1px dashed #4b4b4b";
      if (i === firstEmpty) { text(205, cy, "+", 13, "#6e6e6e", false, "center"); text(232, cy, "Drag songs here", 10, "#646464"); } }
    if (isDef && J(p) !== J(sorted(u, d.defs[civ]))) { const g = aimg("undo_mu", W - 53, cy), h = hit(rr(W - 68, cy - 15, W - 38, cy + 15, 4, "transparent"), () => { const q = poolsOf(S.ed, age.k); q[civ] = sorted(S.ed, d.defs[civ]); commitPools(q); });
      hov(h, () => g.srcset = g.srcset.replaceAll("undo_mu@", "undo_tx@"), () => g.srcset = g.srcset.replaceAll("undo_tx@", "undo_mu@")); tipOn(h, ["undo", i], "Back to default", tipR(W - 62, cy - 10, W - 44, cy + 10)); }
  });
  if (maxSc) { const vh = BOT - LT, th = Math.max(28, vh * vh / (vh + maxSc)), ty = LT + (vh - th) * age.sc / maxSc;
    rr(W - 28, LT, W - 24, BOT, 2, "#2a2a2a"); rr(W - 28, ty, W - 24, ty + th, 2, "#5a5a5a"); }
  marks.forEach(([c, cx, cy, r]) => { const g = glow(cx, cy, r); c.after(g); });   // glow right above its own chip (the right neighbour covers it)
  marks.forEach(([c, cx, cy, r]) => glow(cx, cy, r, true));                        // audio badge: top of the list layer
  host = root;
  // header
  const bk = hit(oval(18, HY - 16, 50, HY + 16, "transparent"), () => { tip.hide(); go("intros"); age.k = null; }); const bi = aimg("back", 34, HY);
  hov(bk, () => bi.srcset = bi.srcset.replaceAll("back@", "back_h@"), () => bi.srcset = bi.srcset.replaceAll("back_h@", "back@"));
  aimg(`badge${ai}_${on ? "on" : "off"}`, 78, HY); text(102, HY, lab, 18, C.tx, true);
  toggle(W - 38 - 44, HY - 12, on, 44, 24, null, empty);
  const sw = hit(rr(W - 86, HY - 16, W - 34, HY + 16, 0, "transparent"), () => { if (!empty) setAgeOn(age.k, !on); }); if (empty) { sw.style.cursor = "not-allowed"; tipOn(sw, ["swoff", age.k], "Add a song first", tipR(W - 68, HY - 14, W - 44, HY + 10)); }
  if (custom) { const g = aimg("undo_mu", W - 22, HY), h = hit(rr(W - 32, HY - 12, W - 10, HY + 12, 4, "transparent"), () => commitPools(Object.fromEntries(civs.map(([c]) => [c, isDef ? sorted(S.ed, d.defs[c]) : []]))));
    hov(h, () => g.srcset = g.srcset.replaceAll("undo_mu@", "undo_tx@"), () => g.srcset = g.srcset.replaceAll("undo_tx@", "undo_mu@")); tipOn(h, ["reset"], "Reset this age", tipR(W - 31, HY - 10, W - 13, HY + 10)); }
  // tray
  rr(20, 70, W - 20, 162, 18, "#1a1a1a", LN); text(36, 81, "OCTOPATH", 8.5, C.mu, true);
  const L = trayLayout(d, u);
  if (age.dropOver) { const g = rr(L.div + 2, 72, W - 22, 160, 14, "rgba(29,185,84,.10)", C.acc); g.style.borderWidth = "2px"; g.style.boxShadow = "0 0 10px rgba(30,215,96,.35)"; }
  text(L.div + 14, 81, age.dropOver ? "DROP TO ADD" : "YOURS", 8.5, C.acc, true);
  if (!age.dropOver) text(L.plus.cx, 150, "or drop songs here", 8.5, "#7a7a7a", false, "center"); el("div", "a", { left: L.div + "px", top: "84px", width: "1px", height: "66px", background: LN });
  if (L.emblem) { const e = aimg("emblem", EX, TY), h = hit(oval(EX - ER, TY - ER, EX + ER, TY + ER, "transparent"), () => setPackOpen(true));
    tipOn(h, ["pack"], `Octopath Traveler \u2014 ${d.nb} songs (click to show)`, tipR(EX - ER, TY - ER - 3, EX + ER, TY + ER + 3));
    hov(h, () => e.srcset = e.srcset.replaceAll("emblem@", "emblem_h@"), () => e.srcset = e.srcset.replaceAll("emblem_h@", "emblem@")); }
  const tmarks = [];
  L.chips.forEach(({ i, cx, r }) => {         // left to right: the right neighbour is drawn later = on top
    const sg = d.songs[i], c = songChip(sg, cx, TY, r);
    if (age.hovTray === i && !dragging) c.after(ringAt(cx, TY, r + 3));          // hover ring: directly above its own chip
    if (age.drag && age.drag.src[0] === "tray" && age.drag.song === sg && dragging) c.after(ringAt(cx, TY, r + 3));
    if (age.song === sg[0] && !dragging) tmarks.push([c, cx, r]);
  });
  tmarks.forEach(([c, cx, r]) => c.after(glow(cx, TY, r)));
  if (L.count) { const { cx, r, n } = L.count, o = oval(cx - r - 0.5, TY - r - 0.5, cx + r + 0.5, TY + r + 0.5, null); o.style.border = "1.6px solid " + C.acc;
    text(cx, TY, String(n), 14, C.acc, true, "center"); const h = hit(oval(cx - r, TY - r, cx + r, TY + r, "transparent"), () => setPackOpen(false));
    tipOn(h, ["count"], `Your songs (${n}) \u2014 click to show`, tipR(cx - r, TY - r - 3, cx + r, TY + r + 3)); hov(h, () => o.style.background = "rgba(29,185,84,.15)", () => o.style.background = "transparent"); }
  const pl = aimg("plus", L.plus.cx, TY, L.plus.r / 19), ph = hit(oval(L.plus.cx - L.plus.r, TY - L.plus.r, L.plus.cx + L.plus.r, TY + L.plus.r, "transparent"), () => { tip.hide(); invoke("open_add"); });
  hov(ph, () => pl.srcset = pl.srcset.replaceAll("plus@", "plus_h@"), () => pl.srcset = pl.srcset.replaceAll("plus_h@", "plus@"));
  L.chips.forEach(({ i, cx, r }, n) => { const sg = d.songs[i], nx = L.chips[n + 1];
    const right = nx && nx.cx - nx.r < cx + r ? (nx.cx - nx.r) : cx + r;   // a squeezed chip is only clickable where it is visible
    const h = hit(rr(cx - r, TY - r, right, TY + r, r, "transparent"), null); h.style.borderRadius = right < cx + r ? `${r}px 0 0 ${r}px` : "50%";
    h.onpointerdown = (e) => startDrag(e, sg, ["tray", i], cx, TY);
    if (sg[0].startsWith("c_")) h.oncontextmenu = (e) => { e.preventDefault(); ctxMenu(e, [["Remove song", () => removeCustom(sg[3])]]); };
    tipOn(h, ["tray", i], sg[2] ? `${sg[1]} \u2014 ${sg[2]}` : sg[1], tipR(cx - r, TY - r - 3, cx + r, TY + r + 3));
    hov(h, () => { if (age.hovTray !== i && !dragging) { age.hovTray = i; redraw(); } }, () => { if (age.hovTray === i) { age.hovTray = null; redraw(); } }); });
  tmarks.forEach(([c, cx, r]) => glow(cx, TY, r, true));                      // audio badge: always on top of everything
  if (dragging) { const [gx, gy] = age.drag.xy; host.querySelectorAll(".hit").forEach((h) => h.style.pointerEvents = "none");
    age.ghost = songChip(age.drag.song, gx, gy, 19); age.ghost.style.zIndex = 5; }
  if (age.msg && Date.now() - age.msgT < 2600) { const [m, x, y] = age.msg, tw = measure(m, 10) + 20, x0 = Math.min(Math.max(8, x - tw / 2), W - 8 - tw), ty = Math.min(Math.max(8, y + 26), H - 32);
    rr(x0, ty, x0 + tw, ty + 24, 12, "#1c3a26", C.acc); text(x0 + tw / 2, ty + 12, m, 10, C.tx, false, "center"); }
  if (age.dropOver) { const m = "Drop to add to YOURS", tw = measure(m, 10) + 28; rr(W / 2 - tw / 2, H - 30, W / 2 + tw / 2, H - 8, 11, "#143c23", C.acc); text(W / 2, H - 19, m, 10, C.acc, true, "center"); }
  age.fadeIn = false;
  return H;
}
function ctxMenu(e, items) {   // 1.0.9 tk.Menu look: card bg, hover #2a2a2a
  document.querySelectorAll(".ctx").forEach((m) => m.remove()); const pg = $(page), r = pg.getBoundingClientRect(), m = document.createElement("div"); m.className = "ctx";
  m.style.left = (e.clientX - r.left) + "px"; m.style.top = (e.clientY - r.top) + "px";
  for (const [t, fn] of items) { const it = document.createElement("div"); it.textContent = t; it.onclick = () => { m.remove(); fn(); }; m.appendChild(it); }
  pg.appendChild(m); setTimeout(() => document.addEventListener("pointerdown", function f(ev) { if (!m.contains(ev.target)) { m.remove(); document.removeEventListener("pointerdown", f, true); } }, true), 0);
}
function ringAt(cx, cy, R) { const e = document.createElement("div"); e.className = "a"; Object.assign(e.style, { left: (cx - R - 0.75) + "px", top: (cy - R - 0.75) + "px", width: (2 * R + 1.5) + "px", height: (2 * R + 1.5) + "px", borderRadius: "50%", boxSizing: "border-box", border: "1.5px solid " + C.acc, pointerEvents: "none" }); return e; }
function hint(m, x, y) { age.msg = [m, x, y]; age.msgT = Date.now(); redraw(); setTimeout(redraw, 2650); }
async function preview(sg, cx, cy) {
  if (age.busy) return; const action = age.song === sg[0] ? "pause" : "play", prev = age.song;
  age.busy = true; age.song = action === "play" ? sg[0] : null; if (action === "play" && prev !== sg[0]) { age.fadeIn = true; age.t0 = Date.now(); } redraw();          // optimistic: the glow reacts on the click
  let res; try { res = await invoke("preview", { uri: action === "play" ? sg[3] : null }); } catch (e) { res = "err"; }
  age.busy = false;
  if (res === "login") { age.song = prev; hint("Log in to Spotify in AoE4 Spotify to preview", cx, cy); }
  else if (res !== "ok") { age.song = action === "play" ? (prev !== sg[0] ? prev : null) : prev; hint("Couldn't play - is Spotify (Premium) running?", cx, cy); }
  else redraw();
}
function openAge(k) { age.k = k; age.sc = 0; age.hovTray = null; tip.hide(); render(S); go("age"); }
// ---- presets (overview): menu, new, share, import (1.0.9 draw_bar / name_dialog / import_dialog)
function presetSongs(p) { const d = S.agedata, out = [];
  for (const [a] of S.ages) for (const [c] of d.civs) { const dd = (p.pools || {})[a] || {}; for (const x of (c in dd ? dd[c] : (a === d.default_age ? d.defs[c] : [])) || []) out.push(x); }
  return sorted(S.ed, out); }
function presetCounts(p) { const d = S.agedata, o = {}; for (const [a] of S.ages) { const dd = (p.pools || {})[a] || {}; o[a] = d.civs.filter(([c]) => (c in dd ? dd[c] : (a === d.default_age ? d.defs[c] : [])).length).length; } return o; }
function drawPresetMenu(s) {
  const u = s.ed, ps = userPresets(u), yb = 118 + ps.length * 46, cur = u.intro_preset || DEFAULT_PRESET, by = Object.fromEntries(s.agedata.songs.map((x) => [x[3], x]));
  const shade = hit(rr(0, 0, IW, 2000, 0, "transparent"), () => { ui.pmenu = false; redraw(); }); shade.style.cursor = "default";
  rr(18, 106, 332, yb + 44, 15, "#0c0c0c"); rr(20, 108, 330, yb + 40, 14, "#242424", "#3e3e3e");
  ps.forEach((p, i) => { const yy = 118 + i * 46, isCur = p.name === cur, row = hit(rr(26, yy, 324, yy + 42, 10, isCur ? "#1e3426" : "transparent"), () => switchPreset(p.name));
    if (!isCur) hov(row, () => row.style.background = "#2e2e2e", () => row.style.background = "transparent");
    presetSongs(p).slice(0, 3).forEach((x, j) => { const sg = by[x]; if (sg) songChip(sg, 48 + j * 16, yy + 21, 10); });
    text(100, yy + 21, p.name, 13, isCur ? C.acc : C.tx, true); const cnt = presetCounts(p);
    text(250, yy + 21, S.ages.map(([a], k) => cnt[a] && ((p.ages || {})[a] ?? a === s.agedata.default_age) ? ROMAN[k] : null).filter(Boolean).join(" "), 10, C.mu, true);
    if (isCur) text(307, yy + 20.5, "\u2713", 14, C.acc, true, "center");
    else if (!p.builtin) {   // delete: hover the row, click the x, click again to confirm (1.0.9 list delete: armed for 3 s)
      const armed = ui.pdel === p.name, dx = hit(rr(armed ? 262 : 294, yy + 9, 318, yy + 33, 12, armed ? "#3d1a1a" : "transparent", armed ? "#e5484d" : null), (e) => { e.stopPropagation(); delPreset(p.name); });
      const lab = armed ? text(290, yy + 21, "Delete", 10, "#e5484d", true, "center") : text(306, yy + 20.5, "\u2715", 11, C.mu, false, "center");
      tipOn(dx, ["pdel", p.name], armed ? "Click again to delete" : "Delete preset", [armed ? 262 : 294, yy + 9, 318, yy + 33]);
      if (!armed) { const show = (v) => { dx.style.opacity = lab.style.opacity = v ? "1" : "0"; }; show(false);
        row.addEventListener("mouseenter", () => show(true)); row.addEventListener("mouseleave", (e) => { if (e.relatedTarget !== dx) show(false); });
        dx.addEventListener("mouseenter", () => { show(true); dx.style.background = "#3a2222"; lab.style.color = "#e5484d"; });
        dx.addEventListener("mouseleave", (e) => { dx.style.background = "transparent"; lab.style.color = C.mu; if (e.relatedTarget !== row) show(false); }); dx._hov = true; }
    } });
  hline(32, yb + 1, 318, "#3e3e3e"); const nw = hit(rr(26, yb + 4, 324, yb + 32, 8, "transparent"), () => { ui.pmenu = false; nameDialog("New preset", "My preset", savePreset); });
  hov(nw, () => nw.style.background = "#2e2e2e", () => nw.style.background = "transparent"); text(48, yb + 18, "+", 16, C.acc, false, "center"); text(62, yb + 18, "New preset", 12, C.acc, true);
}
function delPreset(name) {
  if (ui.pdel !== name) { ui.pdel = name; redraw(); clearTimeout(ui.pdelT); ui.pdelT = setTimeout(() => { if (ui.pdel === name) { ui.pdel = null; redraw(); } }, 3000); return; }
  ui.pdel = null; const u = clone(S.ed); u.intro_presets = (u.intro_presets || []).filter((q) => !(q && q.name === name)); saveEd(u); }
function switchPreset(name) { const u = clone(S.ed), p = userPresets(u).find((q) => q.name === name); ui.pmenu = false; if (!p) return redraw(); applyPreset(u, p); record(u); }
function savePreset(name) { const u = clone(S.ed), ps = (u.intro_presets || []).filter((p) => p && typeof p === "object"); name = uniqueName(u, name);
  ps.push(presetFromUser(u, name)); u.intro_presets = ps; u.intro_preset = name; ED.cur = snap(u); saveEd(u); }
async function sharePreset() { const u = S.ed, p = presetFromUser(u, u.intro_preset || "Shared"); const code = await invoke("encode_preset", { p });
  try { await navigator.clipboard.writeText(code); } catch (e) {} window.__lastCode = code; toast("Code copied"); }
function modal(H, w, h, build) { rr(0, 0, IW, H, 0, "rgba(0,0,0,.55)").classList.add("hit"); const x0 = (IW - w) / 2, y0 = Math.max(60, (H - h) / 2); rr(x0, y0, x0 + w, y0 + h, 14, "#1e1e1e", "#3e3e3e"); build(x0, y0); }
function input(x, y, w, h, val) { const e = el("input", "a", { left: x + "px", top: y + "px", width: w + "px", height: h + "px", background: "#141414", color: "#c8c8c8", border: "1px solid #3e3e3e",
  outline: "none", font: '400 13px "Segoe UI"', padding: "0 10px", boxSizing: "border-box", borderRadius: "6px" }); e.value = val || ""; e.onfocus = () => e.style.borderColor = C.acc; e.onblur = () => e.style.borderColor = "#3e3e3e"; return e; }
function button(x0, y0, x1, y1, label, fn, primary) { const b = hit(rr(x0, y0, x1, y1, (y1 - y0) / 2, primary ? C.acc : "#2a2a2a"), fn); text((x0 + x1) / 2, (y0 + y1) / 2, label, 12, primary ? "#121212" : C.tx, true, "center"); return b; }
function nameDialog(title, init, cb) { let inp; const close = () => { ui.dialog = null; redraw(); };
  ui.dialog = (H) => modal(H, 330, 132, (x0, y0) => { text(x0 + 16, y0 + 26, title, 15, C.tx, true); inp = input(x0 + 16, y0 + 46, 298, 32, ui.dv ?? init);
    inp.oninput = () => ui.dv = inp.value; inp.onkeydown = (e) => { if (e.key === "Enter") ok(); if (e.key === "Escape") { ui.dv = null; close(); } };
    button(x0 + 160, y0 + 92, x0 + 230, y0 + 120, "Cancel", () => { ui.dv = null; close(); }); button(x0 + 240, y0 + 92, x0 + 314, y0 + 120, "Save", ok, true);
    setTimeout(() => { inp.focus(); if (ui.dv == null) inp.select(); }, 0); });
  const ok = () => { const v = (inp.value || "").trim(); if (v) { ui.dv = null; ui.dialog = null; cb(v); } }; redraw(); }
function importDialog() { let inp, res = { p: null, err: null }; const close = () => { ui.dialog = null; ui.dv = null; redraw(); };
  const check = async () => { const v = inp.value.trim(); ui.dv = inp.value; if (!v) { res = { p: null, err: null }; return redraw(); }
    try { res = { p: await invoke("decode_preset", { code: v }), err: null }; } catch (e) { res = { p: null, err: String(e) }; } redraw(); };
  ui.dialog = (H) => modal(H, 480, 300, (x0, y0) => {
    oval(x0 + 23, y0 + 21, x0 + 53, y0 + 51, "#1e3c28", C.acc); sprite("import", x0 + 23, y0 + 21, x0 + 53, y0 + 51).style.pointerEvents = "none"; text(x0 + 62, y0 + 36, "Import", 17, C.tx, true);
    const xb = hit(oval(x0 + 440, y0 + 20, x0 + 464, y0 + 46, "transparent"), close); text(x0 + 452, y0 + 34, "\u2715", 14, C.mu, false, "center");
    inp = input(x0 + 24, y0 + 66, 432, 40, ui.dv || ""); inp.placeholder = "Paste a code (AOE4S1:\u2026)"; inp.oninput = check; inp.onkeydown = (e) => { if (e.key === "Escape") close(); if (e.key === "Enter" && res.p) go_(); };
    rr(x0 + 24, y0 + 126, x0 + 456, y0 + 236, 14, "#262626");
    if (res.p) { const by = Object.fromEntries(songsOf({ custom_songs: [...(S.ed.custom_songs || []), ...res.p.custom] }).map((x) => [x[3], x]));
      presetSongs(res.p).slice(0, 3).forEach((x, j) => by[x] && songChip(by[x], x0 + 56 + j * 20, y0 + 158, 15)); text(x0 + 130, y0 + 150, res.p.name, 16, C.tx, true); text(x0 + 130, y0 + 171, "from code", 10, C.mu);
      const cnt = presetCounts(res.p); S.ages.forEach(([a], k) => { const on = !!((res.p.ages || {})[a] ?? a === S.agedata.default_age) && cnt[a], x = x0 + 40 + k * 102;
        oval(x, y0 + 204, x + 30, y0 + 234 - 0, on ? "#1e3c28" : "#2c2c2c"); text(x + 15, y0 + 219, ROMAN[k], 11, on ? C.acc : C.mu, true, "center"); text(x + 38, y0 + 219, `${cnt[a]}/${S.agedata.civs.length}`, 10, C.mu, true); }); }
    else text(x0 + 240, y0 + 181, res.err || "Paste a code to see the preset", 11, res.err ? "#e5534b" : C.mu, !!res.err, "center");
    button(x0 + 300, y0 + 252, x0 + 370, y0 + 282, "Cancel", close); const ib = button(x0 + 380, y0 + 252, x0 + 456, y0 + 282, "Import", () => res.p && go_(), true); if (!res.p) ib.style.opacity = .4;
    setTimeout(() => { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }, 0); });
  const go_ = () => { const u = clone(S.ed), p = { ...res.p, name: uniqueName(u, res.p.name) }; u.intro_presets = (u.intro_presets || []).concat([p]); applyPreset(u, p); ui.dialog = null; ui.dv = null; record(u); toast("Imported"); };
  redraw(); }
// ---- AOE4S_EDTEST: drive the editor like a user (synthetic pointer events) and record what happened
window.__errs = []; window.addEventListener("error", (e) => window.__errs.push(e.message + " @" + e.lineno)); window.addEventListener("unhandledrejection", (e) => window.__errs.push("rej " + (e.reason && (e.reason.stack || e.reason))));
async function edTest() {
  const out = []; const wait = (ms) => new Promise((r) => setTimeout(r, ms)); const ok = (c, m) => out.push((c ? "PASS " : "FAIL ") + m);
  const pg = () => $("age").getBoundingClientRect();
  const ptr = (type, x, y, tgt) => { const r = pg(); const e = new PointerEvent(type, { bubbles: true, clientX: r.left + x, clientY: r.top + y, button: 0, buttons: type === "pointerup" ? 0 : 1 }); (tgt || window).dispatchEvent(e); };
  const at = (x, y) => { const r = pg(), X = r.left + x, Y = r.top + y; const hs = [...$("age").querySelectorAll(".hit")].filter((e) => e.style.display !== "none" && (() => { const b = e.getBoundingClientRect(); return b.left <= X && X <= b.right && b.top <= Y && Y <= b.bottom; })()); return hs[hs.length - 1]; };
  const P = () => poolsOf(S.ed, age.k), d = S.agedata, civ = (i) => d.civs[i][0];
  openAge(d.default_age); await wait(400);
  out.push("dbg civ0=" + civ(0) + " js=" + J(P()[civ(0)]) + " rs=" + J(d.pools[d.default_age][civ(0)]) + " page=" + page + " k=" + age.k + " sizes=" + J(sizes.age) + " ed=" + J(S.ed).slice(0, 200));
  // 1) drag a tray song onto row 0 (French)
  const start = J(Object.fromEntries(S.ages.map(([a]) => [a, poolsOf(S.ed, a)]))); setPackOpen(true); await wait(500); const L = trayLayout(d, S.ed), t0 = L.chips.find((c) => !P()[civ(0)].includes(d.songs[c.i][3]));
  const before = P()[civ(0)].length; let h = at(t0.cx - 6, TY); ptr("pointerdown", t0.cx - 6, TY, h);
  for (let k = 1; k <= 8; k++) { ptr("pointermove", t0.cx - 6 + (230 - t0.cx) * k / 8, TY + (LT + 20 - TY) * k / 8); await wait(30); }
  out.push("press/drag " + J(age.press && age.press.src) + " " + J(age.drag && age.drag.xy) + " pgrect=" + J(pg()) + " cls=" + $("age").className + " frame=" + $("frame").style.cssText + " client=" + J($("client").getBoundingClientRect()) + " hits=" + $("age").querySelectorAll(".hit").length + " hit=" + (h && h.outerHTML.slice(0, 100)) + " bp=" + J((S.ed.intro_pools || {}).imperial && S.ed.intro_pools.imperial.french) + " defs=" + J(d.defs.french) + " keys=" + J(Object.keys((S.ed.intro_pools||{}).imperial||{}).slice(0,5)) + " t0=" + J(t0));
  ok(age.drop === 0, "drag over French highlights it (drop row " + age.drop + ")"); ptr("pointerup", 230, LT + 20); await wait(500);
  ok(P()[civ(0)].length === before + 1 && P()[civ(0)].includes(d.songs[t0.i][3]), `tray -> French added (${before} -> ${P()[civ(0)].length})`);
  // 2) move French's first chip to row 3
  const mv = P()[civ(0)][0], tg = [1, 2, 3, 4, 5, 6, 7].find((i) => !P()[civ(i)].includes(mv)), n3 = P()[civ(tg)].length, nf = P()[civ(0)].length, cyy = LT + RH / 2; h = at(205, cyy); ptr("pointerdown", 205, cyy, h);
  for (let k = 1; k <= 6; k++) { ptr("pointermove", 205 + 60 * k / 6, cyy + tg * STEP * k / 6); await wait(30); }
  ptr("pointerup", 265, cyy + tg * STEP); await wait(500);
  ok(P()[civ(tg)].includes(mv) && !P()[civ(0)].includes(mv) && P()[civ(tg)].length === n3 + 1 && P()[civ(0)].length === nf - 1, `row move French -> ${civ(tg)} (${n3} -> ${P()[civ(tg)].length}, French ${nf} -> ${P()[civ(0)].length})`);
  // 3) remove with the x badge
  // drag a chip out of its row = remove (1.0.9)
  { const m0 = P()[civ(tg)].length, yy = cyy + tg * STEP, xx = 205 + (m0 - 1) * 34; const hh = at(xx, yy); ptr("pointerdown", xx, yy, hh); for (let k = 1; k <= 5; k++) { ptr("pointermove", xx + 40 * k, yy - 100 * k / 5 - 20); await wait(30); }
    ptr("pointerup", xx + 200, TY); await wait(500); ok(P()[civ(tg)].length === m0 - 1, `dragged out of its row = removed (${m0} -> ${P()[civ(tg)].length})`); }
  const n0 = P()[civ(0)].length; h = at(205, cyy); h.dispatchEvent(new MouseEvent("mouseenter")); await wait(50); const xb = at(216, cyy - 11); xb && xb.click(); await wait(500);
  ok(P()[civ(0)].length === n0 - 1, `x badge removes (${n0} -> ${P()[civ(0)].length})`);
  // 4) undo x3 restores, redo once
  out.push("undo depth " + ED.undo.length + " stack " + J(ED.undo.concat([ED.cur]).map((s) => poolsOf({ ...S.ed, ...s }, d.default_age)[civ(0)].length)) + " cur keys " + J(Object.keys(ED.cur)) + " ip? " + J(Object.keys(ED.undo[0].intro_pools || {}))); const want = J(ED.undo[0] && ED.undo[0].intro_pools); for (let k = 0; k < 4; k++) { undoRedo(true); await wait(400); out.push("u" + k + " depth " + ED.undo.length + "/" + ED.redo.length + " drag " + !!age.drag + " fr " + P()[civ(0)].length); }
  ok(J(Object.fromEntries(S.ages.map(([a]) => [a, poolsOf(S.ed, a)]))) === start, "Ctrl+Z x4 back to the start"); if (!out[out.length-1].startsWith("PASS")) out.push("now " + J(poolsOf(S.ed, d.default_age)[civ(0)]) + " " + J(poolsOf(S.ed, d.default_age)[civ(3)]) + " start " + start.slice(0, 0) + J(JSON.parse(start)[d.default_age][civ(0)]) + J(JSON.parse(start)[d.default_age][civ(3)])); undoRedo(false); await wait(400); ok(P()[civ(0)].length === before + 1, "Ctrl+Y redoes the add");
  undoRedo(true); await wait(400);
  // 5) age on/off on an age with songs and on an empty one
  const a2 = S.ages.find(([a]) => a !== d.default_age && !ageEmpty(S.ed, a)), a3 = S.ages.find(([a]) => ageEmpty(S.ed, a));
  const on0 = agesOn(S.ed)[d.default_age]; setAgeOn(d.default_age, !on0); await wait(400); ok(agesOn(S.ed)[d.default_age] === !on0, "age switch flips");
  setAgeOn(d.default_age, on0); await wait(400); if (a3) { setAgeOn(a3[0], true); await wait(300); ok(!agesOn(S.ed)[a3[0]], "empty age can't be switched on"); }
  // 6) presets: new, switch to Default, back, share -> import round trip
  const cur = S.ed.intro_preset; savePreset("Test preset"); await wait(400); ok(S.ed.intro_preset === "Test preset", "new preset saved + current");
  switchPreset("Default"); await wait(400); ok(S.ed.intro_preset === "Default" && J(poolsOf(S.ed, d.default_age)[civ(0)]) === J(sorted(S.ed, d.defs[civ(0)])), "switch to Default resets the lists");
  switchPreset("Test preset"); await wait(400); ok(S.ed.intro_preset === "Test preset", "switch back");
  await sharePreset(); await wait(200); const code = window.__lastCode || ""; ok(code.startsWith("AOE4S1:"), "share makes an AOE4S1 code (" + code.length + " chars)");
  let dp = null; try { dp = await invoke("decode_preset", { code }); } catch (e) { out.push("decode err " + e); }
  ok(dp && J(dp.pools) === J(presetFromUser(S.ed, "x").pools), "code decodes to the same lists");
  try { await invoke("decode_preset", { code: "AOE4S1:garbage" }); ok(false, "bad code rejected"); } catch (e) { ok(String(e).includes("damaged"), "bad code rejected: " + e); }
  if (cur) { switchPreset(cur); await wait(400); }
  // 7) emblem state persists (intros.json)
  setPackOpen(false); await wait(400); ok(S.ed.intro_pack_open === false, "emblem closed saved"); setPackOpen(true); await wait(400); ok(S.ed.intro_pack_open === true, "emblem open saved");
  out.push("errors: " + window.__errs.slice(0, 6).join(" | ")); out.push("save+refresh ms " + Math.round(ED.ms || 0));
  await invoke("dbg", { s: out.join("\n") }); await wait(200); W_.close();
}
async function shotState(x) {   // AOE4S_OPEN extras for screenshots
  const d = S.agedata; if (!x) return;
  if (x === "drag") { age.drag = { song: d.songs[2], src: ["tray", 2], xy: [262, LT + STEP + 26] }; age.drop = 1; redraw(); }
  if (x === "tip") { const L = trayLayout(d, S.ed), c = L.chips[3], sg = d.songs[c.i]; tip.show(`${sg[1]} \u2014 ${sg[2]}`, [c.cx - c.r, TY - c.r - 3, c.cx + c.r, TY + c.r + 3], false); }
  if (x === "menu") { ui.pmenu = true; redraw(); }
  if (x === "name") nameDialog("New preset", "My preset", () => {});
  if (x === "import") { const code = await invoke("encode_preset", { p: presetFromUser(S.ed, "Capstar's intros") }); ui.dv = code; importDialog(); setTimeout(() => { const i = document.querySelector("#intros input"); if (i) i.dispatchEvent(new Event("input")); }, 200); }
}
async function domDump() { await new Promise((r) => setTimeout(r, 800)); const ks = [...$("age").children].map((e) => e.className + (e.className === "glowf" ? "(" + e.style.left + "," + getComputedStyle(e).opacity + "," + getComputedStyle(e).backgroundImage.slice(0, 60) + "," + getComputedStyle(e).backgroundSize + "," + getComputedStyle(e).backgroundPosition + ")" : e.className === "chip" ? "@" + e.style.left : ""));
  const i = ks.findIndex((k) => k.startsWith("glowf")); await invoke("dbg", { s: ks.slice(Math.max(0, i - 4), i + 4).join("\n") }); }

// ---- M3 Add a song: drop Spotify songs/links anywhere on the age page (or the Add a song window) -> YOURS. One undo per add.
const TRK = /(?:open\.spotify\.com\/(?:intl-[a-z-]+\/)?track\/|spotify:track:)([A-Za-z0-9]{22})/g, META = {};
const trackIds = (t) => [...new Set([...String(t || "").matchAll(TRK)].map((m) => m[1]))];
const haveUris = () => songsOf(S.ed).map((x) => x[3]);
const EVT = window.__TAURI__.event, toAdd = (m, err) => EVT.emitTo("add", "say", [m, !!err]).catch(() => {});
function addSongs(items) {
  const u = clone(S.ed), have = new Set(haveUris()), cs = [...(u.custom_songs || [])], fresh = [];
  for (const it of items || []) if (it && /^spotify:track:[A-Za-z0-9]{22}$/.test(it.uri) && !have.has(it.uri)) { have.add(it.uri); fresh.push(it); cs.push({ uri: it.uri, name: String(it.name || "Song").slice(0, 80), artist: String(it.artist || "").slice(0, 80) }); }
  const L = page === "age" && S.agedata ? trayLayout(S.agedata, S.ed) : null, at = L ? [L.plus.cx, TY] : [IW / 2, 120];
  if (!fresh.length) { const m = items && items.length ? (items.length > 1 ? "Already in YOURS" : "Already added") : "No songs found"; if (page === "age") hint(m, ...at); toAdd(m); return 0; }
  u.custom_songs = cs; u.intro_pack_open = false; age.tray = "yours"; record(u); invoke("cache_covers", { items: fresh });
  fresh.forEach((it) => delete covers[it.uri]); setTimeout(() => fresh.forEach((it) => delete covers[it.uri]) || redraw(), 2500);
  const m = fresh.length > 1 ? `Added ${fresh.length} songs to YOURS` : `Added \u201c${fresh[0].name}\u201d`; if (page === "age") hint(m, ...at); toAdd(m);
  setTimeout(() => EVT.emitTo("add", "have", haveUris()).catch(() => {}), 50); return fresh.length;
}
async function dropText(t) {
  const ids = trackIds(t); if (!ids.length) { if (page === "age") hint("Drop a Spotify song or song link", IW / 2, 120); return; }
  const have = new Set(haveUris()), known = ids.map((i) => "spotify:track:" + i).filter((u) => META[u] || have.has(u)), miss = ids.filter((i) => !META["spotify:track:" + i] && !have.has("spotify:track:" + i));
  let got = []; if (miss.length) { let v; try { v = await invoke("sp", { kind: "tracks", arg: miss.join(",") }); } catch (e) { v = null; }
    if (v === "login") { hint("Log in to Spotify in AoE4 Spotify to add songs", IW / 2, 120); toAdd("Log in to Spotify in AoE4 Spotify first", true); return; } got = Array.isArray(v) ? v : []; }
  got.forEach((it) => META[it.uri] = it);
  addSongs(ids.map((i) => META["spotify:track:" + i] || (have.has("spotify:track:" + i) ? { uri: "spotify:track:" + i } : null)).filter(Boolean));
}
EVT.listen("add-songs", (e) => addSongs(e.payload)); EVT.listen("add-drop", (e) => dropText(e.payload));
EVT.listen("add-meta", (e) => (e.payload || []).forEach((it) => META[it.uri] = it));
EVT.listen("add-ready", () => EVT.emitTo("add", "have", haveUris()));
let dragN = 0; const setOver = (v) => { if (age.dropOver !== v) { age.dropOver = v; tip.hide(); redraw(); } };
document.addEventListener("dragenter", (e) => { e.preventDefault(); if (page !== "age") return; dragN++; setOver(true); });
document.addEventListener("dragover", (e) => { e.preventDefault(); if (page === "age") e.dataTransfer.dropEffect = "copy"; else e.dataTransfer.dropEffect = "none"; });
document.addEventListener("dragleave", () => { if (page === "age" && --dragN <= 0) { dragN = 0; setOver(false); } });
document.addEventListener("drop", (e) => { e.preventDefault(); dragN = 0; setOver(false); if (page !== "age") return;
  dropText(e.dataTransfer.getData("text/plain") || e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text")); });
// M3 test: AOE4S_ADDTEST -> synthetic drags/drops + Add a song window flow, results to dbg
async function addTest() {
  const R = [], ok = (n, c) => R.push((c ? "PASS " : "FAIL ") + n), w = (ms) => new Promise((r) => setTimeout(r, ms)), cnt = () => (S.ed.custom_songs || []).length, und = ED.undo.length;
  const dt = (t) => { const d = new DataTransfer(); if (t) d.setData("text/plain", t); return d; }, fire = (ty, t) => document.getElementById("age").dispatchEvent(new DragEvent(ty, { bubbles: true, cancelable: true, dataTransfer: dt(t) }));
  const rid = () => Array.from({ length: 22 }, () => "abcdefghijkLMNOPQ0123456789"[Math.random() * 27 | 0]).join(""), A = rid(), B = rid(), n0 = cnt();
  invoke("dbg", { s: "SHOT idle" }); await w(1200);
  fire("dragenter"); await w(60); ok("drag over age page: YOURS shows DROP TO ADD + pill", document.getElementById("age").innerText.includes("DROP TO ADD") && document.getElementById("age").innerText.includes("Drop to add to YOURS"));
  invoke("dbg", { s: "SHOT dragover" }); await w(1400);
  fire("dragleave"); await w(60); ok("leave: highlight gone, idle hint back", !document.getElementById("age").innerText.includes("DROP TO ADD") && document.getElementById("age").innerText.includes("or drop songs here"));
  fire("dragenter"); fire("drop", `https://open.spotify.com/track/${A}?si=x\r\nhttps://open.spotify.com/intl-de/track/${B}\nspotify:track:${A}`); await w(400);
  ok("drop 2 links -> both added to YOURS", cnt() === n0 + 2 && haveUris().includes("spotify:track:" + A) && haveUris().includes("spotify:track:" + B));
  ok("no civ pool changed", !J(S.ed.intro_pools || {}).includes(A));
  ok("tray shows Yours view", S.ed.intro_pack_open === false);
  invoke("dbg", { s: "SHOT dropped" }); await w(1200);
  undoRedo(true); await w(150); ok("one undo removes the whole drop", cnt() === n0); undoRedo(false); await w(150); ok("redo brings both back", cnt() === n0 + 2);
  fire("drop", `spotify:track:${A}`); await w(250); ok("dropping again: no duplicate", cnt() === n0 + 2);
  fire("drop", "https://open.spotify.com/album/" + "3".repeat(22)); await w(150); ok("non-track drop ignored", cnt() === n0 + 2);
  await invoke("open_add"); await w(1500); invoke("dbg", { s: "SHOT addwin" }); await w(900);
  EVT.emitTo("add", "test", ["menu"]); await w(500); invoke("dbg", { s: "SHOT addmenu" }); await w(900);
  EVT.emitTo("add", "test", ["pick", "p1"]); await w(500); invoke("dbg", { s: "SHOT addlist" }); await w(900);
  EVT.emitTo("add", "test", ["zone", 1]); await w(300); invoke("dbg", { s: "SHOT addzone" }); await w(900); EVT.emitTo("add", "test", ["zone", 0]);
  const n1 = cnt(); await new Promise((r) => { const un = EVT.listen("add-songs", () => { setTimeout(r, 200); }); EVT.emitTo("add", "test", ["click", 0]); setTimeout(r, 1500); });
  META["spotify:track:" + "6".repeat(22)] = { uri: "spotify:track:" + "6".repeat(22), name: "Battle at the Gate", artist: "Yasunori Nishiki" };
  await dropText("https://open.spotify.com/track/" + "6".repeat(22)); await w(300);
  ok("song dragged from the window list -> YOURS (meta, no lookup)", haveUris().includes("spotify:track:" + "6".repeat(22)) && (S.ed.custom_songs || []).some((c) => c.name === "Battle at the Gate"));
  invoke("dbg", { s: "ADDTEST " + JSON.stringify(R) + " undo+" + (ED.undo.length - und) });
}
