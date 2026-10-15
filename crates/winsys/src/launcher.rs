//! Game-launcher mode, ported from 1.0.9 (app.py _main, aoe4_setup.py, runtime.py):
//! Steam starts `"<install>\AoE4 Spotify.exe" %command% <your options>`; we sync the game music, start the game
//! with Steam's environment, and run the switcher (window hidden) until the game closes. One switcher at a time.
//! Also: --set-launch-option / --remove-launch-option (Steam localconfig.vdf, Steam closed while editing).
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

pub const APPID: &str = "1466860";   // Age of Empires IV on Steam
const NO_WINDOW: u32 = 0x0800_0000;

/// Test-only overrides (dummy Steam / game): honoured only with AOE4S_TEST=1, so a stray variable can't redirect a real install.
pub fn test_env(name: &str) -> Option<String> { if std::env::var("AOE4S_TEST").ok().as_deref() != Some("1") { return None; } std::env::var(name).ok().filter(|s| !s.is_empty()) }
pub fn data_dir() -> PathBuf { PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify-1.1") }
pub fn log(m: &str) {
    use std::io::Write; let _ = std::fs::create_dir_all(data_dir());
    let t = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) + 2 * 3600;
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(data_dir().join("aoe4_spotify.log")) {
        let _ = writeln!(f, "{:02}:{:02}:{:02} {m}", (t / 3600) % 24, (t / 60) % 60, t % 60); }
}
/// One Toolhelp process row. Layout matches PROCESSENTRY32W on 64-bit Windows.
#[repr(C)]
struct ProcessEntry {
    size: u32, _cnt_usage: u32, _pid: u32, _heap: usize, _mid: u32, _threads: u32, _parent: u32, _pri: i32, _flags: u32,
    exe: [u16; 260],
}
/// Image name of a running process, via a Toolhelp snapshot. No `tasklist.exe`.
pub fn proc_running(name: &str) -> bool {
    unsafe {
        let snap = CreateToolhelp32Snapshot(0x2, 0);   // TH32CS_SNAPPROCESS
        if snap == 0 || snap == -1 { return false; }
        let mut e: ProcessEntry = std::mem::zeroed();
        e.size = std::mem::size_of::<ProcessEntry>() as u32;
        let mut found = false;
        if Process32FirstW(snap, &mut e) != 0 {
            loop {
                let n = e.exe.iter().position(|&c| c == 0).unwrap_or(e.exe.len());
                if String::from_utf16_lossy(&e.exe[..n]).eq_ignore_ascii_case(name) { found = true; break; }
                if Process32NextW(snap, &mut e) == 0 { break; }
            }
        }
        CloseHandle(snap);
        found
    }
}
pub fn game_proc() -> String { test_env("AOE4S_GAME_PROC").unwrap_or_else(|| "RelicCardinal.exe".into()) }
pub fn aoe_running() -> bool { proc_running(&game_proc()) }

// ---- game music: mute AoE4's own music while we play Spotify (remember your level), put it back when disabled
fn game_cfg_path() -> PathBuf {
    if let Some(p) = test_env("AOE4S_GAME_CFG") { return p.into(); }
    let docs = std::env::var("USERPROFILE").map(|u| PathBuf::from(u).join("Documents")).unwrap_or_default();
    docs.join(r"My Games\Age of Empires IV\configuration_system.lua")
}
fn music_state() -> PathBuf { data_dir().join("game_music.json") }
fn music_find(data: &[u8]) -> Option<(usize, usize, f64)> {
    // setting\s*=\s*"musicvolume"\s*,\s*variantFloat\s*=\s*(-?[0-9]+(\.[0-9]+)?)
    let t = String::from_utf8_lossy(data); let low = t.as_ref();
    let mut from = 0;
    while let Some(i) = low[from..].find("\"musicvolume\"") {
        let s = from + i; from = s + 1;
        let before = low[..s].trim_end(); if !before.ends_with('=') || !before[..before.len() - 1].trim_end().ends_with("setting") { continue; }
        let mut j = s + "\"musicvolume\"".len(); let b = low.as_bytes();
        while j < b.len() && b[j].is_ascii_whitespace() { j += 1; } if j >= b.len() || b[j] != b',' { continue; } j += 1;
        while j < b.len() && b[j].is_ascii_whitespace() { j += 1; } if !low[j..].starts_with("variantFloat") { continue; } j += "variantFloat".len();
        while j < b.len() && b[j].is_ascii_whitespace() { j += 1; } if j >= b.len() || b[j] != b'=' { continue; } j += 1;
        while j < b.len() && b[j].is_ascii_whitespace() { j += 1; }
        let st = j; if j < b.len() && b[j] == b'-' { j += 1; } let d0 = j; while j < b.len() && b[j].is_ascii_digit() { j += 1; } if j == d0 { continue; }
        if j + 1 < b.len() && b[j] == b'.' && b[j + 1].is_ascii_digit() { j += 1; while j < b.len() && b[j].is_ascii_digit() { j += 1; } }
        if t.len() != data.len() { return None; }   // non-UTF-8 file: byte offsets would not match, leave it alone
        return low[st..j].parse().ok().map(|v| (st, j, v));
    }
    None
}
fn music_read() -> Option<f64> { music_find(&std::fs::read(game_cfg_path()).ok()?).map(|x| x.2) }
/// Change only that one number; the rest of the file stays byte-identical. Backs the file up once.
fn music_write(v: f64) -> bool {
    let p = game_cfg_path(); let Ok(data) = std::fs::read(&p) else { return false }; let Some((a, b, _)) = music_find(&data) else { return false };
    let bak = PathBuf::from(format!("{}.aoe4spotify.bak", p.display())); if !bak.exists() { let _ = std::fs::copy(&p, &bak); }
    let mut new = data[..a].to_vec(); new.extend_from_slice(format!("{v:.5}").as_bytes()); new.extend_from_slice(&data[b..]);
    if new != data { let tmp = PathBuf::from(format!("{}.tmp", p.display())); if std::fs::write(&tmp, &new).is_err() || std::fs::rename(&tmp, &p).is_err() { return false; } }
    true
}
/// enabled: mute the game music (remember your level); disabled: put your level back. Never while AoE4 runs.
pub fn music_sync(enabled: bool) -> bool {
    if aoe_running() { log("Game music: AoE4 is running - will apply after it closes"); return false; }
    let Some(v) = music_read() else { return false };
    if enabled {
        if v > 0.0 { let _ = std::fs::create_dir_all(data_dir()); let _ = std::fs::write(music_state(), serde_json::json!({ "level": v }).to_string()); music_write(0.0); log(&format!("Game music muted (your level {v:.2} saved)")); }
    } else {
        // only put back what we muted (a saved level); music that was already 0 when we took over stays 0
        let lv = std::fs::read_to_string(music_state()).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()).and_then(|j| j["level"].as_f64()).filter(|l| *l > 0.0);
        if let Some(l) = lv { if v == 0.0 { music_write(l); log(&format!("Game music restored to {l:.2}")); } }
        let _ = std::fs::remove_file(music_state());
    }
    true
}

// ---- uninstall (1.0.9 setup.iss: "Removes the app, its shortcuts and settings, and puts the game's launch options and music volume back.")
fn arp_key() -> String { test_env("AOE4S_ARP").unwrap_or_else(|| r"HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AoE4Spotify11".into()) }
pub fn installed() -> bool { install_dir().join("unins000.exe").is_file() || install_dir().file_name().map_or(false, |n| n.to_string_lossy().eq_ignore_ascii_case("AoE4 Spotify 1.1")) || test_env("AOE4S_INSTALLED").is_some() }
/// Apps & features entry for the installed copy (idempotent).
pub fn register_uninstall() {
    use std::os::windows::process::CommandExt;
    if !installed() || install_dir().join("unins000.exe").is_file() { return; } let exe = install_dir().join("AoE4 Spotify.exe"); let k = arp_key();
    for (n, t, v) in [("DisplayName", "REG_SZ", "AoE4 Spotify".to_string()), ("DisplayVersion", "REG_SZ", env!("CARGO_PKG_VERSION").to_string()), ("Publisher", "REG_SZ", "Capstar1".into()),
        ("DisplayIcon", "REG_SZ", install_dir().join("app.ico").display().to_string()), ("InstallLocation", "REG_SZ", install_dir().display().to_string()),
        ("UninstallString", "REG_SZ", format!("\"{}\" --uninstall", exe.display())), ("NoModify", "REG_DWORD", "1".into()), ("NoRepair", "REG_DWORD", "1".into())] {
        let _ = std::process::Command::new("reg").args(["add", &k, "/v", n, "/t", t, "/d", &v, "/f"]).creation_flags(NO_WINDOW).output(); }
}
fn desktop() -> PathBuf { test_env("AOE4S_DESKTOP").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(std::env::var("USERPROFILE").unwrap_or_default()).join("Desktop")) }
#[link(name = "user32")] extern "system" { fn MessageBoxW(h: isize, t: *const u16, c: *const u16, f: u32) -> i32; }
fn msgbox(text: &str, title: &str, flags: u32) -> i32 { let w = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>(); unsafe { MessageBoxW(0, w(text).as_ptr(), w(title).as_ptr(), flags | 0x40000) } }
pub fn uninstall(yes: bool) {
    use std::os::windows::process::CommandExt;
    if !yes && msgbox("Removes the app, its shortcuts and settings, and puts the game's launch options and music volume back.\n\nSteam will be closed briefly if it is running.", "Uninstall AoE4 Spotify?", 0x4 | 0x20) != 6 { return; }
    if aoe_running() { msgbox("Close Age of Empires IV first, then uninstall again.", "Uninstall", 0x30); return; }
    // Hold both mutexes so a panel or a switcher cannot start mid-uninstall. Best-effort 15 s.
    // CreateMutex in a process that already holds that mutex returns 183, so take each one only once.
    let t0 = Instant::now(); let (mut got_p, mut got_s) = (false, false);
    while !(got_p && got_s) && t0.elapsed().as_secs() < 15 {
        if !got_p { got_p = panel_lock(); }
        if !got_s { got_s = switcher_lock(); }
        if got_p && got_s { break; }
        std::thread::sleep(Duration::from_millis(500));
    }
    log("Uninstall: removing launch option, restoring game music");
    with_steam_closed(remove_launch_option); music_sync(false);
    let lnk = desktop().join("AoE4 Spotify.lnk"); if lnk.exists() { let _ = std::fs::remove_file(&lnk); }
    let ad = PathBuf::from(std::env::var("APPDATA").unwrap_or_default());
    for d in [ad.join("AoE4Spotify-1.1"), ad.join("AoE4Spotify")] { let _ = std::fs::remove_dir_all(&d); }   // settings (+ the 1.0.9 leftover)
    let _ = std::process::Command::new("reg").args(["delete", &arp_key(), "/f"]).creation_flags(NO_WINDOW).output();
    // the running exe can't delete itself: a detached cmd removes the install folder once we have exited
    let dir = install_dir();
    if installed() { let _ = std::process::Command::new("cmd").raw_arg(format!("/c ping -n 3 127.0.0.1 >nul & rmdir /s /q \"{}\"", dir.display())).current_dir(std::env::temp_dir()).creation_flags(NO_WINDOW | 0x8).spawn(); }
    if !yes { msgbox("AoE4 Spotify was removed.", "Uninstall", 0x40); }
}

// ---- two instances: the panel (settings UI) and the switcher (Steam launch / --attach). Each holds its own mutex.
#[link(name = "kernel32")] extern "system" {
    fn CreateMutexW(a: *const u8, o: i32, n: *const u16) -> isize;
    fn OpenMutexW(access: u32, inherit: i32, n: *const u16) -> isize;
    fn GetLastError() -> u32;
    fn CloseHandle(h: isize) -> i32;
    fn CreateToolhelp32Snapshot(flags: u32, pid: u32) -> isize;
    fn Process32FirstW(snap: isize, e: *mut ProcessEntry) -> i32;
    fn Process32NextW(snap: isize, e: *mut ProcessEntry) -> i32;
}
fn wide(name: &str) -> Vec<u16> { name.encode_utf16().chain(Some(0)).collect() }
fn suffix() -> String { std::env::var("AOE4S_MUTEX_SUFFIX").unwrap_or_default() }
fn switcher_name() -> Vec<u16> { wide(&format!("AoE4Spotify11SwitcherMutex{}", suffix())) }
fn panel_name() -> Vec<u16> { wide(&format!("AoE4Spotify11PanelMutex{}", suffix())) }
fn lock_named(name: &[u16]) -> bool {
    unsafe { let h = CreateMutexW(std::ptr::null(), 0, name.as_ptr()); if GetLastError() != 183 { return h != 0; } if h != 0 { CloseHandle(h); } false }
}
/// Switcher mutex. The winning handle stays open for the life of this process.
pub fn switcher_lock() -> bool { lock_named(&switcher_name()) }
/// Panel mutex. A second panel asks the first to show itself and exits.
pub fn panel_lock() -> bool { lock_named(&panel_name()) }
/// Alias of `switcher_lock` (Steam launch and `--attach`).
pub fn single_instance() -> bool { switcher_lock() }
/// True while any process holds the switcher mutex.
pub fn switcher_running() -> bool {
    unsafe { let h = OpenMutexW(0x0010_0000, 0, switcher_name().as_ptr()); if h == 0 { return false; } CloseHandle(h); true }
}
/// Game restarted right after closing: the old switcher may still be finishing. Wait for it (20 s).
pub fn wait_single_instance(secs: u64) -> bool { let t0 = Instant::now(); while !single_instance() { if t0.elapsed().as_secs() > secs { return false; } std::thread::sleep(Duration::from_secs(1)); } true }

/// What main() should do with the command line.
pub enum Mode { Panel, Game(Vec<String>), Done, Attach, Migrate(Option<PathBuf>, bool) }
pub fn mode(enabled: bool) -> Mode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(|s| s.as_str()) {
        None | Some("--panel") => Mode::Panel,
        Some("--set-launch-option") => { with_steam_closed(set_launch_option); music_sync(enabled); Mode::Done }
        Some("--uninstall") => { uninstall(args.iter().any(|a| a == "--yes")); Mode::Done }
        Some("--remove-launch-option") => { remove_launch_option(); music_sync(false); Mode::Done }
        Some("--attach") => Mode::Attach,                  // setup ran while the game runs: follow that game (hidden), else exit
        Some("--migrate-109") => Mode::Migrate(args.iter().skip(1).find(|a| !a.starts_with("--")).map(PathBuf::from), args.iter().any(|a| a == "--cleanup")),
        Some("--updated") => Mode::Panel,
        Some(a) if a.starts_with("--") => Mode::Done,
        _ => Mode::Game(args),
    }
}
/// Started by Steam with the game command (%command%) as args: start the game first. Returns true if this process
/// should go on as the (hidden) switcher for this game session.
pub fn start_game(args: &[String], enabled: bool) -> bool {
    if let Err(e) = std::panic::catch_unwind(|| music_sync(enabled)) { log(&format!("Music volume sync failed (game starts anyway): {e:?}")); }
    let exe = Path::new(&args[0]); let mut c = std::process::Command::new(exe); c.args(&args[1..]);
    if exe.is_file() { if let Some(d) = exe.parent() { c.current_dir(d); } }      // the game keeps Steam's variables
    match c.spawn() { Ok(_) => log(&format!("Started game: {}", args.join(" "))), Err(e) => { log(&format!("Could not start the game: {e}")); return false; } }
    if !enabled { log("Disabled in the app - game started, doing nothing else"); return false; }
    if !wait_single_instance(20) { log("Another switcher is already running - exiting"); return false; }
    true
}
/// Wait for the game process (max 5 min), then until it closes; then re-apply the music mute (the game rewrote its settings).
pub fn follow_game(on_close: impl FnOnce()) {
    let t0 = Instant::now();
    while !aoe_running() { if t0.elapsed().as_secs() > 300 { log("Age of Empires IV did not start within 5 minutes - exiting"); on_close(); return; } std::thread::sleep(Duration::from_secs(3)); }
    log("Age of Empires IV is running");
    while aoe_running() { std::thread::sleep(Duration::from_secs(3)); }
    log("Age of Empires IV closed - exiting");
    std::thread::sleep(Duration::from_secs(2)); music_sync(enabled_now()); std::thread::sleep(Duration::from_secs(3)); on_close();
}
pub fn enabled_now() -> bool { std::fs::read_to_string(data_dir().join("config.json")).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()).and_then(|v| v["enabled"].as_bool()).unwrap_or(true) }

// ---- Steam launch option (aoe4_setup.py)
fn steam_reg(v: &str) -> Option<String> {
    use std::os::windows::process::CommandExt;
    let o = std::process::Command::new("reg").args(["query", r"HKCU\Software\Valve\Steam", "/v", v]).creation_flags(NO_WINDOW).output().ok()?;
    String::from_utf8_lossy(&o.stdout).lines().find_map(|l| { let l = l.trim(); l.strip_prefix(v).and_then(|r| r.trim().strip_prefix("REG_SZ")).map(|r| r.trim().to_string()) })
}
fn steam_path() -> Option<String> { test_env("AOE4S_STEAM_PATH").or_else(|| steam_reg("SteamPath")) }
fn steam_exe() -> Option<String> { test_env("AOE4S_STEAM_EXE").or_else(|| steam_reg("SteamExe")) }
fn steam_proc() -> String { test_env("AOE4S_STEAM_PROC").unwrap_or_else(|| "steam.exe".into()) }
pub fn install_dir() -> PathBuf { std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())).unwrap_or_default() }
fn state_path() -> PathBuf { install_dir().join("launch_option_backup.json") }
fn our_prefix() -> String { format!("\"{}\" ", install_dir().join("AoE4 Spotify.exe").display()) }
fn localconfigs() -> Vec<PathBuf> {
    let Some(root) = steam_path() else { log("Steam is not installed (no SteamPath in the registry) - launch option not changed"); return vec![] };
    let mut v: Vec<PathBuf> = std::fs::read_dir(Path::new(&root).join("userdata")).into_iter().flatten().flatten().map(|e| e.path().join(r"config\localconfig.vdf")).filter(|p| p.is_file()).collect();
    v.sort(); if v.is_empty() { log(&format!("No Steam user configs found under {root}")); } v
}
#[derive(Clone)] struct Tok { kind: char, val: String, a: usize, b: usize }
fn vdf_tokens(t: &str) -> Vec<Tok> {
    let b = t.as_bytes(); let (mut out, mut i, n) = (vec![], 0, b.len());
    while i < n { let c = b[i];
        if c == b'"' { let mut j = i + 1; while j < n && b[j] != b'"' { j += if b[j] == b'\\' { 2 } else { 1 }; } let j2 = j.min(n); out.push(Tok { kind: 's', val: t[i + 1..j2].to_string(), a: i, b: (j + 1).min(n) }); i = j + 1; }
        else if c == b'{' || c == b'}' { out.push(Tok { kind: c as char, val: (c as char).to_string(), a: i, b: i + 1 }); i += 1; }
        else if c == b'/' && t[i..].starts_with("//") { i = t[i..].find('\n').map(|k| i + k).unwrap_or(n); }
        else { i += 1; } }
    out
}
fn vdf_find(toks: &[Tok], path: &[&str]) -> Option<(usize, usize)> {
    let (mut lo, mut hi): (isize, usize) = (-1, toks.len());
    for key in path {
        let (mut depth, mut k, mut found) = (0i32, (lo + 1) as usize, None);
        while k < hi { match toks[k].kind { '{' => depth += 1, '}' => depth -= 1,
            's' if depth == 0 && k + 1 < hi && toks[k + 1].kind == '{' && toks[k].val.eq_ignore_ascii_case(key) => { found = Some(k + 1); break; } _ => {} } k += 1; }
        let f = found?; let (mut d, mut m) = (0, f);
        loop { if toks[m].kind == '{' { d += 1; } else if toks[m].kind == '}' { d -= 1; if d == 0 { break; } } m += 1; if m >= toks.len() { return None; } }
        lo = f as isize; hi = m;
    }
    Some((lo as usize, hi))
}
fn vesc(v: &str) -> String { v.replace('\\', "\\\\").replace('"', "\\\"") }
fn vunesc(v: &str) -> String { let mut o = String::new(); let mut it = v.chars(); while let Some(c) = it.next() { if c == '\\' { if let Some(n) = it.next() { o.push(n); } } else { o.push(c); } } o }

/// Remove every AoE4 Spotify exe path (any install folder, quoted or not, any number) from a launch option.
pub fn strip_ours(v: &str) -> String {
    let mut s = v.to_string();
    loop {
        let low = s.to_lowercase(); let Some(e) = low.find("spotify.exe") else { break }; let end = e + "spotify.exe".len();
        let head = &low[..e]; let Some(a) = head.rfind("aoe4 ") else { break };
        if !head[a..].trim_end().is_empty() && !head[a + 5..].chars().all(|c| c.is_ascii_alphanumeric() || " ._-".contains(c)) { break }
        let (mut st, mut en) = (a, end);
        if let Some(q) = s[..a].rfind('"') { if s[q + 1..a].chars().all(|c| c != '"') && s[end..].starts_with('"') { st = q; en = end + 1; } }
        if st == a { // unquoted: back up to the drive / path start
            let b = s[..a].rfind(|c: char| c == ' ' && false).unwrap_or(0); let _ = b;
            st = s[..a].rfind(|c: char| c == '"' || c == '%').map(|i| i + 1).unwrap_or(0);
            if let Some(d) = s[st..a].find(|c: char| c.is_ascii_alphabetic()).map(|i| st + i) { if s[d..].as_bytes().get(1) == Some(&b':') { st = d; } else if !s[st..a].trim().is_empty() && !s[st..a].contains('\\') && !s[st..a].contains('/') { st = a; } }
        }
        s = format!("{} {}", s[..st].trim_end(), s[en..].trim_start()).trim().to_string();
    }
    s
}
fn compose(pre: &str, old: &str) -> String { let c = strip_ours(old); format!("{pre}{}", if c.contains("%command%") { c } else { format!("%command% {c}").trim().to_string() }) }
fn user_args(old: &str) -> String { let c = strip_ours(old); if c != old.trim() { c.strip_prefix("%command%").map(|r| r.trim().to_string()).unwrap_or(c) } else { old.to_string() } }
pub fn set_launch_option() {
    let mut state = serde_json::Map::new();
    for f in localconfigs() {
        let Ok(raw) = std::fs::read(&f) else { continue }; let Ok(t) = String::from_utf8(raw) else { log(&format!("{}: not UTF-8 - skipped", f.display())); continue };
        let _ = std::fs::copy(&f, format!("{}.aoe4spotify.bak", f.display()));
        let toks = vdf_tokens(&t);
        let base = ["UserLocalConfigStore", "Software", "Valve", "Steam", "apps", APPID];
        let Some((lo, hi)) = vdf_find(&toks, &base) else { log(&format!("{}: AoE4 has no entry (never launched by this Steam user) - skipped", f.display())); continue };
        let (mut d, mut kv) = (0, None);
        for k in lo + 1..hi { match toks[k].kind { '{' => d += 1, '}' => d -= 1, 's' if d == 0 && toks[k].val.eq_ignore_ascii_case("launchoptions") && toks[k + 1].kind == 's' => { kv = Some(k); break; } _ => {} } }
        let pre = our_prefix(); let fs = f.display().to_string(); let (t2, new);
        if let Some(k) = kv {
            let old = vunesc(&toks[k + 1].val);
            new = compose(&pre, &old);
            if old == new { log(&format!("{fs}: already set")); continue; }
            let prev = std::fs::read_to_string(state_path()).ok().and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok()).and_then(|v| v[&fs]["old"].as_str().map(|o| o.to_string()));
            let old = prev.filter(|o| strip_ours(o) == *o).unwrap_or_else(|| user_args(&old));
            t2 = format!("{}\"{}\"{}", &t[..toks[k + 1].a], vesc(&new), &t[toks[k + 1].b..]);
            state.insert(fs.clone(), serde_json::json!({ "mode": "replace", "old": old, "new": new }));
        } else {
            new = format!("{pre}%command%"); let close = toks[hi].a; let ls = t[..close].rfind('\n').map(|i| i + 1).unwrap_or(0);
            let ins = format!("{}\t\"LaunchOptions\"\t\t\"{}\"\n", &t[ls..close], vesc(&new));
            t2 = format!("{}{}{}", &t[..ls], ins, &t[ls..]);
            state.insert(fs.clone(), serde_json::json!({ "mode": "insert", "ins": ins, "new": new }));
        }
        if std::fs::write(&f, t2).is_ok() { log(&format!("{fs}: launch option set to {new}")); }
    }
    let mut old: serde_json::Map<String, serde_json::Value> = std::fs::read_to_string(state_path()).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    old.extend(state); let _ = std::fs::write(state_path(), serde_json::to_string_pretty(&old).unwrap_or_default());
}
pub fn remove_launch_option() {
    let state: serde_json::Value = std::fs::read_to_string(state_path()).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
    for f in localconfigs() {
        let Ok(t) = std::fs::read_to_string(&f) else { continue }; let st = &state[f.display().to_string()]; let toks = vdf_tokens(&t); let mut t2 = None;
        for k in 0..toks.len() {
            if toks[k].kind == 's' && toks[k].val.eq_ignore_ascii_case("launchoptions") && k + 1 < toks.len() && toks[k + 1].kind == 's' && strip_ours(&vunesc(&toks[k + 1].val)) != vunesc(&toks[k + 1].val).trim() {
                let cur = vunesc(&toks[k + 1].val); let (a, b) = (toks[k + 1].a, toks[k + 1].b);
                t2 = Some(if st["mode"] == "insert" && st["new"].as_str() == Some(&cur) && st["ins"].as_str().map_or(false, |i| t.contains(i)) { t.replacen(st["ins"].as_str().unwrap(), "", 1) }
                    else if st["mode"] == "replace" && st["new"].as_str() == Some(&cur) { format!("{}\"{}\"{}", &t[..a], vesc(st["old"].as_str().unwrap_or("")), &t[b..]) }
                    else { format!("{}\"{}\"{}", &t[..a], vesc(&user_args(&cur)), &t[b..]) });
                break;
            }
        }
        if let Some(t2) = t2 { if std::fs::write(&f, t2).is_ok() { log(&format!("{}: launch option removed", f.display())); } }
    }
    let _ = std::fs::remove_file(state_path());
}
pub fn launch_option_is_set() -> Option<bool> {
    let files = localconfigs(); if files.is_empty() { return None; } let pre = our_prefix().to_lowercase();
    Some(files.iter().any(|f| std::fs::read_to_string(f).map(|t| { let toks = vdf_tokens(&t);
        (0..toks.len()).any(|k| toks[k].kind == 's' && toks[k].val.eq_ignore_ascii_case("launchoptions") && k + 1 < toks.len() && toks[k + 1].kind == 's' && vunesc(&toks[k + 1].val).to_lowercase().starts_with(&pre)) }).unwrap_or(false)))
}
/// Steam rewrites localconfig.vdf while running: close it gracefully, run fn, reopen it if it was open.
pub fn with_steam_closed(f: impl FnOnce()) {
    use std::os::windows::process::CommandExt;
    let was = proc_running(&steam_proc()); let exe = steam_exe();
    if was {
        log("Closing Steam to edit the launch option");
        if let Some(e) = &exe { let _ = std::process::Command::new(e).arg("-shutdown").spawn(); }
        let mut closed = false; for _ in 0..30 { std::thread::sleep(Duration::from_secs(1)); if !proc_running(&steam_proc()) { closed = true; break; } }
        if !closed { log("Steam did not close in 30s - force closing"); let _ = std::process::Command::new("taskkill").args(["/im", &steam_proc(), "/f"]).creation_flags(NO_WINDOW).output(); std::thread::sleep(Duration::from_secs(2)); }
        // Steam flushes localconfig.vdf while shutting down: wait until all its processes are gone and the file is quiet.
        for _ in 0..20 { if !proc_running(&steam_proc()) && !proc_running("steamwebhelper.exe") && !proc_running("steamservice.exe") { break; } std::thread::sleep(Duration::from_secs(1)); }
        std::thread::sleep(Duration::from_secs(2));
    }
    f();
    if was { if let Some(e) = &exe { let _ = std::process::Command::new(e).arg("-silent").spawn(); log("Reopened Steam"); } }
}

#[cfg(test)]
mod lo_tests {
    use super::*;
    const P: &str = "\"C:\\Users\\X\\AppData\\Local\\Programs\\AoE4 Spotify\\AoE4 Spotify.exe\" ";
    #[test] fn strip_cases() {
        let o11 = "\"C:\\Users\\X\\AppData\\Local\\Programs\\AoE4 Spotify 1.1\\AoE4 Spotify.exe\"";
        let o109 = "\"C:\\Users\\X\\AppData\\Local\\Programs\\AoE4 Spotify\\AoE4 Spotify.exe\"";
        let unq = "C:\\Tools\\AoE4 Spotify TEST\\AoE4 Spotify.exe";
        for (inp, want) in [
            (format!("{P}{o11} %command% -nomovies"), format!("{P}%command% -nomovies")),          // doubled (the real bug)
            (format!("{o11} %command% -nomovies -dev"), format!("{P}%command% -nomovies -dev")),     // old 1.1 path
            (format!("{o109} %command% +fps_max 144"), format!("{P}%command% +fps_max 144")),         // 1.0.9 path
            (format!("{unq} {o11} {o109} %command% -a"), format!("{P}%command% -a")),               // unquoted + many
            ("-nomovies -dev".to_string(), format!("{P}%command% -nomovies -dev")),                // plain user args
            ("PROTON_LOG=1 %command% -x".to_string(), format!("{P}PROTON_LOG=1 %command% -x")),     // other wrappers kept
            ("".to_string(), format!("{P}%command%")),
        ] { let n = compose(P, &inp); assert_eq!(n, want, "input {inp}"); assert_eq!(compose(P, &n), n, "idempotent {inp}"); }
        assert_eq!(user_args(&format!("{P}{o11} %command% -nomovies")), "-nomovies");
        assert_eq!(user_args("-nomovies"), "-nomovies");
    }
    #[test] fn toolhelp_sees_this_process() {
        let name = std::env::current_exe().unwrap().file_name().unwrap().to_string_lossy().to_string();
        assert!(proc_running(&name), "snapshot missed {name}");
        assert!(!proc_running("aoe4s_no_such_process.exe"));
    }
}
