// Add a song window (1.0.9 add_dialog + M3 playlists / drop zone). Songs are added by the main window (one undo step per add).
const { invoke } = window.__TAURI__.core, EV = window.__TAURI__.event;
const $ = (id) => document.getElementById(id), R = { items: [], have: new Set(), seq: 0, lists: null, cur: null };
const TRK = /(?:open\.spotify\.com\/(?:intl-[a-z-]+\/)?track\/|spotify:track:)([A-Za-z0-9]{22})/g;
const ids = (t) => [...new Set([...String(t || "").matchAll(TRK)].map((m) => m[1]))];
function say(t, err) { $("msg").textContent = t; $("msg").className = err ? "err" : ""; }
function paint() {
  const L = $("list"); L.innerHTML = "";
  R.items.forEach((it) => { const r = document.createElement("div"), ad = R.have.has(it.uri); r.className = "r" + (ad ? " ad" : ""); r.draggable = !ad;
    r.innerHTML = `${it.img ? `<img class="t" src="${it.img}" draggable="false">` : `<div class="t"></div>`}<div class="n"></div><div class="a"></div><div class="s">${ad ? "\u2713 Added" : "+ Add"}</div>`;
    r.querySelector(".n").textContent = it.name; r.querySelector(".a").textContent = it.artist; 
    r.onclick = () => { if (!ad) add([it]); };
    r.ondragstart = (e) => { const l = "https://open.spotify.com/track/" + it.uri.split(":").pop(); e.dataTransfer.setData("text/plain", l); e.dataTransfer.setData("text/uri-list", l); e.dataTransfer.effectAllowed = "copy"; EV.emitTo("main", "add-meta", [it]); };
    L.appendChild(r); });
}
function add(items) { EV.emitTo("main", "add-songs", items); }
async function api(kind, arg) { let v; try { v = await invoke("sp", { kind, arg: arg || "" }); } catch (e) { say(String(e), true); return null; }
  if (v === "login") { say("Log in to Spotify in AoE4 Spotify first", true); return null; } return v; }
let job = 0;
$("q").addEventListener("input", () => { clearTimeout(job); const q = $("q").value.trim();
  if (ids(q).length) { say("Press Enter to add the pasted song"); return; } if (!q) { say("Click a song to add it"); return; }
  job = setTimeout(async () => { const s = ++R.seq; say("Searching\u2026"); const v = await api("search", q); if (s !== R.seq || !v) return; R.items = v; R.cur = null; $("pln").textContent = "Your playlists"; paint(); say(v.length ? "Click a song to add it" : "No songs found"); }, 350); });
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter") { const l = ids($("q").value); if (l.length) { EV.emitTo("main", "add-drop", $("q").value); $("q").value = ""; } } if (e.key === "Escape") window.__TAURI__.window.getCurrentWindow().close(); });
$("np").onclick = async () => { const v = await api("playing"); if (!v) return; if (!v.length) return say("Nothing is playing on Spotify", true); add(v); setTimeout(() => window.__TAURI__.window.getCurrentWindow().close(), 150); };
$("pl").onclick = async (e) => { e.stopPropagation(); const m = $("menu"); if (m.style.display === "block") { m.style.display = "none"; return; }
  if (!R.lists) { say("Loading your playlists\u2026"); R.lists = await api("playlists"); if (!R.lists) return; say("Click a song to add it"); }
  m.innerHTML = ""; R.lists.forEach((p) => { const d = document.createElement("div"); d.className = p.id === R.cur ? "cur" : ""; d.innerHTML = "<span></span><small></small>";
    d.firstChild.textContent = p.name; d.lastChild.textContent = p.n == null ? "" : p.n; d.onclick = () => pick(p); m.appendChild(d); }); m.style.display = "block"; };
document.addEventListener("click", () => $("menu").style.display = "none");
async function pick(p) { $("menu").style.display = "none"; R.cur = p.id; $("pln").textContent = p.name; const s = ++R.seq; say("Loading\u2026");
  const v = await api("plist", p.id); if (s !== R.seq || !v) return; R.items = v; $("list").scrollTop = 0; paint(); say(v.length ? "Click a song to add it" : "This playlist has no songs"); }
// dropping onto the window (Spotify drags its song links as text)
let dc = 0; const zone = $("zone"), own = () => document.querySelector(".r.dragging");
document.addEventListener("dragenter", (e) => { e.preventDefault(); dc++; zone.classList.add("on"); zone.textContent = "Release to add"; });
document.addEventListener("dragover", (e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; });
document.addEventListener("dragleave", () => { if (--dc <= 0) { dc = 0; off(); } });
function off() { zone.classList.remove("on"); zone.textContent = "Drop Spotify songs or links here"; }
document.addEventListener("drop", (e) => { e.preventDefault(); dc = 0; off(); const t = e.dataTransfer.getData("text/plain") || e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text");
  if (ids(t).length) EV.emitTo("main", "add-drop", t); else say("Drop a Spotify song or song link", true); });
document.addEventListener("dragend", () => { dc = 0; off(); });
EV.listen("have", (e) => { R.have = new Set(e.payload || []); paint(); });
EV.listen("say", (e) => say(e.payload[0], e.payload[1]));
EV.listen("test", (e) => { const [k, a] = e.payload; if (k === "pick") pick(R.lists.find((p) => p.id === a)); if (k === "menu") $("pl").click(); if (k === "zone") { zone.classList.toggle("on", !!a); zone.textContent = a ? "Release to add 2 songs" : "Drop Spotify songs or links here"; } if (k === "click") $("list").children[a].click(); if (k === "q") { $("q").value = a; $("q").dispatchEvent(new Event("input")); } });
EV.emitTo("main", "add-ready", null);
