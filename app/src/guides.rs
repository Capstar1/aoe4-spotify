//! Windows after login: good to go, the shared-app access guide, Your Spotify app; login.
use super::*;

/// 1.0.9 setup_status for the "You're good to go" window.
pub fn spotify_installed() -> bool {
    let ad = std::env::var("APPDATA").unwrap_or_default(); let la = std::env::var("LOCALAPPDATA").unwrap_or_default();
    std::path::Path::new(&ad).join(r"Spotify\Spotify.exe").is_file() || std::path::Path::new(&la).join(r"Packages\SpotifyAB.SpotifyMusic_zpdnekdrzrea0").is_dir()
        || std::process::Command::new("reg").args(["query", r"HKCU\Software\Classes\spotify"]).output().map(|o| o.status.success()).unwrap_or(false)
}
pub fn show_gtg(app: &tauri::AppHandle, a: &Arc<AppState>) {
    let (ok, web) = { let mut s = a.spotify.lock().unwrap(); let ok = s.logged_in(); (ok, if ok { s.web().ok() } else { None }) };
    let name = web.and_then(|w| w.get("/me").ok()).filter(|(c, _)| *c == 200).and_then(|(_, v)| v["display_name"].as_str().or(v["id"].as_str()).map(String::from));
    *a.gtg.lock().unwrap() = serde_json::json!({ "ok": ok, "name": name, "steam": launcher::launch_option_is_set(), "spotify_app": spotify_installed() });
    let h = app.clone(); let _ = app.run_on_main_thread(move || small_window(&h, "gtg", "gtg.html", 400.0, 470.0));
}
#[tauri::command]
pub fn gtg_info(app: tauri::State<Arc<AppState>>) -> serde_json::Value { app.gtg.lock().unwrap().clone() }
/// Fix: put the Steam launch option back (Steam closes and reopens), then re-check.
#[tauri::command]
pub async fn gtg_fix(app: tauri::State<'_, Arc<AppState>>) -> Result<serde_json::Value, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || { launcher::with_steam_closed(launcher::set_launch_option); let st = launcher::launch_option_is_set(); a.gtg.lock().unwrap()["steam"] = serde_json::json!(st); a.gtg.lock().unwrap().clone() }).await.map_err(|e| e.to_string())
}

#[tauri::command]
pub fn login(h: tauri::AppHandle, app: tauri::State<Arc<AppState>>) { do_login(h, app.inner().clone()); }
/// 1.0.9 login(): browser login, then the "You're good to go" window.
pub fn do_login(h: tauri::AppHandle, a: Arc<AppState>) {
    if a.busy.swap(true, Ordering::SeqCst) { return; }
    std::thread::spawn(move || {
        push(&a.status, "Spotify: opening login in your browser...".into());
        let cid = a.spotify.lock().unwrap().client_id();   // lock released before the browser wait
        let r = Spotify::login_code(&cid).and_then(|(c, v)| a.spotify.lock().unwrap().login_finish(&c, &v));
        sync_logged(&a);
        push(&a.status, match r { Ok(_) => "Spotify: logged in".into(), Err(e) => format!("Spotify login: {e}") });
        a.busy.store(false, Ordering::SeqCst);
        after_login(&h, &a);
    });
}

// ---- 1.0.9 access.py: shared-app access request (capstar.app relay) and the 'Not invited yet' guide
pub const ACCESS_URL: &str = "https://capstar.app/api/aoe4-spotify/access-request";
pub const ACCESS_GAP: f64 = 600.0;   // one request per 10 min per install
/// "ok", "blocked" (Spotify refuses this account: not on the shared app's user list, dev-mode 403) or None (offline / not logged in).
pub fn access_status(a: &AppState) -> Option<&'static str> {
    let w = { let mut sp = a.spotify.lock().unwrap(); if !sp.logged_in() { return None; } sp.web().ok()? };
    let (c, r) = w.get("/me").ok()?; if c == 200 { return Some("ok"); }
    let t = r.to_string().to_lowercase();
    if c == 403 && (t.contains("not registered") || t.contains("developer dashboard") || t.contains("user may not be registered")) { Some("blocked") } else { None }
}
/// After a login: good to go, or the not-invited guide when the shared app refuses this account.
pub fn after_login(h: &tauri::AppHandle, a: &Arc<AppState>) { if access_status(a) == Some("blocked") { show_access(h); } else { show_gtg(h, a); } }
pub fn show_access(h: &tauri::AppHandle) { let h2 = h.clone(); let _ = h.run_on_main_thread(move || small_window(&h2, "access", "access.html", 500.0, 701.0)); }
/// Asked for access earlier: check once on start (1.0.9 pending_access).
pub fn pending_access(h: tauri::AppHandle, a: Arc<AppState>) {
    if read_user(&a.dir)["access_pending"].as_bool() != Some(true) { return; }
    std::thread::spawn(move || match access_status(&a) { Some("ok") => { set_user_(&a, "access_pending", serde_json::Value::Null); show_gtg(&h, &a); } Some("blocked") => show_access(&h), _ => {} });
}
#[tauri::command]
pub fn access_info(app: tauri::State<Arc<AppState>>) -> serde_json::Value {
    let u = read_user(&app.dir); let last = u["access_last"].as_f64().unwrap_or(0.0);
    serde_json::json!({ "pending": u["access_pending"].as_bool() == Some(true) && wall() - last < ACCESS_GAP, "on": true, "light": windows_light() })
}
/// Windows app theme (1.0.9 windows_light): HKCU ...\Themes\Personalize AppsUseLightTheme = 1.
/// Read straight from the registry (no `reg` process) and reused for 10 s.
pub(crate) fn windows_light() -> bool {
    static LAST: Mutex<Option<(std::time::Instant, bool)>> = Mutex::new(None);
    let mut l = LAST.lock().unwrap();
    if let Some((t, v)) = *l { if t.elapsed() < Duration::from_secs(10) { return v; } }
    #[link(name = "advapi32")] extern "system" { fn RegGetValueW(k: isize, sub: *const u16, val: *const u16, flags: u32, ty: *mut u32, data: *mut u32, len: *mut u32) -> i32; }
    let w = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
    let (mut d, mut n) = (0u32, 4u32);
    // HKEY_CURRENT_USER = 0x80000001, RRF_RT_REG_DWORD = 0x10
    let r = unsafe { RegGetValueW(0x8000_0001u32 as i32 as isize, w(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize").as_ptr(), w("AppsUseLightTheme").as_ptr(), 0x10, std::ptr::null_mut(), &mut d, &mut n) };
    let v = r == 0 && d == 1; *l = Some((std::time::Instant::now(), v)); v
}
/// The 'Send request' button: one POST {email[, name]} to the relay (no key in the app). sent | wait | bad | busy | down | error.
#[tauri::command]
pub async fn access_send(app: tauri::State<'_, Arc<AppState>>, email: String) -> Result<String, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let e = email.trim().to_string(); let at = e.find('@').unwrap_or(0);
        if e.len() > 100 || at == 0 || !e[at + 1..].contains('.') || e.chars().any(|c| c.is_whitespace() || c == ',' || c == ';') || e.ends_with('.') { return "bad".to_string(); }
        let u = read_user(&a.dir); if wall() - u["access_last"].as_f64().unwrap_or(0.0) < ACCESS_GAP { return "wait".into(); }
        let name: Option<String> = { let web = a.spotify.lock().unwrap().web().ok(); let me = web.and_then(|w| w.get("/me").ok()).map(|(_, v)| v["display_name"].as_str().unwrap_or("").to_string()).unwrap_or_default();
            let n: String = me.chars().map(|c| if c.is_whitespace() { ' ' } else { c }).filter(|c| c.is_alphanumeric() || " ._-".contains(*c)).collect();
            let n = n.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(40).collect::<String>().trim().to_string(); if n.is_empty() { None } else { Some(n) } };
        let mut body = serde_json::json!({ "email": e }); if let Some(n) = name { body["name"] = serde_json::json!(n); }
        let r = ureq::post(ACCESS_URL).timeout(Duration::from_secs(15)).set("User-Agent", &format!("AoE4Spotify/{}", env!("CARGO_PKG_VERSION"))).send_json(body);
        let code = match r { Ok(r) => r.status(), Err(ureq::Error::Status(c, _)) => c, Err(_) => { launcher::log("Access request failed: network"); return "down".into(); } };
        if !(200..300).contains(&code) { launcher::log(&format!("Access request failed: HTTP {code}")); return match code { 400 => "bad", 429 => "busy", 502 | 503 => "down", _ => "error" }.into(); }
        set_user_(&a, "access_last", serde_json::json!(wall())); set_user_(&a, "access_pending", serde_json::json!(true)); launcher::log("Access request sent"); "sent".into()
    }).await.map_err(|e| e.to_string())
}
/// Rechecked every minute while the guide is open: once access works, close it and show good to go.
#[tauri::command]
pub async fn access_check(h: tauri::AppHandle, app: tauri::State<'_, Arc<AppState>>) -> Result<Option<String>, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || { let r = access_status(&a);
        if r == Some("ok") { set_user_(&a, "access_pending", serde_json::Value::Null); show_gtg(&h, &a); use tauri::Manager; if let Some(w) = h.get_webview_window("access") { let _ = w.close(); } }
        r.map(String::from) }).await.map_err(|e| e.to_string())
}
/// Windows clipboard text (the guide fills the email box as soon as you copy one; builder Paste).
#[tauri::command]
pub fn clip_text() -> String {
    #[cfg(windows)] unsafe {
        #[link(name = "user32")] extern "system" { fn OpenClipboard(h: isize) -> i32; fn CloseClipboard() -> i32; fn GetClipboardData(f: u32) -> isize; }
        #[link(name = "kernel32")] extern "system" { fn GlobalLock(h: isize) -> *const u16; fn GlobalUnlock(h: isize) -> i32; }
        if OpenClipboard(0) == 0 { return String::new(); }
        let h = GetClipboardData(13); let mut out = String::new();
        if h != 0 { let p = GlobalLock(h); if !p.is_null() { let mut n = 0; while *p.add(n) != 0 && n < 100_000 { n += 1; } out = String::from_utf16_lossy(std::slice::from_raw_parts(p, n)); GlobalUnlock(h); } }
        CloseClipboard(); return out;
    }
    #[allow(unreachable_code)] String::new()
}

// ---- Your Spotify app (1.0.9 byo.py, approved v3 guide): your own Client ID instead of the shared app
pub fn show_own(h: &tauri::AppHandle) { let h2 = h.clone(); let _ = h.run_on_main_thread(move || small_window(&h2, "own", "own.html", 500.0, 922.0)); }
#[tauri::command]
pub fn open_own(h: tauri::AppHandle) { show_own(&h); }
#[tauri::command]
pub fn own_info(app: tauri::State<Arc<AppState>>) -> serde_json::Value { serde_json::json!({ "own": app.settings.lock().unwrap().own_app, "light": windows_light() }) }
pub fn close_guides(h: &tauri::AppHandle) { use tauri::Manager; for l in ["own", "access"] { if let Some(w) = h.get_webview_window(l) { let _ = w.close(); } } }
/// Save and log in: a valid Client ID (32 hex, not the secret) -> settings, switch the client (drops the old login), log in (PKCE).
#[tauri::command]
pub async fn own_save(h: tauri::AppHandle, app: tauri::State<'_, Arc<AppState>>, cid: String) -> Result<String, String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let c = cid.trim().to_lowercase(); if !settings::client_id_ok(&c) { return "bad".to_string(); }
        set_user_(&a, "client_id", serde_json::json!(c)); set_user_(&a, "own_app", serde_json::json!(true));
        if a.spotify.lock().unwrap().set_client(&c) { launcher::log("Using your own Spotify app"); }
        sync_logged(&a); close_guides(&h); do_login(h.clone(), a); "saved".into()
    }).await.map_err(|e| e.to_string())
}
/// Use the shared app instead: back to the installer's client (drops the login only when it changes).
#[tauri::command]
pub async fn own_shared(h: tauri::AppHandle, app: tauri::State<'_, Arc<AppState>>) -> Result<(), String> {
    let a = app.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        set_user_(&a, "client_id", serde_json::Value::Null); set_user_(&a, "own_app", serde_json::Value::Null);
        let shared = a.settings.lock().unwrap().shared_client_id.clone();
        let changed = a.spotify.lock().unwrap().set_client(&shared); sync_logged(&a);
        close_guides(&h); if changed { launcher::log("Using the shared Spotify app"); do_login(h.clone(), a); }
    }).await.map_err(|e| e.to_string())
}
#[tauri::command]
pub fn show_panel(app: tauri::AppHandle) { use tauri::Manager; if let Some(w) = app.get_webview_window("main") { let _ = w.show(); let _ = w.unminimize(); let _ = w.set_focus(); } }
