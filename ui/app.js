// M1 UI: two pages in ONE fixed-size window. A switch only toggles which page is shown (no resize = no blank frame).
const $ = (id) => document.getElementById(id);
const invoke = (c, a) => window.__TAURI__.core.invoke(c, a);
const ROMAN = ["I", "II", "III", "IV"];
let last = null;

function show(page) {
  const t0 = performance.now();
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("on", p.id === page));
  requestAnimationFrame(() => { $("perf").textContent = `page switch ${(performance.now() - t0).toFixed(1)} ms`; });
}
$("go-intros").onclick = () => show("intros");
$("back").onclick = () => show("main");
document.addEventListener("keydown", (e) => { if ((e.key === "Escape" || e.key === "Backspace") && $("intros").classList.contains("on")) show("main"); });

$("spbtn").onclick = () => invoke(lastS && lastS.spotify.logged_in ? "logout" : "login");
$("real").onchange = e => invoke("set_real", { on: e.target.checked });
let lastS = null;
function render(s) {
  lastS = s; const sp = s.spotify;
  $("sptxt").textContent = sp.busy ? "Spotify: waiting for browser login..." : sp.logged_in ? "Spotify: logged in" : "Spotify: not logged in (1.1)";
  $("spbtn").textContent = sp.logged_in ? "Log out" : "Log in"; $("spbtn").disabled = sp.busy;
  $("real").checked = sp.real; $("real").disabled = !sp.logged_in && !sp.real;
  $("mode").textContent = sp.real ? "REAL playback" : "dry run"; $("mode").classList.toggle("live", sp.real);
  const st = s.status, set = s.settings;
  $("gdot").classList.toggle("on", st.in_match);
  $("gtxt").textContent = st.in_match ? `${st.game}: in a match${st.age ? " (" + st.age + ")" : ""}` : st.watching ? `${st.game}: watching log` : `${st.game}: log not found`;
  $("plist").innerHTML = s.ages.map(([k, label]) => {
    const uri = set.playlists[k] || ""; const id = uri.split(":").pop();
    const name = set.playlist_names[id] || (uri.includes(":list:liked") ? "Liked Songs" : uri ? "Playlist" : "not set");
    return `<div class="pl${st.age === k ? " now" : ""}"><b>${label.replace(" Age", "")}</b><i>${name}</i></div>`;
  }).join("");
  $("pips").innerHTML = s.ages.map(([k], i) => `<span class="pip${set.intro_ages[k] !== false ? " on" : ""}">${ROMAN[i]}</span>`).join("");
  $("agecards").innerHTML = s.ages.map(([k, label], i) => `<div class="age${set.intro_ages[k] !== false ? " on" : ""}"><span class="num">${ROMAN[i]}</span><b>${label}</b></div>`).join("");
  const log = st.log.join("\n"); if (log !== last) { $("log").textContent = log; $("log").scrollTop = 1e9; last = log; }
}
async function tick() { try { render(await invoke("get_state")); } catch (e) { $("perf").textContent = "core: " + e; } setTimeout(tick, 500); }
tick();