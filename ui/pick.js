// 1.0.9 list_picker, pick page (picker.py): Your playlists grid (Liked Songs first) with search, Paste link (paste / drop),
// your app lists, Use button. Opened by the panel for an age row, After match playlist, or Victory / Defeat (songs too).
const { invoke } = window.__TAURI__.core, Wn = window.__TAURI__.window.getCurrentWindow();
const $ = (id) => document.getElementById(id), W = 420, GT = 79.5, GAP = 10, GP = 4, GR = GT + 42, GH = 241, COLS = 4, LIKED = "aoe4s:list:liked";
const P = { info: {}, state: "load", items: [], sel: null, sc: 0, err: "", use: false };
const RE_PL = /(?:open\.spotify\.com\/(?:intl-[a-z-]+\/)?playlist\/|spotify:playlist:)([A-Za-z0-9]{22})/;
const RE_TR = /(?:open\.spotify\.com\/(?:intl-[a-z-]+\/)?track\/|spotify:track:)([A-Za-z0-9]{22})/;
const trunc = (t, n) => t.length <= n ? t : t.slice(0, n - 1) + "\u2026";
function parseLink(t) { const m = RE_PL.exec(t || ""); if (m) return "spotify:playlist:" + m[1]; if (P.info.tracks) { const r = RE_TR.exec(t || ""); if (r) return "spotify:track:" + r[1]; } return null; }
async function finish(uri, name, img) {
  if (!name && uri.startsWith("spotify:")) {      // pasted link: look up its name / cover for the panel row
    try { const r = await invoke("sp", { kind: uri.startsWith("spotify:track:") ? "tracks" : "plmeta", arg: uri.split(":").pop() }); const it = Array.isArray(r) ? r[0] : null; if (it) { name = it.name; img = it.img || ""; } } catch (e) {}
  }
  await invoke("pick_done", { uri, name: name || "", img: img || "" }); Wn.close();
}
function shown() { const f = $("sq").value.trim().toLowerCase(); return P.items.filter((it) => !f || it.name.toLowerCase().includes(f)); }
const gmax = () => Math.max(0, Math.ceil(shown().length / COLS) * GR + GP - 6 - GH);
function liked() { return `<div class="im" style="background:linear-gradient(135deg,#4527d6,#9cc3e6);display:flex;align-items:center;justify-content:center"><svg width="40" height="40" viewBox="0 0 100 100"><path d="M50 69 L31.2 50 A10.5 10.5 0 1 1 50 40 A10.5 10.5 0 1 1 68.8 50 Z" fill="#fff" transform="translate(0,-6)"/></svg></div>`; }
function gdraw() {
  const g = $("grid"); g.innerHTML = ""; const msg = (a, b, btn) => { const d = document.createElement("div"); d.id = "gmsg"; d.style.top = (GH / 2 - 14 - 9) + "px";
    d.innerHTML = `<div style="font:700 12.5px 'Segoe UI'">${a}</div>` + (b ? `<div style="font:400 10.5px 'Segoe UI';color:#9a9a9a;margin-top:4px">${b}</div>` : ""); g.appendChild(d);
    if (btn) { const x = document.createElement("div"); x.className = "btn"; Object.assign(x.style, { left: (364 / 2 - 52) + "px", top: (GH / 2 - 14 + 40) + "px", width: "104px", height: "30px" }); x.textContent = btn[0]; x.onclick = btn[1]; g.appendChild(x); } };
  if (P.state !== "ok") { ({ load: () => msg("Loading your playlists\u2026"), login: () => msg("Log in to Spotify first", "Use Log in in the panel"), off: () => msg("Can't reach Spotify", "", ["Retry", load]) })[P.state](); return; }
  const items = shown(); if (!items.length) { const d = document.createElement("div"); d.id = "gmsg"; d.style.top = (GH / 2 - 14 - 9) + "px"; d.style.font = "400 12px 'Segoe UI'"; d.style.color = "#9a9a9a"; d.textContent = "No matches"; g.appendChild(d); return; }
  items.forEach((it, i) => { const r = Math.floor(i / COLS), c = i % COLS, x = GP + c * (GT + GAP), y = GP + r * GR - P.sc; if (y + GR < -2 || y > GH + 2) return;
    const t = document.createElement("div"); t.className = "tile" + (it.uri === P.sel ? " sel" : ""); t.style.left = x + "px"; t.style.top = y + "px"; t.style.height = GR + "px";
    t.innerHTML = (it.liked ? liked() : it.img ? `<img class="im" src="${it.img}" draggable="false">` : `<div class="im note">\u266a</div>`) +
      `<div class="hv"></div><div class="ring"></div><div class="bd"><svg width="20" height="20"><polyline points="5.8,10.4 8.8,13.2 14.4,7.2" fill="none" stroke="#121212" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg></div><div class="nm"></div><div class="ct"></div>`;
    t.querySelector(".nm").textContent = it.name; const n = it.n || 0; t.querySelector(".ct").textContent = `${n} song${n === 1 ? "" : "s"}`;
    t.onmousedown = () => { P.sel = it.uri; P.err = ""; gdraw(); draw(); }; t.ondblclick = () => { P.sel = it.uri; useSel(); }; g.appendChild(t); });
  const mx = gmax(); if (mx > 0) { const th = Math.max(28, GH * GH / (GH + mx)), ty = (GH - th) * (P.sc / mx); const b = document.createElement("div"); b.id = "sb"; b.style.top = ty + "px"; b.style.height = th + "px";
    b.onmousedown = (e) => { const y0 = e.clientY, s0 = P.sc; b.classList.add("d"); const mv = (ev) => { P.sc = Math.max(0, Math.min(mx, s0 + (ev.clientY - y0) * mx / Math.max(1, GH - th))); gdraw(); };
      const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); gdraw(); }; document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up); e.stopPropagation(); };
    g.appendChild(b); }
}
$("grid").addEventListener("wheel", (e) => { P.sc = Math.max(0, Math.min(gmax(), P.sc + (e.deltaY / 100) * GR * 0.6)); gdraw(); e.preventDefault(); }, { passive: false });
function useSel() { const it = P.items.find((x) => x.uri === P.sel); if (!it || P.use) return; finish(it.uri, it.name, it.img); }
function draw() { if (B.on) return;
  $("title").textContent = P.info.title || "Playlist";
  const hint = $("hint"); hint.textContent = P.err || (P.drag ? "Drop here" : `Paste a link or drag a ${P.info.tracks ? "playlist or song" : "playlist"} from Spotify`); hint.style.color = P.err ? "#e5675f" : P.drag ? "#1DB954" : "#9a9a9a";
  const d = $("drop"); d.style.background = P.drag ? "#1b2a20" : "#181818"; $("dropi").style.background = P.drag ? "#1DB954" : "#9a9a9a";
  d.innerHTML = `<svg width="364" height="46"><rect x="0.7" y="0.7" width="362.6" height="44.6" rx="9.3" fill="none" stroke="${P.drag ? "#1DB954" : "#4a4a4a"}" stroke-width="1.4" stroke-dasharray="5 4"/></svg>`;
  // your app lists (1.0.9 'Your lists': up to 4, not the current one)
  let y = 313 + 184; const L = $("lists"); L.innerHTML = "";
  // make your own card: one button (tile, title, grey subline, chevron) -> builder
  const cur = P.info.current || "", curL = cur.startsWith("aoe4s:list:") && !cur.endsWith(":liked") ? (P.info.custom_lists || {})[cur.split(":").pop()] : null, mk = $("mk"); mk.style.top = y + "px";
  mk.innerHTML = `<div class="a" id="mkt" style="left:11px;top:9px;width:36px;height:36px;border-radius:9px;background:#1f4630"></div>` +
    `<div class="t" style="left:61px;top:19px;font:700 12.5px 'Segoe UI'"></div><div class="t" style="left:61px;top:37px;font:400 10.5px 'Segoe UI';color:#9a9a9a">Saved in this app, not Spotify</div>` +
    `<svg class="a" id="mkc" style="left:367px;top:20px" width="10" height="14"><polyline points="2.5,2 7.5,7 2.5,12" fill="none" stroke="#9a9a9a" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  mk.children[1].textContent = curL ? "Edit \u00b7 " + trunc(curL.name || "My list", 22) : "Make your own";
  if (curL) invoke("cover", { uri: cur }).then((u) => { if (u) $("mkt").outerHTML = `<img class="a" src="${u}" style="left:11px;top:9px;width:36px;height:36px;border-radius:9px">`; });
  else $("mkt").innerHTML = `<div class="mk" style="left:7px;top:7px;width:22px;height:22px;background:#1DB954;-webkit-mask-image:image-set(url(img/mk_pk_plus22@1.png) 1x,url(img/mk_pk_plus22@1.5.png) 1.5x)"></div>`;
  mk.onmouseenter = () => { $("mkc").style.left = "369px"; $("mkc").firstChild.setAttribute("stroke", "#1DB954"); const t = $("mkt"); if (t.tagName === "DIV") t.style.background = "#24553a"; };
  mk.onmouseleave = () => { $("mkc").style.left = "367px"; $("mkc").firstChild.setAttribute("stroke", "#9a9a9a"); const t = $("mkt"); if (t.tagName === "DIV") t.style.background = "#1f4630"; };
  mk.onclick = () => openBuilder(curL ? cur : null);
  y += 68;
  const lists = Object.entries(P.info.custom_lists || {}).filter(([k, v]) => v && typeof v === "object" && "aoe4s:list:" + k !== P.info.current && k !== "liked").slice(-4);
  if (lists.length) { const h = document.createElement("div"); h.className = "t"; Object.assign(h.style, { left: "20px", top: (y + 8) + "px", font: "700 10.5px 'Segoe UI'", color: "#9a9a9a" }); h.textContent = "Your lists"; L.appendChild(h); y += 20;
    for (const [k, v] of lists) { const r = document.createElement("div"); r.className = "ls"; r.style.top = y + "px"; r.innerHTML = `<div class="ph"></div><div class="t" style="left:48px;top:20px;font:700 12px 'Segoe UI'"></div><div class="t" style="right:14px;top:20px;font:400 10.5px 'Segoe UI';color:#9a9a9a">${(v.tracks || []).length} songs</div>`;
      r.children[1].textContent = trunc(v.name || "My list", 28); invoke("cover", { uri: "aoe4s:list:" + k }).then((u) => { if (u) r.children[0].outerHTML = `<img src="${u}">`; });
      r.onclick = () => finish("aoe4s:list:" + k, v.name || "My list", ""); L.appendChild(r); y += 46; } }
  else y -= 0;
  y += 6 - (lists.length ? 0 : 0);
  const sel = P.items.find((x) => x.uri === P.sel), u = $("use"); u.style.top = (y) + "px"; u.className = "btn" + (sel ? "" : " off");
  u.textContent = P.err && !sel ? P.err : sel ? "Use " + trunc(sel.name, 34) : "Pick a playlist"; u.onclick = sel ? useSel : null;
  const H = y + 48 + 16; if (H !== P.H) { P.H = H; invoke("resize", { w: W, h: H }); }
}
async function load() {
  P.state = P.items.length ? "ok" : "load"; gdraw();
  try { const r = await invoke("sp", { kind: "playlists", arg: "" });
    if (r === "login") { P.state = "login"; }
    else { P.items = r.map((p) => ({ uri: p.id === "liked" ? LIKED : "spotify:playlist:" + p.id, name: p.name || "Playlist", n: p.n || 0, img: p.img || "", liked: p.id === "liked" })); P.state = "ok";
      const cur = P.info.current; if (P.sel == null && P.items.some((x) => x.uri === cur)) P.sel = cur; }
  } catch (e) { P.state = "off"; }
  gdraw(); draw();
}
function okLink() { const v = $("ent").value.trim(); if (!v) { P.err = "Paste a link first"; return draw(); } const u = parseLink(v); if (u) finish(u); else { P.err = `Not a Spotify ${P.info.tracks ? "playlist or song" : "playlist"} link`; draw(); } }
$("ok").onclick = okLink; $("ent").onkeydown = (e) => { if (e.key === "Enter") okLink(); };
$("ent").addEventListener("paste", () => setTimeout(() => { const u = parseLink($("ent").value.trim()); if (u) finish(u); }, 10));
$("sq").addEventListener("input", () => { P.sc = 0; gdraw(); }); $("sq").onkeydown = (e) => { if (e.key === "Escape" && $("sq").value) { $("sq").value = ""; P.sc = 0; gdraw(); e.stopPropagation(); } };
let dragN = 0;
document.addEventListener("dragenter", (e) => { e.preventDefault(); dragN++; if (!P.drag) { P.drag = true; B.on ? bdraw() : draw(); } });
document.addEventListener("dragleave", () => { if (--dragN <= 0) { dragN = 0; P.drag = false; B.on ? bdraw() : draw(); } });
document.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
document.addEventListener("drop", (e) => { e.preventDefault(); if (B.on) return bDrop(e); dragN = 0; P.drag = false; const t = e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain"); const u = parseLink(t);
  if (u) finish(u); else { P.err = `Not a Spotify ${P.info.tracks ? "playlist or song" : "playlist"} link`; draw(); } });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !B.on) Wn.close(); });
(async () => { P.info = await invoke("pick_info"); const c = P.info.current || ""; if (c.startsWith("aoe4s:list:") && !c.endsWith(":liked") && (P.info.custom_lists || {})[c.split(":").pop()]) { draw(); openBuilder(c); } else { draw(); gdraw(); }
  await Wn.show(); await Wn.setFocus(); load(); })();
