//! After login: good to go, the shared-app access guide, Your Spotify app; login (Tauri 1.1 guides.rs without windows).
//! Windows to show are requested through `Shell`, implemented by the front end.
use crate::{Engine, wall, data::{read_user, set_user_}};
use aoe4core::settings;
use aoe4core::spotify::Spotify;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::Duration;

/// Small windows the engine asks the front end to show / close.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Win { Panel, Gtg, Access, Own, Pick, Add }
pub trait Shell: Send + Sync { fn show(&self, w: Win); fn close(&self, w: Win); }

/// 1.0.9 setup_status for the "You're good to go" window.
pub fn spotify_installed() -> bool {
    let ad = std::env::var("APPDATA").unwrap_or_default(); let la = std::env::var("LOCALAPPDATA").unwrap_or_default();
    std::path::Path::new(&ad).join(r"Spotify\Spotify.exe").is_file() || std::path::Path::new(&la).join(r"Packages\SpotifyAB.SpotifyMusic_zpdnekdrzrea0").is_dir()
        || (cfg!(windows) && std::process::Command::new("reg").args(["query", r"HKCU\Software\Classes\spotify"]).output().map(|o| o.status.success()).unwrap_or(false))
}
pub fn launch_option_is_set() -> Option<bool> { #[cfg(windows)] { aoe4winsys::launcher::launch_option_is_set() } #[cfg(not(windows))] { None } }
pub fn show_gtg(sh: &Arc<dyn Shell>, a: &Arc<Engine>) {
    let (ok, web) = { let mut s = a.spotify.lock().unwrap(); let ok = s.logged_in(); (ok, if ok { s.web().ok() } else { None }) };
    let name = web.and_then(|w| w.get("/me").ok()).filter(|(c, _)| *c == 200).and_then(|(_, v)| v["display_name"].as_str().or(v["id"].as_str()).map(String::from));
    *a.gtg.lock().unwrap() = serde_json::json!({ "ok": ok, "name": name, "steam": launch_option_is_set(), "spotify_app": spotify_installed() });
    sh.show(Win::Gtg);
}
/// Good to go "Fix": put the Steam launch option back (Steam closes and reopens), then re-check. Blocking.
pub fn gtg_fix(a: &Engine) -> serde_json::Value {
    #[cfg(windows)] { aoe4winsys::launcher::with_steam_closed(aoe4winsys::launcher::set_launch_option); }
    let st = launch_option_is_set(); a.gtg.lock().unwrap()["steam"] = serde_json::json!(st); a.gtg.lock().unwrap().clone()
}
/// 1.0.9 login(): browser login, then good to go / the not-invited guide.
pub fn do_login(sh: Arc<dyn Shell>, a: Arc<Engine>) {
    if a.busy.swap(true, Ordering::SeqCst) { return; }
    std::thread::spawn(move || {
        a.push("Spotify: opening login in your browser...".into());
        let cid = a.spotify.lock().unwrap().client_id();   // lock released before the browser wait
        let r = Spotify::login_code(&cid).and_then(|(c, v)| a.spotify.lock().unwrap().login_finish(&c, &v));
        a.sync_logged();
        a.push(match r { Ok(_) => "Spotify: logged in".into(), Err(e) => format!("Spotify login: {e}") });
        a.busy.store(false, Ordering::SeqCst);
        after_login(&sh, &a);
    });
}

// ---- 1.0.9 access.py: shared-app access request (capstar.app relay) and the 'Not invited yet' guide
pub const ACCESS_URL: &str = "https://capstar.app/api/aoe4-spotify/access-request";
pub const ACCESS_GAP: f64 = 600.0;   // one request per 10 min per install
/// "ok", "blocked" (Spotify refuses this account: not on the shared app's user list, dev-mode 403) or None (offline / not logged in).
pub fn access_status(a: &Engine) -> Option<&'static str> {
    let w = { let mut sp = a.spotify.lock().unwrap(); if !sp.logged_in() { return None; } sp.web().ok()? };
    let (c, r) = w.get("/me").ok()?; if c == 200 { return Some("ok"); }
    let t = r.to_string().to_lowercase();
    if c == 403 && (t.contains("not registered") || t.contains("developer dashboard") || t.contains("user may not be registered")) { Some("blocked") } else { None }
}
pub fn after_login(sh: &Arc<dyn Shell>, a: &Arc<Engine>) { if access_status(a) == Some("blocked") { sh.show(Win::Access); } else { show_gtg(sh, a); } }
/// Asked for access earlier: check once on start (1.0.9 pending_access).
pub fn pending_access(sh: Arc<dyn Shell>, a: Arc<Engine>) {
    if read_user(&a.dir)["access_pending"].as_bool() != Some(true) { return; }
    std::thread::spawn(move || match access_status(&a) { Some("ok") => { set_user_(&a, "access_pending", serde_json::Value::Null); show_gtg(&sh, &a); } Some("blocked") => sh.show(Win::Access), _ => {} });
}
pub fn access_info(a: &Engine) -> serde_json::Value {
    let u = read_user(&a.dir); let last = u["access_last"].as_f64().unwrap_or(0.0);
    serde_json::json!({ "pending": u["access_pending"].as_bool() == Some(true) && wall() - last < ACCESS_GAP, "on": true, "light": windows_light() })
}
/// Windows app theme (1.0.9 windows_light): HKCU ...\Themes\Personalize AppsUseLightTheme = 1, reused for 10 s.
/// AOE4S_LIGHT=1/0 overrides (tests, other OSes).
pub fn windows_light() -> bool {
    if let Ok(v) = std::env::var("AOE4S_LIGHT") { return v == "1"; }
    static LAST: Mutex<Option<(std::time::Instant, bool)>> = Mutex::new(None);
    let mut l = LAST.lock().unwrap();
    if let Some((t, v)) = *l { if t.elapsed() < Duration::from_secs(10) { return v; } }
    let v = reg_light(); *l = Some((std::time::Instant::now(), v)); v
}
#[cfg(windows)]
fn reg_light() -> bool {
    #[link(name = "advapi32")] extern "system" { fn RegGetValueW(k: isize, sub: *const u16, val: *const u16, flags: u32, ty: *mut u32, data: *mut u32, len: *mut u32) -> i32; }
    let w = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
    let (mut d, mut n) = (0u32, 4u32);
    // HKEY_CURRENT_USER = 0x80000001, RRF_RT_REG_DWORD = 0x10
    let r = unsafe { RegGetValueW(0x8000_0001u32 as i32 as isize, w(r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize").as_ptr(), w("AppsUseLightTheme").as_ptr(), 0x10, std::ptr::null_mut(), &mut d, &mut n) };
    r == 0 && d == 1
}
#[cfg(not(windows))]
fn reg_light() -> bool { false }
/// Email check of the access form (1.1 rules).
pub fn email_ok(e: &str) -> bool { let at = e.find('@').unwrap_or(0); !(e.len() > 100 || at == 0 || !e[at + 1..].contains('.') || e.chars().any(|c| c.is_whitespace() || c == ',' || c == ';') || e.ends_with('.')) }
/// 'Send request': one POST {email[, name]} to the relay. sent | wait | bad | busy | down | error. Blocking.
pub fn access_send(a: &Engine, email: &str) -> String {
    let e = email.trim().to_string(); if !email_ok(&e) { return "bad".to_string(); }
    let u = read_user(&a.dir); if wall() - u["access_last"].as_f64().unwrap_or(0.0) < ACCESS_GAP { return "wait".into(); }
    let name: Option<String> = { let web = a.spotify.lock().unwrap().web().ok(); let me = web.and_then(|w| w.get("/me").ok()).map(|(_, v)| v["display_name"].as_str().unwrap_or("").to_string()).unwrap_or_default();
        let n: String = me.chars().map(|c| if c.is_whitespace() { ' ' } else { c }).filter(|c| c.is_alphanumeric() || " ._-".contains(*c)).collect();
        let n = n.split_whitespace().collect::<Vec<_>>().join(" ").chars().take(40).collect::<String>().trim().to_string(); if n.is_empty() { None } else { Some(n) } };
    let mut body = serde_json::json!({ "email": e }); if let Some(n) = name { body["name"] = serde_json::json!(n); }
    let r = ureq::post(ACCESS_URL).timeout(Duration::from_secs(15)).set("User-Agent", &format!("AoE4Spotify/{}", env!("CARGO_PKG_VERSION"))).send_json(body);
    let code = match r { Ok(r) => r.status(), Err(ureq::Error::Status(c, _)) => c, Err(_) => { crate::sys::log("Access request failed: network"); return "down".into(); } };
    if !(200..300).contains(&code) { crate::sys::log(&format!("Access request failed: HTTP {code}")); return match code { 400 => "bad", 429 => "busy", 502 | 503 => "down", _ => "error" }.into(); }
    set_user_(a, "access_last", serde_json::json!(wall())); set_user_(a, "access_pending", serde_json::json!(true)); crate::sys::log("Access request sent"); "sent".into()
}
/// Rechecked every minute while the guide is open: once access works, close it and show good to go. Blocking.
pub fn access_check(sh: &Arc<dyn Shell>, a: &Arc<Engine>) -> Option<String> {
    let r = access_status(a);
    if r == Some("ok") { set_user_(a, "access_pending", serde_json::Value::Null); show_gtg(sh, a); sh.close(Win::Access); }
    r.map(String::from)
}
/// Put text on the clipboard (Windows; share codes). Elsewhere a no-op.
pub fn set_clip_text(t: &str) {
    #[cfg(windows)] unsafe {
        #[link(name = "user32")] extern "system" { fn OpenClipboard(h: isize) -> i32; fn CloseClipboard() -> i32; fn EmptyClipboard() -> i32; fn SetClipboardData(f: u32, h: isize) -> isize; }
        #[link(name = "kernel32")] extern "system" { fn GlobalAlloc(f: u32, n: usize) -> isize; fn GlobalLock(h: isize) -> *const u16; fn GlobalUnlock(h: isize) -> i32; fn GlobalFree(h: isize) -> isize; }
        let w: Vec<u16> = t.encode_utf16().chain(std::iter::once(0)).collect();
        if OpenClipboard(0) == 0 { return; }
        EmptyClipboard();
        let h = GlobalAlloc(0x0002, w.len() * 2);
        if h != 0 { let p = GlobalLock(h); if !p.is_null() { std::ptr::copy_nonoverlapping(w.as_ptr(), p as *mut u16, w.len()); GlobalUnlock(h); if SetClipboardData(13, h) == 0 { GlobalFree(h); } } else { GlobalFree(h); } }
        CloseClipboard();
    }
    #[cfg(not(windows))] { let _ = t; }
}
/// Clipboard text (Windows; the guide fills the email box as soon as you copy one).
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
pub fn own_info(a: &Engine) -> serde_json::Value { serde_json::json!({ "own": a.settings.lock().unwrap().own_app, "light": windows_light() }) }
fn close_guides(sh: &Arc<dyn Shell>) { sh.close(Win::Own); sh.close(Win::Access); }
/// Save and log in: a valid Client ID (32 hex, not the secret) -> settings, switch the client, log in. "bad" | "saved".
pub fn own_save(sh: &Arc<dyn Shell>, a: &Arc<Engine>, cid: &str) -> String {
    let c = cid.trim().to_lowercase(); if !settings::client_id_ok(&c) { return "bad".to_string(); }
    set_user_(a, "client_id", serde_json::json!(c)); set_user_(a, "own_app", serde_json::json!(true));
    if a.spotify.lock().unwrap().set_client(&c) { crate::sys::log("Using your own Spotify app"); }
    a.sync_logged(); close_guides(sh); do_login(sh.clone(), a.clone()); "saved".into()
}
/// Use the shared app instead (drops the login only when the client changes).
pub fn own_shared(sh: &Arc<dyn Shell>, a: &Arc<Engine>) {
    set_user_(a, "client_id", serde_json::Value::Null); set_user_(a, "own_app", serde_json::Value::Null);
    let shared = a.settings.lock().unwrap().shared_client_id.clone();
    let changed = a.spotify.lock().unwrap().set_client(&shared); a.sync_logged();
    close_guides(sh); if changed { crate::sys::log("Using the shared Spotify app"); do_login(sh.clone(), a.clone()); }
}
