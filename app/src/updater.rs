//! Updates (1.0.9 updater.py).
use super::*;

// ---- updates (1.0.9 updater.py): GitHub release Setup .exe, size + SHA-256 checked, silent in-place install
pub fn ver_t(v: &str) -> Vec<u32> { let mut n: Vec<u32> = v.split(|c: char| !c.is_ascii_digit()).filter(|x| !x.is_empty()).take(3).map(|x| x.parse().unwrap_or(0)).collect(); n.resize(3, 0); n }
pub fn latest() -> Result<Option<serde_json::Value>, String> {
    let api = launcher::test_env("AOE4S_UPDATE_API").unwrap_or_else(|| "https://api.github.com/repos/Capstar1/aoe4-spotify/releases/latest".into());
    let v: serde_json::Value = ureq::get(&api).set("User-Agent", "aoe4-spotify").set("Accept", "application/vnd.github+json").timeout(Duration::from_secs(8)).call().map_err(|e| e.to_string())?.into_json().map_err(|e| e.to_string())?;
    let tag = v["tag_name"].as_str().unwrap_or("");
    if ver_t(tag) <= ver_t(env!("CARGO_PKG_VERSION")) { return Ok(None); }
    let Some(a) = v["assets"].as_array().and_then(|a| a.iter().find(|a| a["name"].as_str().unwrap_or("").to_lowercase().ends_with(".exe"))) else { return Ok(None) };
    let dg = a["digest"].as_str().unwrap_or("");
    Ok(Some(serde_json::json!({ "version": tag.trim_start_matches(['v', 'V']), "url": a["browser_download_url"], "size": a["size"], "sha256": dg.split("sha256:").nth(1).unwrap_or("") })))
}
pub fn download(info: &serde_json::Value, dest: &std::path::Path, mut progress: impl FnMut(f64)) -> Result<(), String> {
    use sha2::Digest; use std::io::{Read, Write};
    let part = dest.with_extension("part");
    let r = (|| -> Result<(), String> {
        let resp = ureq::get(info["url"].as_str().unwrap_or("")).set("User-Agent", "aoe4-spotify").timeout(Duration::from_secs(120)).call().map_err(|e| e.to_string())?;
        let total = info["size"].as_u64().filter(|n| *n > 0).or_else(|| resp.header("Content-Length").and_then(|s| s.parse().ok())).unwrap_or(0);
        let mut rd = resp.into_reader(); let mut f = std::fs::File::create(&part).map_err(|e| e.to_string())?;
        let mut h = sha2::Sha256::new(); let mut got = 0u64; let mut buf = vec![0u8; 65536];
        loop { let n = rd.read(&mut buf).map_err(|e| e.to_string())?; if n == 0 { break; } f.write_all(&buf[..n]).map_err(|e| e.to_string())?; h.update(&buf[..n]); got += n as u64; if total > 0 { progress((got as f64 / total as f64).min(1.0)); } }
        drop(f);
        if let Some(sz) = info["size"].as_u64().filter(|n| *n > 0) { if got != sz { return Err(format!("size mismatch ({got} of {sz} bytes)")); } }
        let want = info["sha256"].as_str().unwrap_or(""); let hx: String = h.finalize().iter().map(|b| format!("{b:02x}")).collect();
        if !want.is_empty() && !hx.eq_ignore_ascii_case(want) { return Err("checksum mismatch".into()); }
        std::fs::rename(&part, dest).map_err(|e| e.to_string())
    })();
    let _ = std::fs::remove_file(&part); r
}
pub fn run_setup(setup: &std::path::Path, relaunch: bool) {
    let lg = format!("/LOG={}", launcher::data_dir().join("update_setup.log").display());
    let mut a = vec!["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]; a.push(if relaunch { "/RELAUNCH=1" } else { "/FROMSWITCHER=1" });
    let mut c = std::process::Command::new(setup); c.args(&a).arg(&lg);
    for (k, _) in std::env::vars() { let l = k.to_lowercase(); if l.starts_with("steam") || l.starts_with("steam_") { c.env_remove(k); } }
    if !relaunch { use std::os::windows::process::CommandExt; c.creation_flags(0x0800_0000); }
    match c.spawn() { Ok(_) => launcher::log(&format!("Update: running {}", setup.display())), Err(e) => launcher::log(&format!("Update: could not start setup: {e}")) }
}
/// Update pill (panel): check at start; "↓ Update x" downloads with progress and installs (relaunches the panel).
#[tauri::command]
pub async fn check_update(app: tauri::State<'_, Arc<AppState>>) -> Result<String, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || match latest() {
        Ok(Some(i)) => { let v = i["version"].as_str().unwrap_or("").to_string(); *a.upd.lock().unwrap() = serde_json::json!({ "phase": "avail", "info": i }); format!("\u{2193} Update {v}") }
        Ok(None) => "Up to date".into(), Err(_) => "Couldn't check".into() }).await.map_err(|e| e.to_string())
}
#[tauri::command]
pub fn start_update(app: tauri::State<Arc<AppState>>) {
    let a = app.inner().clone(); let u = a.upd.lock().unwrap().clone();
    if !matches!(u["phase"].as_str(), Some("avail" | "error")) || u["info"].is_null() { return; }
    if launcher::aoe_running() { *a.upd.lock().unwrap() = serde_json::json!({ "phase": "error", "msg": "Close Age of Empires IV to update", "info": u["info"] }); return; }   // setup won't install mid-game
    *a.upd.lock().unwrap() = serde_json::json!({ "phase": "dl", "pct": 0, "info": u["info"] });
    std::thread::spawn(move || {
        let info = u["info"].clone(); let dest = std::env::temp_dir().join(format!("AoE4 Spotify Setup {}.exe", info["version"].as_str().unwrap_or("")));
        let a2 = a.clone();
        match download(&info, &dest, |f| { a2.upd.lock().unwrap()["pct"] = serde_json::json!((f * 100.0) as i64); }) {
            Ok(_) => { *a.upd.lock().unwrap() = serde_json::json!({ "phase": "run", "info": info }); run_setup(&dest, true); std::thread::sleep(Duration::from_millis(400)); std::process::exit(0); }
            Err(e) => { launcher::log(&format!("Update failed: {e}")); *a.upd.lock().unwrap() = serde_json::json!({ "phase": "error", "msg": "Update failed \u{2013} retry", "info": info }); }
        }
    });
}
pub static PENDING_SETUP: Mutex<Option<PathBuf>> = Mutex::new(None);
/// Switcher (started with the game): newer release -> download in the background; install silently once no match
/// is on and the game is closed (setup refuses while AoE4 runs). Same 6 h no-retry mark as 1.0.9.
pub fn auto_update(app: Arc<AppState>) {
    let Ok(Some(info)) = latest() else { return };
    let v = info["version"].as_str().unwrap_or("").to_string(); let mark = app.dir.join("auto_update.json");
    let last: serde_json::Value = std::fs::read_to_string(&mark).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    if last["v"] == serde_json::json!(v) && wall() - last["t"].as_f64().unwrap_or(0.0) < 6.0 * 3600.0 { launcher::log(&format!("Auto-update: {v} was already installed recently but this is still {} - not retrying for now", env!("CARGO_PKG_VERSION"))); return; }
    launcher::log(&format!("Auto-update: {v} available - downloading in the background"));
    let dest = std::env::temp_dir().join(format!("AoE4.Spotify.Setup-{v}.exe"));
    if let Err(e) = download(&info, &dest, |_| {}) { launcher::log(&format!("Auto-update: download failed ({e}) - trying again next launch")); return; }
    let _ = std::fs::write(&mark, serde_json::json!({ "v": v, "t": wall() }).to_string());
    launcher::log(&format!("Auto-update: {v} ready - installing between matches, after the game closes"));
    *PENDING_SETUP.lock().unwrap() = Some(dest);
}
pub fn install_pending(app: &AppState) {
    if app.status.lock().unwrap().in_match { return; }     // never mid-match
    if let Some(p) = PENDING_SETUP.lock().unwrap().take() { run_setup(&p, false); }
}
