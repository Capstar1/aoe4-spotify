//! AOE4S_BTRTEST=<report file>: on-machine self-test of the real windows (run it on a hidden desktop, sandboxed APPDATA).
//! Drives OLE drops through each window's registered IDropTarget, the clipboard fill (AOE4S_CLIP stands in for the
//! clipboard), the live theme switch, Esc, DWM corners / shadow / hit-test frame, live Spotify reads (read-only), the
//! access status (no access request is sent), own-app validation and page opening (AOE4S_DRYOPEN). Writes PASS / FAIL
//! lines with counts only (no tokens, no account data) and quits.
#![cfg(windows)]
use aoe4engine::{guides::{self, Shell}, picker, Engine};
use slint::ComponentHandle;
use std::{io::Write, sync::{mpsc, Arc}, time::{Duration, Instant}};

/// Run `f` on the UI thread and wait for its result.
fn ui<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> T {
    let (tx, rx) = mpsc::channel(); let _ = slint::invoke_from_event_loop(move || { let _ = tx.send(f()); }); rx.recv().expect("ui thread gone")
}
fn hwnd(w: &slint::Window) -> isize {
    use slint::winit_030::winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
    use slint::winit_030::WinitWindowAccessor;
    w.with_winit_window(|ww| match ww.window_handle().map(|h| h.as_raw()) { Ok(RawWindowHandle::Win32(h)) => h.hwnd.get(), _ => 0 }).unwrap_or(0)
}
/// A window's handle once its native window exists.
fn wait_hwnd(f: impl Fn() -> isize + Send + Sync + Clone + 'static) -> isize { let t0 = Instant::now(); loop { let g = f.clone(); let h = ui(move || g()); if h != 0 || t0.elapsed().as_secs() >= 5 { return h; } std::thread::sleep(Duration::from_millis(100)); } }
fn wait(secs: f32, f: impl Fn() -> bool) -> bool { let t0 = Instant::now(); while t0.elapsed().as_secs_f32() < secs { if f() { return true; } std::thread::sleep(Duration::from_millis(100)); } f() }

struct Rep { f: std::fs::File, fails: usize }
impl Rep {
    fn ok(&mut self, name: &str, c: bool, info: &str) { if !c { self.fails += 1; } let _ = writeln!(self.f, "{} {name}{}", if c { "PASS" } else { "FAIL" }, if info.is_empty() { String::new() } else { format!(" ({info})") }); let _ = self.f.flush(); }
    fn note(&mut self, t: &str) { let _ = writeln!(self.f, "INFO {t}"); let _ = self.f.flush(); }
}

use crate::geom::Rect as R;
#[link(name = "dwmapi")] extern "system" { fn DwmGetWindowAttribute(h: isize, a: u32, v: *mut std::ffi::c_void, n: u32) -> i32; }
#[link(name = "user32")] extern "system" { fn GetWindowLongW(h: isize, i: i32) -> i32; fn GetWindowRect(h: isize, r: *mut R) -> i32; fn GetClientRect(h: isize, r: *mut R) -> i32; fn IsWindowVisible(h: isize) -> i32; }

/// No non-client area: the client rect fills the whole window (winit keeps WS_CAPTION for snap / shadow but removes the frame).
fn no_nc(h: isize) -> bool { unsafe { let (mut w, mut c) = (R::default(), R::default()); GetWindowRect(h, &mut w); GetClientRect(h, &mut c); w.r - w.l == c.r && w.b - w.t == c.b } }
/// DWM state of a window: (corner preference, NC rendering on, style, ex style, window rect == visible frame).
fn dwm(h: isize) -> (u32, u32, u32, u32, bool) {
    unsafe {
        let (mut c, mut n) = (0u32, 0u32); DwmGetWindowAttribute(h, 33, &mut c as *mut u32 as *mut _, 4); DwmGetWindowAttribute(h, 1, &mut n as *mut u32 as *mut _, 4);
        let (mut wr, mut fr) = (R::default(), R::default()); GetWindowRect(h, &mut wr); DwmGetWindowAttribute(h, 9, &mut fr as *mut R as *mut _, 16);
        let same = (wr.l - fr.l).abs() <= 1 && (wr.t - fr.t).abs() <= 1 && (wr.r - fr.r).abs() <= 1 && (wr.b - fr.b).abs() <= 1;
        (c, n, GetWindowLongW(h, -16) as u32, GetWindowLongW(h, -20) as u32, same)
    }
}

pub fn start(eng: Arc<Engine>, sh: Arc<dyn Shell>, out: String) {
    std::thread::spawn(move || {
        let Ok(f) = std::fs::File::create(&out) else { return };
        let mut r = Rep { f, fails: 0 };
        run(&eng, &sh, &mut r);
        r.note(&format!("done, {} failed", r.fails));
        let _ = slint::invoke_from_event_loop(|| { let _ = slint::quit_event_loop(); });
    });
}

fn run(eng: &Arc<Engine>, sh: &Arc<dyn Shell>, r: &mut Rep) {
    std::thread::sleep(Duration::from_millis(1500));
    // ---- panel window: shown, DWM rounded corners, shadow (DWM NC rendering), frame = hit-test area (shadow click-through)
    let ph = ui(|| crate::panel_hwnd()); r.ok("panel window shown", ph != 0 && unsafe { IsWindowVisible(ph) } != 0, "");
    if ph != 0 {
        let (c, n, st, ex, same) = dwm(ph);
        let hr = crate::ROUND_HR.load(std::sync::atomic::Ordering::SeqCst);
        r.ok("rounded corners: DWMWA_WINDOW_CORNER_PREFERENCE = round accepted", hr == 0, &format!("hr {hr:#x}, readback {c}"));
        r.ok("OLE: panel drop target registered", aoe4winsys::droptext::registered(ph) == Some(0), &format!("{:?}", aoe4winsys::droptext::registered(ph)));
        r.ok("shadow: DWM non-client rendering on", n == 1, &format!("{n}"));
        r.ok("borderless: no native frame / title bar (client = window)", no_nc(ph), &format!("style {st:#x}"));
        r.ok("panel takes clicks (not WS_EX_TRANSPARENT / LAYERED)", ex & 0x20 == 0 && ex & 0x80000 == 0, &format!("ex {ex:#x}"));
        r.ok("shadow click-through: input rect == visible frame (no invisible borders)", same, "");
    }
    // ---- live Spotify reads (read-only)
    let logged = eng.spotify.lock().unwrap().logged_in(); let fake = std::env::var_os("AOE4S_FAKESP").is_some();
    if !logged && fake { r.note("SKIP live Spotify: not logged in - Spotify flows below use fake data (AOE4S_FAKESP)"); } else {
    r.ok("Spotify logged in (sandbox copy of the real token)", logged, "");
    let st = guides::access_status(eng); r.ok("access status (GET /me, no request sent)", st == Some("ok"), &format!("{st:?}")); }
    let src = if fake && !logged { "fake" } else { "live" };
    let cnt = |v: &Result<serde_json::Value, String>| v.as_ref().ok().and_then(|v| v.as_array().map(|a| a.len()));
    let pls = picker::sp(eng, "playlists", ""); r.ok(&format!("{src}: your playlists"), cnt(&pls).unwrap_or(0) > 0, &format!("{:?} items", cnt(&pls)));
    let srch = picker::sp(eng, "search", "piano"); r.ok(&format!("{src}: search"), cnt(&srch).unwrap_or(0) > 0, &format!("{:?} items", cnt(&srch)));
    let play = picker::sp(eng, "playing", ""); r.ok(&format!("{src}: now playing (read)"), play.is_ok(), &format!("{:?} items", cnt(&play)));
    let tracks: Vec<String> = srch.as_ref().ok().and_then(|v| v.as_array().cloned()).unwrap_or_default().iter().filter_map(|t| t["uri"].as_str().map(String::from)).collect();
    if let Some(t) = tracks.first() { let id = t.rsplit(':').next().unwrap_or("").to_string(); let tr = picker::sp(eng, "tracks", &id); r.ok(&format!("{src}: track lookup"), cnt(&tr) == Some(1), ""); }
    let pl = pls.as_ref().ok().and_then(|v| v.as_array().cloned()).unwrap_or_default().iter().filter_map(|p| p["id"].as_str().filter(|i| i.len() == 22).map(String::from)).next()
        .or_else(|| if fake { Some("37i9dQZF1DX4sWSpwq3LiO".to_string()) } else { None });
    if let Some(p) = &pl { let m = picker::sp(eng, "plmeta", p); r.ok(&format!("{src}: playlist meta"), cnt(&m).unwrap_or(0) >= 1, ""); }
    // ---- OLE text drop on the age page
    ui(|| { crate::intros::test_state("age:castle"); });
    let have = || ui(|| crate::intros::have_uris());
    let link = |u: &str| format!("https://open.spotify.com/track/{}", u.rsplit(':').next().unwrap_or(""));
    let fresh: Vec<String> = { let h = have(); tracks.iter().filter(|t| !h.contains(t)).cloned().collect() };
    r.note(&format!("{} search tracks not yet in your intros", fresh.len()));
    if let Some(t) = fresh.first().cloned() {
        let (l, ph2) = (link(&t), ph);
        let ok = ui(move || aoe4winsys::droptext::simulate(ph2, &l, false)); r.ok("OLE: panel has a text drop target (enter/leave)", ok, "");
        r.ok("OLE: leave clears the drop highlight", !ui(crate::intros::drop_over), "");
        let l = link(&t); ui(move || aoe4winsys::droptext::simulate(ph2, &l, true));
        let t2 = t.clone(); r.ok("OLE: song link dropped on the age page is added", wait(8.0, move || have().contains(&t2)), "");
        let before = have().len(); ui(move || aoe4winsys::droptext::simulate(ph2, "hello, not a link", true)); std::thread::sleep(Duration::from_millis(800));
        r.ok("OLE: non-Spotify text is refused", have().len() == before, "");
    }
    // ---- Add a song window: OLE drop + search list + drag a row onto the age page
    { let e = eng.clone(); ui(move || crate::add::open(&e)); }
    let ah = wait_hwnd(|| crate::add::win().map(|w| hwnd(w.window())).unwrap_or(0)); r.ok("Add window open", ah != 0, "");
    r.ok("OLE: Add window drop target registered", aoe4winsys::droptext::registered(ah) == Some(0), "");
    if let Some(t) = fresh.get(1).cloned() {
        let l = link(&t); ui(move || aoe4winsys::droptext::simulate(ah, &l, true));
        let t2 = t.clone(); r.ok("OLE: song dropped on Add a song is added to the age", wait(8.0, move || have().contains(&t2)), "");
    }
    ui(|| { if let Some(w) = crate::add::win() { w.set_query("piano".into()); w.invoke_edited("piano".into()); } });
    r.ok("Add: live search fills the list", wait(10.0, || ui(crate::add::items_len) > 0), &format!("{} rows", ui(crate::add::items_len)));
    let h = have(); let idx = (0..ui(crate::add::items_len)).find(|i| { let i = *i; ui(move || crate::add::item_uri(i)).map_or(false, |u| !h.contains(&u)) });
    if let Some(i) = idx {
        let u = { let i2 = i; ui(move || crate::add::item_uri(i2)).unwrap_or_default() };
        // a point inside the panel, in the Add window's logical coordinates
        let dropped = ui(move || {
            let (Some(a), Some(p)) = (crate::add::win(), crate::panel()) else { return false };
            let (aw, pw) = (a.window(), p.window()); let (sa, sp) = (aw.scale_factor(), pw.scale_factor());
            let gx = pw.position().x as f32 + 200.0 * sp; let gy = pw.position().y as f32 + 300.0 * sp;
            let (x, y) = ((gx - aw.position().x as f32) / sa, (gy - aw.position().y as f32) / sa);
            a.invoke_drag(i as i32, "move".into(), x, y); let lit = crate::intros::drop_over();
            a.invoke_drag(i as i32, "drop".into(), x, y); lit
        });
        r.ok("drag from the Add list: age page lights up while over the panel", dropped, "");
        r.ok("drag from the Add list: dropped song is added", wait(5.0, move || have().contains(&u)), "");
        r.ok("drag from the Add list: highlight off after the drop", !ui(crate::intros::drop_over), "");
    }
    ui(crate::add::close);
    // ---- picker: OLE drop of a playlist link sets the age playlist
    if let Some(p) = pl.clone() {
        let cur = eng.settings.lock().unwrap().playlists.get("castle").cloned().unwrap_or_default();
        picker::open_pick(eng, "age:castle", "Castle Age playlist", false, &cur);
        { let e = eng.clone(); ui(move || crate::pick::open(&e)); }
        let kh = wait_hwnd(|| crate::pick::win().map(|w| hwnd(w.window())).unwrap_or(0)); r.ok("picker open", kh != 0, &format!("window object: {}", ui(|| crate::pick::win().is_some())));
        r.ok("OLE: picker drop target registered", aoe4winsys::droptext::registered(kh) == Some(0), "");
        let l = format!("https://open.spotify.com/playlist/{p}?si=x"); ui(move || aoe4winsys::droptext::simulate(kh, &l, true));
        let want = format!("spotify:playlist:{p}"); let e = eng.clone();
        r.ok("OLE: playlist link dropped on the picker sets the Castle playlist", wait(8.0, move || e.settings.lock().unwrap().playlists.get("castle") == Some(&want)), "");
        r.ok("picker closes after the drop", wait(3.0, || ui(|| crate::pick::win().is_none())), "");
    }
    // ---- Esc on the age page goes back
    ui(|| { if let Some(p) = crate::panel() { p.invoke_refocus(); p.window().dispatch_event(slint::platform::WindowEvent::KeyPressed { text: slint::platform::Key::Escape.into() }); p.window().dispatch_event(slint::platform::WindowEvent::KeyReleased { text: slint::platform::Key::Escape.into() }); } });
    r.ok("Esc: age page -> Age Intros", wait(2.0, || ui(crate::intros::page) != "age"), &ui(crate::intros::page));
    // ---- access guide: clipboard fill (AOE4S_CLIP), theme switch, Esc
    std::env::set_var("AOE4S_CLIP", "capstar.btrtest@example.com");
    sh.show(guides::Win::Access);
    let gh = wait_hwnd(|| crate::access::acc().map(|w| hwnd(w.window())).unwrap_or(0));
    r.ok("access guide open", gh != 0, "");
    let email = || ui(|| crate::access::acc().map(|w| w.get_email().to_string()).unwrap_or_default());
    r.ok("clipboard: not read while the guide is unfocused (hidden desktop)", !wait(1.5, move || email() == "capstar.btrtest@example.com"), "");
    std::env::set_var("AOE4S_FOCUSED", "1");
    r.ok("clipboard: copied email fills the access box (focused)", wait(4.0, move || email() == "capstar.btrtest@example.com"), "");
    r.ok("access: send button enabled for a valid email", ui(|| crate::access::acc().map(|w| w.get_valid()).unwrap_or(false)), "");
    std::env::set_var("AOE4S_LIGHT", "1"); r.ok("theme: guide follows a switch to light (live, <= 2 s poll)", wait(4.0, || ui(|| crate::access::acc().map(|w| w.get_light()).unwrap_or(false))), "");
    std::env::set_var("AOE4S_LIGHT", "0"); r.ok("theme: and back to dark", wait(4.0, || !ui(|| crate::access::acc().map(|w| w.get_light()).unwrap_or(true))), "");
    std::env::remove_var("AOE4S_LIGHT"); r.note(&format!("Windows theme read from the registry: {}", if guides::windows_light() { "light" } else { "dark" }));
    r.ok("access: invalid email is refused locally (nothing sent)", guides::access_send(eng, "not-an-email") == "bad", "");
    ui(|| { if let Some(w) = crate::access::acc() { w.invoke_dismiss(); } });
    r.ok("Esc / close: access guide closes", wait(2.0, || ui(|| crate::access::acc().is_none())), "");
    // ---- Your Spotify app: clipboard fill + validation (no save: that would switch the app and drop the login)
    std::env::set_var("AOE4S_CLIP", "0123456789abcdef0123456789abcdef");
    sh.show(guides::Win::Own);
    let _ = wait(3.0, || ui(|| crate::access::own().is_some()));
    r.ok("clipboard: copied Client ID fills the box", wait(4.0, || ui(|| crate::access::own().map(|w| w.get_cid().to_string()).unwrap_or_default()) == "0123456789abcdef0123456789abcdef"), "");
    r.ok("own app: valid Client ID shows the check", ui(|| crate::access::own().map(|w| w.get_valid()).unwrap_or(false)), "");
    ui(|| { if let Some(w) = crate::access::own() { w.set_cid("my-client-secret-looking-xxxxxxxx".into()); w.invoke_edited(); w.invoke_save(); } });
    r.ok("own app: a non-Client-ID is refused with the note", ui(|| crate::access::own().map(|w| !w.get_note().is_empty() && !w.get_busy()).unwrap_or(false)), "");
    r.ok("own app: settings unchanged", !eng.settings.lock().unwrap().own_app, "");
    r.ok("own app: engine refuses a bad id too", guides::own_save(sh, eng, "xyz") == "bad", "");
    ui(|| { if let Some(w) = crate::access::own() { w.invoke_dismiss(); } });
    std::env::remove_var("AOE4S_CLIP"); std::env::remove_var("AOE4S_FOCUSED");
    // ---- opening pages: logged (AOE4S_DRYOPEN), never opened
    for k in ["account", "dashboard", "github", "log"] { aoe4engine::menu::menu(eng, k); }
    let dry = std::env::var("AOE4S_DRYOPEN").ok().and_then(|f| std::fs::read_to_string(f).ok()).unwrap_or_default();
    r.ok("pages: account / dashboard / GitHub / log were logged, not opened", ["spotify.com/account", "developer.spotify.com/dashboard", "github.com/Capstar1", "aoe4_spotify.log"].iter().all(|s| dry.contains(s)), &format!("{} lines", dry.lines().count()));
}
