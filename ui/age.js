// ---------- Age page (1.0.9 intros.py draw() for one age) + approved changes:
// either/or tray (no songs of your own: Octopath shown normally, no emblem; >=1: Octopath folds into the spiked
// emblem, one group at a time, a compact Yours count chip switches back) and the squeezed-chip stacking rule
// (normal order = right neighbour on top; hover ring / playing glow sit directly above their own chip, so the right
// neighbour covers them; the audio badge is a separate top-most item).
const LT = 178, RH = 40, GAP = 4, STEP = RH + GAP, CR = 14, ER = 23, EX = 57, TY = 119, LN = "#2e2e2e";
const AS = {}; fetch("img/age/sizes.json").then((r) => r.json()).then((j) => { Object.assign(AS, j); redraw(); });
const age = { k: null, sc: 0, tray: null, hovTray: null, song: null, busy: false, msg: null, msgT: 0 };
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
function trayLayout(d) {
  const NB = d.nb, U = d.songs.length - NB, W = IW, ysp = Math.min(50, 100 / Math.max(1, U)), yr = Math.max(9, Math.min(19, ysp * 0.45));
  const view = U === 0 ? "octo0" : (age.tray || "yours"), out = { view, chips: [], emblem: false, count: null };
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
function ageH() { return sizes.intros ? sizes.intros[1] : 586; }
function drawAge(s) {
  const d = s.agedata, H = introsH(s.ages.length, mainH(s.ages.length)); begin("age", IW, H);
  if (!d || !age.k) return H;
  const W = IW, BOT = H - 12, ai = s.ages.findIndex((a) => a[0] === age.k), lab = (s.ages[ai] || ["", ""])[1].replace(" Age", "");
  const pools = d.pools[age.k], civs = d.civs, byUri = Object.fromEntries(d.songs.map((x) => [x[3], x]));
  const maxSc = Math.max(0, civs.length * STEP - GAP - (BOT - LT)); age.sc = Math.max(0, Math.min(maxSc, age.sc));
  const on = s.intros[age.k].on, empty = !s.intros[age.k].n, isDef = age.k === d.default_age, same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  // list (clipped like the Tk covers: header above LT-4, bottom below BOT)
  const root = host, list = el("div", "a", { left: "0px", top: (LT - 4) + "px", width: W + "px", height: (BOT - LT + 4) + "px", overflow: "hidden" });
  list.addEventListener("wheel", (e) => { age.sc = Math.max(0, Math.min(maxSc, age.sc + Math.sign(e.deltaY) * 46)); redraw(); }, { passive: true });
  const inner = el("div", "a", { left: "0px", top: (-(LT - 4)) + "px", width: W + "px", height: H + "px" }); list.appendChild(inner); host = inner; host._w = W;
  const firstEmpty = civs.findIndex(([c]) => !(pools[c] || []).length), marks = [];
  civs.forEach(([civ, name], i) => {
    const y = LT + i * STEP - age.sc; if (y > BOT || y + RH < LT - 60) return;
    const cy = y + RH / 2, p = pools[civ] || [];
    rr(20, y, W - 32, y + RH, 10, C.card); const [fw, fh] = AS["flag_" + civ] || [30, 16];
    const f = el("img", "a", { left: "32px", top: (cy - fh / 2) + "px", width: fw + "px", height: fh + "px" }); f.srcset = `img/age/flag_${civ}@1.png 1x, img/age/flag_${civ}@1.5.png 1.5x`; f.src = `img/age/flag_${civ}@1.png`;
    text(72, cy, name, 12, C.tx, true);
    p.forEach((u, j) => { const sg = byUri[u]; if (!sg) return; const cx = 205 + j * 34; const c = songChip(sg, cx, cy, CR);
      const h = hit(oval(cx - 16, cy - 16, cx + 16, cy + 16, "transparent"), () => preview(sg, cx, cy)); h.title = sg[2] ? `${sg[1]} \u2014 ${sg[2]}` : sg[1];
      hov(h, () => { const x = aimg("xbadge", cx + 11, cy - 11); h._x = x; }, () => { h._x && h._x.remove(); });
      if (age.song === sg[0]) marks.push([c, cx, cy, CR]); });
    if (!p.length) { const o = oval(190, cy - 15, 220, cy + 15, null); o.style.border = "1px dashed #4b4b4b";
      if (i === firstEmpty) { text(205, cy, "+", 13, "#6e6e6e", false, "center"); text(232, cy, "Drag songs here", 10, "#646464"); } }
    if (isDef && !same(p, d.defs[civ])) aimg("undo_mu", W - 53, cy);
  });
  if (maxSc) { const vh = BOT - LT, th = Math.max(28, vh * vh / (vh + maxSc)), ty = LT + (vh - th) * age.sc / maxSc;
    rr(W - 28, LT, W - 24, BOT, 2, "#2a2a2a"); rr(W - 28, ty, W - 24, ty + th, 2, "#5a5a5a"); }
  marks.forEach(([c, cx, cy, r]) => { c.after(glow(cx, cy, r)); });          // glow right above its own chip
  marks.forEach(([c, cx, cy, r]) => glow(cx, cy, r, true));                   // badge: top of the list layer
  host = root;
  // header
  const bk = hit(oval(18, HY - 16, 50, HY + 16, "transparent"), () => { go("intros"); age.k = null; }); const bi = aimg("back", 34, HY);
  hov(bk, () => bi.srcset = bi.srcset.replaceAll("back@", "back_h@"), () => bi.srcset = bi.srcset.replaceAll("back_h@", "back@"));
  aimg(`badge${ai}_${on ? "on" : "off"}`, 78, HY); text(102, HY, lab, 18, C.tx, true);
  toggle(W - 38 - 44, HY - 12, on, 44, 24, null, empty);
  if (d.custom[age.k]) aimg("undo_mu", W - 22, HY);
  // tray
  rr(20, 70, W - 20, 162, 18, "#1a1a1a", LN); text(36, 81, "OCTOPATH", 8.5, C.mu, true);
  const L = trayLayout(d); text(L.div + 14, 81, "YOURS", 8.5, C.acc, true); el("div", "a", { left: L.div + "px", top: "84px", width: "1px", height: "66px", background: LN });
  if (L.emblem) { const e = aimg("emblem", EX, TY); const h = hit(oval(EX - ER, TY - ER, EX + ER, TY + ER, "transparent"), () => { age.tray = "octo"; redraw(); });
    h.title = `Octopath Traveler \u2014 ${d.nb} songs (click to show)`; hov(h, () => e.srcset = e.srcset.replaceAll("emblem@", "emblem_h@"), () => e.srcset = e.srcset.replaceAll("emblem_h@", "emblem@")); }
  const tmarks = [];
  L.chips.forEach(({ i, cx, r }) => {         // left to right: the right neighbour is drawn later = on top
    const sg = d.songs[i], c = songChip(sg, cx, TY, r);
    if (age.hovTray === i) c.after(ringAt(cx, TY, r + 3));                     // hover ring: directly above its own chip
    if (age.song === sg[0]) tmarks.push([c, cx, r]);
  });
  tmarks.forEach(([c, cx, r]) => c.after(glow(cx, TY, r)));
  if (L.count) { const { cx, r, n } = L.count, o = oval(cx - r - 0.5, TY - r - 0.5, cx + r + 0.5, TY + r + 0.5, null); o.style.border = "1.6px solid " + C.acc;
    text(cx, TY, String(n), 14, C.acc, true, "center"); const h = hit(oval(cx - r, TY - r, cx + r, TY + r, "transparent"), () => { age.tray = "yours"; redraw(); });
    h.title = `Your songs (${n}) \u2014 click to show`; hov(h, () => o.style.background = "rgba(29,185,84,.15)", () => o.style.background = "transparent"); }
  const pl = aimg("plus", L.plus.cx, TY, L.plus.r / 19), ph = hit(oval(L.plus.cx - L.plus.r, TY - L.plus.r, L.plus.cx + L.plus.r, TY + L.plus.r, "transparent"), () => hint("Add a song comes in M3", L.plus.cx, TY));
  hov(ph, () => pl.srcset = pl.srcset.replaceAll("plus@", "plus_h@"), () => pl.srcset = pl.srcset.replaceAll("plus_h@", "plus@"));
  // hit areas for tray chips (on top; z-order of the drawing is unaffected)
  L.chips.forEach(({ i, cx, r }, n) => { const sg = d.songs[i], nx = L.chips[n + 1];
    const right = nx && nx.cx - nx.r < cx + r ? (nx.cx - nx.r) : cx + r;   // a squeezed chip is only clickable where it is visible
    const h = hit(rr(cx - r, TY - r, right, TY + r, r, "transparent"), () => preview(sg, cx, TY)); h.style.borderRadius = right < cx + r ? `${r}px 0 0 ${r}px` : "50%";
    h.title = sg[2] ? `${sg[1]} \u2014 ${sg[2]}` : sg[1];
    hov(h, () => { if (age.hovTray !== i) { age.hovTray = i; redraw(); } }, () => { if (age.hovTray === i) { age.hovTray = null; redraw(); } }); });
  tmarks.forEach(([c, cx, r]) => glow(cx, TY, r, true));                      // audio badge: always on top of everything
  if (age.msg && Date.now() - age.msgT < 2600) { const [m, x, y] = age.msg, tw = measure(m, 10) + 20, x0 = Math.min(Math.max(8, x - tw / 2), W - 8 - tw), ty = Math.min(Math.max(8, y + 26), H - 32);
    rr(x0, ty, x0 + tw, ty + 24, 12, "#1c3a26", C.acc); text(x0 + tw / 2, ty + 12, m, 10, C.tx, false, "center"); }
  return H;
}
function ringAt(cx, cy, R) { const e = document.createElement("div"); e.className = "a"; Object.assign(e.style, { left: (cx - R - 0.75) + "px", top: (cy - R - 0.75) + "px", width: (2 * R + 1.5) + "px", height: (2 * R + 1.5) + "px", borderRadius: "50%", boxSizing: "border-box", border: "1.5px solid " + C.acc, pointerEvents: "none" }); return e; }
function hint(m, x, y) { age.msg = [m, x, y]; age.msgT = Date.now(); redraw(); setTimeout(redraw, 2650); }
async function preview(sg, cx, cy) {
  if (age.busy) return; const action = age.song === sg[0] ? "pause" : "play", prev = age.song;
  age.busy = true; age.song = action === "play" ? sg[0] : null; redraw();          // optimistic: the glow reacts on the click
  let res; try { res = await invoke("preview", { uri: action === "play" ? sg[3] : null }); } catch (e) { res = "err"; }
  age.busy = false;
  if (res === "login") { age.song = prev; hint("Log in to Spotify in AoE4 Spotify to preview", cx, cy); }
  else if (res !== "ok") { age.song = action === "play" ? (prev !== sg[0] ? prev : null) : prev; hint("Couldn't play - is Spotify (Premium) running?", cx, cy); }
  else redraw();
}
function openAge(k) { age.k = k; age.sc = 0; age.hovTray = null; render(S); go("age"); }
