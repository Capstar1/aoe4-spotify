// 1.0.9 list builder (picker.py open_builder / draw_build): app-only song list, max 100. Search (dropdown), add what's
// playing, paste links, drop from Spotify, drag rows to reorder, click to preview, x to remove, Ctrl+Z / Ctrl+Y, Save / Delete.
const RH = 48, VISN = 7, LT = 138, LB = LT + RH * VISN, MAXN = 100;
const B = { on: false, id: null, tracks: [], sc: 0, target: 0, undo: [], redo: [], toast: null, tjob: 0, res: [], sel: 0, busy: "", qjob: 0, delarm: false, pv: null, pvBusy: false, drag: null, ins: null, press: null };
const mkI = (n, sz, x, y, col, extra) => `<div class="mk" style="left:${x - sz / 2}px;top:${y - sz / 2}px;width:${sz}px;height:${sz}px;background:${col};-webkit-mask-image:image-set(url(img/mk_pk_${n}${sz}@1.png) 1x,url(img/mk_pk_${n}${sz}@1.5.png) 1.5x);${extra || ""}"></div>`;
const esc = (t) => String(t || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const coverOf = {};
function trackImg(t) { if (t.img) return t.img; const id = t.uri.split(":").pop(); if (!(id in coverOf)) { coverOf[id] = ""; invoke("cover", { uri: t.uri }).then((u) => { if (u) { coverOf[id] = u; bdraw(); } }); } return coverOf[id]; }
const maxSc = () => Math.max(0, B.tracks.length * RH - RH * VISN);
function openBuilder(uri) {
  const l = uri ? (P.info.custom_lists || {})[uri.split(":").pop()] : null;
  Object.assign(B, { on: true, id: l ? uri.split(":").pop() : null, tracks: ((l || {}).tracks || []).filter((t) => t && t.uri).map((t) => ({ ...t })), sc: 0, target: 0, undo: [], redo: [], toast: null, res: [], busy: "", delarm: false, drag: null, ins: null });
  $("pickp").style.display = "none"; $("build").style.display = "block"; bbuild(); $("bname").value = (l || {}).name || "My list"; bdraw();
}
function back() { B.on = false; $("build").style.display = "none"; $("pickp").style.display = "block"; P.err = ""; P.H = 0; draw(); gdraw(); }
function snapB() { B.undo.push(B.tracks.map((t) => ({ ...t }))); B.undo = B.undo.slice(-60); B.redo = []; }
function undoRedo(bk) { const a = bk ? B.undo : B.redo, b = bk ? B.redo : B.undo; if (!a.length) return toastB(bk ? "Nothing to undo" : "Nothing to redo");
  b.push(B.tracks.map((t) => ({ ...t }))); B.tracks = a.pop(); toastB(bk ? "Undone" : "Redone"); }
function toastB(msg, undo, ms = 3500) { B.toast = { msg, undo }; clearTimeout(B.tjob); if (ms) B.tjob = setTimeout(() => { B.toast = null; bdraw(); }, ms); bdraw(); }
function smooth() { const step = () => { const t = Math.max(0, Math.min(maxSc(), B.target)); B.target = t; const d = t - B.sc; if (Math.abs(d) < 0.6) { B.sc = t; bdraw(); return; } B.sc += d * 0.35; bdraw(); requestAnimationFrame(step); }; step(); }
const nOf = (n) => `${n} song${n === 1 ? "" : "s"}`;
async function addUris(uris, src) {
  const have = new Set(B.tracks.map((t) => t.uri)), uniq = [...new Set(uris)], nw = uniq.filter((u) => !have.has(u)), dup = uniq.length - nw.length, room = MAXN - B.tracks.length;
  if (!nw.length) return toastB(dup ? "Already in the list" : "Nothing to add"); if (room <= 0) return toastB("100 songs max");
  toastB("Adding\u2026", false, 0); let out = [];
  try { for (let k = 0; k < Math.min(nw.length, room); k += 50) { const r = await invoke("sp", { kind: "tracks", arg: nw.slice(k, Math.min(k + 50, room)).map((u) => u.split(":").pop()).join(",") }); if (Array.isArray(r)) out = out.concat(r); } } catch (e) {}
  const hv = new Set(B.tracks.map((t) => t.uri)), got = out.filter((t) => !hv.has(t.uri)).slice(0, MAXN - B.tracks.length);
  if (got.length) { snapB(); B.tracks = B.tracks.concat(got); invoke("cache_covers", { items: got }); B.target = maxSc(); smooth(); }
  toastB(got.length ? `Added ${nOf(got.length)}` + (dup ? ` \u00b7 ${dup} already in` : "") : "Couldn't add");
}
const TRS = /(?:spotify:track:|open\.spotify\.com\/(?:intl-[a-z-]+\/)?track\/)([A-Za-z0-9]{22})/g;
const parseTracks = (t) => [...new Set([...String(t || "").matchAll(TRS)].map((m) => "spotify:track:" + m[1]))];
async function addPlaying() { toastB("Checking what's playing\u2026", false, 0); try { const r = await invoke("sp", { kind: "playing", arg: "" }); if (Array.isArray(r) && r[0]) return addUris([r[0].uri]); } catch (e) {} toastB("Nothing playing"); }
async function addPaste() { let t = ""; try { t = await invoke("clip_text"); } catch (e) {} const u = parseTracks(t); if (u.length) addUris(u); else toastB("No song links in the clipboard"); }
function bDrop(e) { dragN = 0; P.drag = false; const u = parseTracks(e.dataTransfer.getData("text/uri-list") + "\n" + e.dataTransfer.getData("text/plain")); if (u.length) addUris(u); else { toastB("Drop songs (not playlists)"); } }
function search(now) { clearTimeout(B.qjob); const q = $("bse").value.trim(); if (q.length < 2) { B.res = []; B.busy = ""; return bdraw(); }
  const run = async () => { B.busy = "search"; bdraw(); let out = []; try { const r = await invoke("sp", { kind: "search", arg: q }); if (Array.isArray(r)) out = r.slice(0, 5); } catch (e) {}
    if ($("bse").value.trim() !== q) return; B.res = out; B.sel = 0; B.busy = ""; if (!out.length) toastB("No results"); bdraw(); };
  if (now) run(); else B.qjob = setTimeout(run, 350); }
function pickRes(i) { const r = B.res[i]; if (!r) return; if (B.tracks.some((t) => t.uri === r.uri)) return toastB("Already in the list");
  snapB(); B.tracks.push({ ...r }); invoke("cache_covers", { items: [r] }); B.target = maxSc(); smooth(); toastB(`Added \u201c${r.name.length > 28 ? r.name.slice(0, 27) + "\u2026" : r.name}\u201d`); }
function removeAt(i) { snapB(); const t = B.tracks.splice(i, 1)[0]; B.target = Math.min(B.target, maxSc()); B.sc = Math.min(B.sc, maxSc()); toastB(`Removed \u201c${t.name.length > 20 ? t.name.slice(0, 19) + "\u2026" : t.name}\u201d`, true, 5000); }
async function preview(uri) { if (B.pvBusy) return; const play = B.pv !== uri, prev = B.pv; B.pvBusy = true; B.pv = play ? uri : null; bdraw();
  let r = false; try { r = await invoke("preview", { uri: play ? uri : null }); } catch (e) { r = false; }
  B.pvBusy = false; if (r === "login") { B.pv = prev; toastB("Log in to Spotify to preview"); } else if (r !== "ok") { B.pv = play ? (prev === uri ? null : prev) : prev; toastB("Couldn't play \u2013 is Spotify running?"); } bdraw(); }
async function mosaic(tracks) {   // 1.0.9 save_mosaic: 2x2 of the first songs' covers (1 song: full art), 96 px
  const c = document.createElement("canvas"); c.width = c.height = 96; const g = c.getContext("2d"); g.fillStyle = "#2a2a2a"; g.fillRect(0, 0, 96, 96);
  const load = (src) => new Promise((res) => { const i = new Image(); i.crossOrigin = "anonymous"; i.onload = () => res(i); i.onerror = () => res(null); i.src = src; });
  const imgs = []; for (const t of tracks.slice(0, 4)) { const u = (await invoke("cover", { uri: t.uri })) || t.img; if (u) { const i = await load(u); if (i) imgs.push(i); } }
  try { if (imgs.length === 1) g.drawImage(imgs[0], 0, 0, 96, 96); else if (imgs.length) for (let k = 0; k < 4; k++) g.drawImage(imgs[k % imgs.length], (k % 2) * 48, Math.floor(k / 2) * 48, 48, 48); return c.toDataURL("image/png"); } catch (e) { return ""; }
}
async function saveList() { if (!B.tracks.length) return; const uri = await invoke("save_list", { id: B.id || "", name: $("bname").value, tracks: B.tracks, mosaic: await mosaic(B.tracks) });
  if (uri) finish(uri, $("bname").value.trim() || "My list", ""); }
function delList() { if (!B.delarm) { B.delarm = true; bdraw(); setTimeout(() => { if (B.delarm) { B.delarm = false; bdraw(); } }, 3000); return; } B.delarm = false; invoke("delete_list", { id: B.id }).then(() => Wn.close()); }
// ---- static parts (built once per open: the inputs keep focus / caret)
function bbuild() {
  const b = $("build"); b.innerHTML = `
  <div id="blist"></div><div class="a" id="bdd"></div>
  <div class="a" style="left:0;top:0;width:420px;height:137px;background:#121212"></div>
  <div class="a cb" id="bback" style="left:14px;top:30px;width:32px;height:32px;background:#2a2a2a">${mkI("back", 22, 16, 16, "#f2f2f2")}</div>
  <div class="a" id="bmos" style="left:56px;top:14px;width:64px;height:64px;border-radius:8px;background:#1f2a23;overflow:hidden"></div>
  <div class="a ib" style="left:132px;top:16px;width:268px;height:30px;border-radius:9px"></div><input class="bin" id="bname" style="left:144px;top:19px;width:246px;height:24px" maxlength="40" spellcheck="false">
  <div class="t" id="bsub" style="left:134px;top:55px;font:400 10.5px 'Segoe UI';color:#9a9a9a"></div>
  <div class="a ib" id="bsbox" style="left:20px;top:92px;width:304px;height:34px;border-radius:17px;border:1px solid #3a3a3a"></div><div id="bsic"></div>
  <input class="bin" id="bse" style="left:54px;top:98px;width:240px;height:22px" placeholder="Search songs" spellcheck="false"><div class="t" id="bbusy" style="right:108px;top:101px;color:#9a9a9a;font:12px 'Segoe UI'"></div>
  <div class="a cb ib" id="btp" style="left:330px;top:93px;width:32px;height:32px">${mkI("playing", 20, 16, 16, "#9a9a9a")}</div>
  <div class="a cb ib" id="btv" style="left:368px;top:93px;width:32px;height:32px">${mkI("paste", 20, 16, 16, "#9a9a9a")}</div>
  <div id="bfoot"></div>`;
  $("bback").onclick = back; $("btp").onclick = addPlaying; $("btv").onclick = addPaste;
  for (const [id, t] of [["btp", "Add what's playing"], ["btv", "Paste song links"]]) { const e = $(id); e.title = t; e.onmouseenter = () => { e.style.background = "#333333"; e.firstChild.style.background = "#f2f2f2"; }; e.onmouseleave = () => { e.style.background = "#2a2a2a"; e.firstChild.style.background = "#9a9a9a"; }; }
  const se = $("bse"); se.onfocus = se.onblur = () => bdraw();
  se.addEventListener("input", () => { const u = parseTracks(se.value); if (u.length) { se.value = ""; B.res = []; addUris(u); } else search(); });
  se.onkeydown = (e) => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { if (B.res.length) { B.sel = (B.sel + (e.key === "ArrowDown" ? 1 : -1) + B.res.length) % B.res.length; bdraw(); } e.preventDefault(); }
    else if (e.key === "Enter") { if (B.res.length) pickRes(B.sel); else search(true); }
    else if (e.key === "Escape") { if (B.res.length || se.value) { se.value = ""; B.res = []; bdraw(); e.stopPropagation(); } else back(); } };
  $("bname").onkeydown = (e) => { if (e.key === "Escape") back(); };
  $("blist").addEventListener("wheel", (e) => { if (!B.res.length) { B.target = Math.max(0, Math.min(maxSc(), B.target + (e.deltaY / 100) * RH * 1.5)); smooth(); } e.preventDefault(); }, { passive: false });
}
function bdraw() {
  if (!B.on) return; const tr = B.tracks, n = tr.length, L = $("blist"), sf = document.activeElement === $("bse");
  // header: mosaic (or note tile), counts
  const mo = $("bmos"); const ims = tr.slice(0, 4).map(trackImg).filter(Boolean);
  mo.innerHTML = !n ? mkI("note", 26, 32, 32, "#1DB954") : !ims.length ? "" : ims.length === 1 || n === 1 ? `<img src="${ims[0] || ""}" style="width:64px;height:64px;object-fit:cover">` :
    [0, 1, 2, 3].map((k) => `<img src="${ims[k % Math.max(1, ims.length)] || ""}" style="position:absolute;left:${(k % 2) * 32}px;top:${Math.floor(k / 2) * 32}px;width:32px;height:32px;object-fit:cover">`).join("");
  mo.style.background = n ? "#2a2a2a" : "#1f2a23";
  const mins = Math.floor(tr.reduce((a, t) => a + (t.ms || 0), 0) / 60000); $("bsub").textContent = n ? `${nOf(n)} \u00b7 ${mins} min` : "No songs yet";
  $("bsbox").style.borderColor = sf ? "#1DB954" : "#3a3a3a"; $("bsic").innerHTML = mkI("search", 18, 38, 109, sf ? "#1DB954" : "#9a9a9a"); $("bbusy").textContent = B.busy === "search" ? "\u2026" : "";
  // list
  L.innerHTML = "";
  if (n) {
    const first = Math.max(0, Math.floor(B.sc / RH)), last = Math.min(n, first + VISN + 2);
    for (let i = first; i < last; i++) { if (B.drag && B.drag.i === i) continue; const t = tr[i], ry = i * RH - B.sc, playing = B.pv === t.uri, r = document.createElement("div");
      r.className = "br"; r.style.top = (ry + 2) + "px"; r.style.background = playing ? "#17271d" : "transparent"; if (!playing) { r.onmouseenter = () => r.style.background = "#1f1f1f"; r.onmouseleave = () => r.style.background = "transparent"; }
      const dur = t.ms ? `${Math.floor(t.ms / 60000)}:${String(Math.floor(t.ms / 1000) % 60).padStart(2, "0")}` : "", im = trackImg(t);
      r.innerHTML = `<div class="t" style="left:16px;top:22px;transform:translate(-50%,-50%);font:${playing ? 700 : 400} 10.5px 'Segoe UI';color:${playing ? "#1DB954" : "#9a9a9a"}">${i + 1}</div>` +
        (playing ? `<div class="glw"></div>` : "") + (im ? `<img class="th" src="${im}" draggable="false">` : `<div class="th"></div>`) +
        `<div class="ov">${playing ? `<svg width="12" height="12"><rect x="1" y="1" width="3.6" height="10" rx="1" fill="#fff"/><rect x="7.4" y="1" width="3.6" height="10" rx="1" fill="#fff"/></svg>` : `<svg width="12" height="12"><polygon points="2.5,0.5 2.5,11.5 11.5,6" fill="#fff"/></svg>`}</div>` +
        (playing ? `<div class="eqb"><i style="left:4.5px"></i><i style="left:8.1px;animation-delay:-.3s"></i><i style="left:11.7px;animation-delay:-.55s"></i></div>` : "") +
        `<div class="t nm" style="left:76px;top:15px;max-width:262px;overflow:hidden;text-overflow:ellipsis;font:700 11.5px 'Segoe UI';color:${playing ? "#1DB954" : "#f2f2f2"}">${esc(t.name || "Song")}</div>` +
        `<div class="t" style="left:76px;top:30px;max-width:262px;overflow:hidden;text-overflow:ellipsis;font:400 10px 'Segoe UI';color:#9a9a9a">${esc(t.artist)}</div>` +
        `<div class="t d1" style="right:14px;top:22px;font:400 10.5px 'Segoe UI';color:#9a9a9a">${dur}</div><div class="t d2" style="right:38px;top:22px;font:400 10.5px 'Segoe UI';color:#9a9a9a">${dur}</div>` +
        `<div class="hd">${mkI("handle", 18, 9, 9, "#9a9a9a")}</div><div class="rm">${mkI("x", 18, 11, 11, "#f2f2f2")}</div>`;
      r.querySelector(".rm").onclick = (e) => { e.stopPropagation(); removeAt(i); }; r.querySelector(".rm").title = ""; 
      r.onmousedown = (e) => { if (e.target.closest(".rm")) return; B.press = { i, x: e.clientX, y: e.clientY, off: e.clientY - (LT + ry) }; };
      L.appendChild(r); }
    if (B.drag && B.ins != null) { const iy = B.ins * RH - B.sc, t = tr[B.drag.i], gy = B.drag.y - B.drag.off - LT, im = trackImg(t);
      L.insertAdjacentHTML("beforeend", `<div class="a" style="left:20px;top:${iy - 1}px;width:380px;height:2px;border-radius:1px;background:#1DB954"></div><div class="a" style="left:18.5px;top:${iy - 3.5}px;width:7px;height:7px;border-radius:50%;background:#1DB954"></div>
        <div class="a" style="left:60px;top:${gy}px;width:320px;height:40px;border-radius:10px;background:#2b2b2d;border:1px solid #3a3a3c;box-shadow:0 6px 14px rgba(0,0,0,.6);pointer-events:none">
        ${im ? `<img src="${im}" style="position:absolute;left:7px;top:5px;width:28px;height:28px;border-radius:5px">` : ""}<div class="t" style="left:45px;top:13px;font:700 11.5px 'Segoe UI';max-width:260px;overflow:hidden;text-overflow:ellipsis">${esc(t.name)}</div><div class="t" style="left:45px;top:27px;font:400 10px 'Segoe UI';color:#9a9a9a">${esc(t.artist)}</div></div>`); }
    if (maxSc() > 0) { const vh = RH * VISN, th = Math.max(28, vh * vh / (n * RH)), ty = (vh - th) * B.sc / maxSc();
      L.insertAdjacentHTML("beforeend", `<div class="a" id="bsbl" style="left:402px;top:0;width:16px;height:${vh}px;cursor:pointer"><div class="a" style="left:6px;top:2px;width:4px;height:${vh - 4}px;border-radius:2px;background:#222"></div><div class="a" id="bsbt" style="left:5px;top:${ty + 2}px;width:6px;height:${th - 4}px;border-radius:3px;background:#4a4a4a"></div></div>`);
      const lane = $("bsbl"); lane.onmouseenter = () => $("bsbt").style.background = "#6a6a6a"; lane.onmouseleave = () => { if (!B.sb) $("bsbt").style.background = "#4a4a4a"; };
      lane.onmousedown = (e) => { const y = e.clientY - LT; if (!(ty <= y && y <= ty + th)) { B.sc = B.target = Math.max(0, Math.min(maxSc(), (y - th / 2) * maxSc() / Math.max(1, vh - th))); } B.sb = [e.clientY, B.sc]; bdraw(); e.stopPropagation(); }; }
    if (P.drag) L.insertAdjacentHTML("beforeend", `<svg class="a" style="left:16px;top:0" width="388" height="336"><rect x="0.7" y="0.7" width="386.6" height="334.6" rx="11.3" fill="none" stroke="#1DB954" stroke-width="1.4" stroke-dasharray="5 4"/></svg>`);
  } else {
    const hl = P.drag; L.innerHTML = `<div class="a" style="left:20px;top:8px;width:380px;height:208px;border-radius:14px;background:${hl ? "#16261c" : "#151a16"}"></div><svg class="a" style="left:20px;top:8px" width="380" height="208"><rect x="0.7" y="0.7" width="378.6" height="206.6" rx="13.3" fill="none" stroke="${hl ? "#1DB954" : "#3f5a48"}" stroke-width="1.4" stroke-dasharray="5 4"/></svg>
      <img src="img/empty_art@1.png" srcset="img/empty_art@1.png 1x, img/empty_art@1.5.png 1.5x" class="a" style="left:140px;top:24px;width:140px;height:92px">
      <div class="t" style="left:210px;top:142px;transform:translate(-50%,-50%);font:700 12.5px 'Segoe UI'">Drop songs from Spotify</div><div class="t" style="left:210px;top:164px;transform:translate(-50%,-50%);font:400 10.5px 'Segoe UI';color:#9a9a9a">or search, add what's playing, paste links</div>`;
  }
  // results dropdown (floats over the list)
  const dd = $("bdd"); dd.innerHTML = ""; dd.style.display = B.res.length ? "block" : "none";
  if (B.res.length) { const h = B.res.length * 44 + 8; Object.assign(dd.style, { left: "20px", top: "132px", width: "304px", height: h + "px", borderRadius: "10px", background: "#262628", border: "1px solid #3a3a3c", boxShadow: "0 6px 14px rgba(0,0,0,.6)", zIndex: 5 });
    B.res.forEach((r, j) => { const inl = tr.some((t) => t.uri === r.uri), e = document.createElement("div"); e.className = "sr"; e.style.left = "3px"; e.style.top = (3 + j * 44) + "px"; e.style.width = "296px"; e.style.background = j === B.sel ? "#2f2f31" : "#262628";
      e.innerHTML = `${r.img ? `<img src="${r.img}" style="position:absolute;left:6px;top:7px;width:28px;height:28px;border-radius:5px">` : ""}<div class="t" style="left:44px;top:15px;max-width:200px;overflow:hidden;text-overflow:ellipsis;font:700 11px 'Segoe UI'">${esc(r.name)}</div><div class="t" style="left:44px;top:30px;max-width:200px;overflow:hidden;text-overflow:ellipsis;font:400 9.5px 'Segoe UI';color:#9a9a9a">${esc(r.artist)}</div>
        <div class="a" style="left:265px;top:10px;width:22px;height:22px;border-radius:50%;background:${inl ? "#2a2a2a" : "#1c3a26"}">${mkI(inl ? "note" : "plus", 16, 11, 11, inl ? "#9a9a9a" : "#1DB954")}</div>`;
      e.onmouseenter = () => { if (B.sel !== j) { B.sel = j; bdraw(); } }; e.onmousedown = (ev) => { ev.preventDefault(); pickRes(j); }; dd.appendChild(e); }); }
  // toast + footer
  const f = $("bfoot"); let html = ""; const fy = LB + 50;
  if (B.toast) { const tw = measureT(B.toast.msg) + 28 + (B.toast.undo ? 48 : 0);
    html += `<div class="a" style="left:20px;top:${LB + 8}px;width:${tw}px;height:32px;border-radius:16px;background:#2b2b2d;border:1px solid #3a3a3c"></div><div class="t" style="left:34px;top:${LB + 24}px;font:400 10.5px 'Segoe UI'">${esc(B.toast.msg)}</div>` +
      (B.toast.undo ? `<div class="t" id="bundo" style="left:${20 + tw - 14 - 30}px;top:${LB + 24}px;font:700 10.5px 'Segoe UI';color:#1DB954;pointer-events:auto;cursor:pointer">Undo</div>` : ""); }
  html += `<div class="cb" id="bsave" style="left:300px;top:${fy}px;width:100px;height:32px;background:${n ? "#1DB954" : "#2a2a2a"};color:${n ? "#121212" : "#6c6c6c"};font:700 12px 'Segoe UI';cursor:${n ? "pointer" : "default"}">Save</div>` +
    `<div class="cb" id="bcancel" style="left:202px;top:${fy}px;width:88px;height:32px;background:#2a2a2a;font:400 12px 'Segoe UI'">Cancel</div>`;
  if (B.id && (P.info.custom_lists || {})[B.id]) html += `<div class="cb" id="bdel" style="left:20px;top:${fy}px;width:102px;height:32px;background:${B.delarm ? "#e5675f" : "#2a2a2a"};border:${B.delarm ? "0" : "1.2px solid #5a3330"};color:${B.delarm ? "#121212" : "#e5675f"};font:700 11.5px 'Segoe UI'">${B.delarm ? "Confirm" : "Delete list"}</div>`;
  if (!n) html += `<div class="t" style="left:350px;top:${fy + 46}px;transform:translate(-50%,-50%);font:400 9.5px 'Segoe UI';color:#9a9a9a">Add a song to save</div>`;
  f.innerHTML = html; const H = n ? fy + 32 + 14 : fy + 32 + 30;
  if (n) { $("bsave").onclick = saveList; $("bsave").onmouseenter = (e) => e.target.style.background = "#1ed760"; $("bsave").onmouseleave = (e) => e.target.style.background = "#1DB954"; }
  $("bcancel").onclick = () => Wn.close(); $("bcancel").onmouseenter = (e) => e.target.style.background = "#333"; $("bcancel").onmouseleave = (e) => e.target.style.background = "#2a2a2a";
  if ($("bdel")) { $("bdel").onclick = delList; if (!B.delarm) { $("bdel").onmouseenter = (e) => e.target.style.background = "#3a2222"; $("bdel").onmouseleave = (e) => e.target.style.background = "#2a2a2a"; } }
  if ($("bundo")) $("bundo").onclick = () => undoRedo(true);
  if (H !== P.H) { P.H = H; invoke("resize", { w: W, h: H }); }
}
const MCX = document.createElement("canvas").getContext("2d"); function measureT(s) { MCX.font = '400 10.5px "Segoe UI"'; return MCX.measureText(s).width; }
const insAt = (cy) => Math.max(0, Math.min(B.tracks.length, Math.round((cy - LT + B.sc) / RH)));
document.addEventListener("mousemove", (e) => {
  if (!B.on) return;
  if (B.sb) { const vh = RH * VISN, th = Math.max(28, vh * vh / (B.tracks.length * RH)); B.sc = B.target = Math.max(0, Math.min(maxSc(), B.sb[1] + (e.clientY - B.sb[0]) * maxSc() / Math.max(1, vh - th))); return bdraw(); }
  const p = B.press; if (!p) return; if (!B.drag && Math.abs(e.clientY - p.y) + Math.abs(e.clientX - p.x) < 5) return;
  if (!B.drag) B.drag = { i: p.i, off: p.off, y: e.clientY }; B.drag.y = Math.max(LT - 20, Math.min(LB - 20, e.clientY)); B.ins = insAt(e.clientY); document.body.style.cursor = "grabbing"; bdraw();
  if ((e.clientY < LT + 24 || e.clientY > LB - 24) && !B.ajob) { const auto = () => { B.ajob = 0; if (!B.drag) return; const yy = B.drag.y, dv = yy < LT + 24 ? -9 : yy > LB - 44 ? 9 : 0; if (!dv) return;
    B.sc = B.target = Math.max(0, Math.min(maxSc(), B.sc + dv)); B.ins = insAt(yy); bdraw(); B.ajob = setTimeout(auto, 30); }; auto(); }
});
document.addEventListener("mouseup", (e) => {
  if (!B.on) return; document.body.style.cursor = "";
  if (B.sb) { B.sb = null; return bdraw(); }
  const p = B.press, dg = B.drag; B.press = null; B.drag = null;
  if (dg) { const i = dg.i, j = B.ins; B.ins = null; if (j != null && j !== i && j !== i + 1) { snapB(); const t = B.tracks.splice(i, 1)[0]; B.tracks.splice(j > i ? j - 1 : j, 0, t); } return bdraw(); }
  if (p && e.target.closest && e.target.closest(".br") && !e.target.closest(".rm") && !e.target.closest(".hd")) preview(B.tracks[p.i].uri);
});
document.addEventListener("mousedown", (e) => { if (B.on && B.res.length && !e.target.closest("#bdd") && e.target.id !== "bse") { B.res = []; bdraw(); } });
document.addEventListener("keydown", (e) => {
  if (!B.on) return; const f = document.activeElement;
  if (e.ctrlKey && /^[zZyY]$/.test(e.key)) { if (f === $("bname") || (f === $("bse") && $("bse").value)) return; undoRedo(/[zZ]/.test(e.key)); e.preventDefault(); }
  else if (e.key === "Escape" && f !== $("bse") && f !== $("bname")) back();
});
