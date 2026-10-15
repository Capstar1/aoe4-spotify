//! "Not invited yet" access guide (Tauri 1.1 ui/access.html) and "Your Spotify app" (ui/own.html).
//! Both follow the Windows app theme (re-read every 2 s) and fill their box from the clipboard while focused.
use crate::{AccessWin, OwnWin};
use aoe4engine::{guides::{self, Shell, Win}, Engine};
use slint::{ComponentHandle, Timer, TimerMode};
use std::{cell::RefCell, sync::Arc, time::Duration};

const MSG_BAD: &str = "That email wasn't accepted, check it and try again";
const CID_BAD: &str = "That isn't a Client ID. Copy the 32-character Client ID, not the Client Secret.";

/// access.html EMAIL_RE: local@domain.tld
pub fn email_valid(e: &str) -> bool {
    let Some((l, d)) = e.split_once('@') else { return false };
    let lok = !l.is_empty() && l.chars().all(|c| c.is_ascii_alphanumeric() || "._%+'-".contains(c));
    let parts: Vec<&str> = d.split('.').collect();
    let dok = parts.len() >= 2 && parts.iter().all(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_alphanumeric() || c == '-'));
    let tld = parts.last().unwrap_or(&""); lok && dok && tld.len() >= 2 && tld.chars().all(|c| c.is_ascii_alphabetic())
}
pub fn cid_valid(c: &str) -> bool { c.len() == 32 && c.chars().all(|c| c.is_ascii_hexdigit()) }
fn send_msg(r: &str) -> &'static str { match r { "bad" => MSG_BAD, "busy" => "Too many requests, try again later", "down" => "Couldn't reach the server, try later", _ => "Couldn't send, try again" } }

thread_local! {
    static ACC: RefCell<Option<(AccessWin, Vec<Timer>)>> = const { RefCell::new(None) };
    static OWN: RefCell<Option<(OwnWin, Vec<Timer>)>> = const { RefCell::new(None) };
}
fn acc() -> Option<AccessWin> { ACC.with(|a| a.borrow().as_ref().map(|(w, _)| w.clone_strong())) }
fn own() -> Option<OwnWin> { OWN.with(|a| a.borrow().as_ref().map(|(w, _)| w.clone_strong())) }

/// Clipboard + theme poll (250 ms; theme every 8th tick). `fill` gets new clipboard text.
fn poll(focused: impl Fn() -> bool + 'static, fill: impl Fn(String) + 'static, light: impl Fn(bool) + 'static) -> Timer {
    let t = Timer::default(); let last = RefCell::new(None::<String>); let n = std::cell::Cell::new(0u32);
    t.start(TimerMode::Repeated, Duration::from_millis(250), move || {
        if focused() { let c = guides::clip_text().trim().to_string(); if last.borrow().as_deref() != Some(&c) { *last.borrow_mut() = Some(c.clone()); fill(c); } }
        n.set(n.get() + 1); if n.get() % 8 == 0 { light(guides::windows_light()); }
    });
    t
}

pub fn open_access(eng: &Arc<Engine>, sh: &Arc<dyn Shell>) {
    if let Some(w) = acc() { let _ = w.show(); return; }
    let Ok(w) = AccessWin::new() else { return };
    let i = guides::access_info(eng);
    w.set_light(i["light"].as_bool().unwrap_or(false));
    if i["pending"].as_bool() == Some(true) { w.set_done(true); }
    let ww = w.as_weak();
    w.on_edited(move || if let Some(w) = ww.upgrade() { w.set_valid(email_valid(w.get_email().trim())); if w.get_note_err() { w.set_note("".into()); } });
    let sh2 = sh.clone(); w.on_open_own(move || sh2.show(Win::Own));
    let e = eng.clone(); w.on_open_account(move || { let e = e.clone(); std::thread::spawn(move || { aoe4engine::menu::menu(&e, "account"); }); });
    w.on_dismiss(close_access);
    let (e, ww) = (eng.clone(), w.as_weak());
    w.on_send(move || {
        let Some(w) = ww.upgrade() else { return }; let em = w.get_email().trim().to_string();
        if !email_valid(&em) || w.get_sending() || w.get_done() { return; }
        w.set_sending(true); let (e, ww) = (e.clone(), ww.clone());
        std::thread::spawn(move || { let r = guides::access_send(&e, &em);
            let _ = slint::invoke_from_event_loop(move || if let Some(w) = ww.upgrade() { w.set_sending(false);
                if r == "sent" || r == "wait" { w.set_done(true); } else { w.set_note(send_msg(&r).into()); w.set_note_err(true); } }); });
    });
    w.window().on_close_requested(|| { close_access(); slint::CloseRequestResponse::HideWindow });
    let (w1, w2, w3) = (w.as_weak(), w.as_weak(), w.as_weak());
    let clip = poll(move || w1.upgrade().is_some_and(|w| w.window().is_visible() && !w.get_done() && is_active(w.window())),
        move |c| if email_valid(&c) { if let Some(w) = w2.upgrade() { w.set_email(c.into()); w.set_valid(true); } },
        move |l| if let Some(w) = w3.upgrade() { w.set_light(l); });
    // rechecked every minute: closes itself once access works (-> good to go)
    let chk = Timer::default(); let (e, s) = (eng.clone(), sh.clone());
    chk.start(TimerMode::Repeated, Duration::from_secs(60), move || { let (e, s) = (e.clone(), s.clone()); std::thread::spawn(move || { guides::access_check(&s, &e); }); });
    ACC.with(|a| *a.borrow_mut() = Some((w.clone_strong(), vec![clip, chk])));
    let _ = w.show(); w.invoke_focus_entry();
}
pub fn close_access() { ACC.with(|a| if let Some((w, t)) = a.borrow_mut().take() { t.iter().for_each(|t| t.stop()); let _ = w.hide(); }); }

pub fn open_own(eng: &Arc<Engine>, sh: &Arc<dyn Shell>) {
    if let Some(w) = own() { let _ = w.show(); return; }
    let Ok(w) = OwnWin::new() else { return };
    w.set_light(guides::own_info(eng)["light"].as_bool().unwrap_or(false));
    let ww = w.as_weak();
    w.on_edited(move || if let Some(w) = ww.upgrade() { w.set_note("".into()); w.set_valid(cid_valid(w.get_cid().trim())); });
    let e = eng.clone(); w.on_dashboard(move || { let e = e.clone(); std::thread::spawn(move || { aoe4engine::menu::menu(&e, "dashboard"); }); });
    let e = eng.clone(); w.on_account(move || { let e = e.clone(); std::thread::spawn(move || { aoe4engine::menu::menu(&e, "account"); }); });
    let ww = w.as_weak();
    w.on_copy(move || { guides::set_clip_text("http://127.0.0.1:8888/callback"); if let Some(w) = ww.upgrade() { w.set_copied(true); }
        let ww = ww.clone(); Timer::single_shot(Duration::from_millis(1200), move || if let Some(w) = ww.upgrade() { w.set_copied(false); }); });
    let (e, s, ww) = (eng.clone(), sh.clone(), w.as_weak());
    w.on_save(move || {
        let Some(w) = ww.upgrade() else { return }; if w.get_busy() { return; }
        let c = w.get_cid().trim().to_string(); if !cid_valid(&c) { w.set_note(CID_BAD.into()); return; }
        w.set_busy(true); w.set_note("".into()); let (e, s, ww) = (e.clone(), s.clone(), ww.clone());
        std::thread::spawn(move || { let r = guides::own_save(&s, &e, &c);
            let _ = slint::invoke_from_event_loop(move || if let Some(w) = ww.upgrade() { w.set_busy(false); if r != "saved" { w.set_note(CID_BAD.into()); } }); });
    });
    let (e, s) = (eng.clone(), sh.clone()); w.on_shared(move || { let (e, s) = (e.clone(), s.clone()); std::thread::spawn(move || guides::own_shared(&s, &e)); });
    w.on_dismiss(close_own);
    w.window().on_close_requested(|| { close_own(); slint::CloseRequestResponse::HideWindow });
    let (w1, w2, w3) = (w.as_weak(), w.as_weak(), w.as_weak());
    let clip = poll(move || w1.upgrade().is_some_and(|w| w.window().is_visible() && is_active(w.window())),
        move |c| if cid_valid(&c) { if let Some(w) = w2.upgrade() { if w.get_cid().is_empty() { w.set_cid(c.into()); w.set_valid(true); } } },
        move |l| if let Some(w) = w3.upgrade() { w.set_light(l); });
    OWN.with(|a| *a.borrow_mut() = Some((w.clone_strong(), vec![clip])));
    let _ = w.show(); w.invoke_focus_entry();
}
pub fn close_own() { OWN.with(|a| if let Some((w, t)) = a.borrow_mut().take() { t.iter().for_each(|t| t.stop()); let _ = w.hide(); }); }

/// The clipboard is read only while the guide has the focus (like document.hasFocus()).
fn is_active(w: &slint::Window) -> bool { use slint::winit_030::WinitWindowAccessor; w.with_winit_window(|ww| ww.has_focus()).unwrap_or(false) }

/// Test switch AOE4S_GUIDE=access|access_done|access_note|own|own_note: fill a sample state.
pub fn test(kind: &str) {
    if let Some(w) = acc() { match kind {
        "access_done" => w.set_done(true),
        "access_note" => { w.set_email("capstar@example.com".into()); w.set_valid(true); w.set_note(MSG_BAD.into()); w.set_note_err(true); }
        _ => { w.set_email("capstar@example.com".into()); w.set_valid(true); } } }
    if let Some(w) = own() { if kind == "own_note" { w.set_cid("not-a-client-id".into()); w.set_note(CID_BAD.into()); } else { w.set_cid("0123456789abcdef0123456789abcdef".into()); w.set_valid(true); } }
}
pub fn snapshot(path: &str) {
    let save = |w: &slint::Window| if let Ok(b) = w.take_snapshot() { let _ = crate::save_png(path, b.as_bytes(), b.width(), b.height()); };
    if let Some(w) = acc() { save(w.window()); } if let Some(w) = own() { save(w.window()); }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn checks() {
        assert!(email_valid("a.b+c@mail.example.com") && !email_valid("a@b") && !email_valid("a b@c.de") && !email_valid("@c.de") && !email_valid("a@c.d1"));
        assert!(cid_valid("0123456789abcdef0123456789ABCDEF") && !cid_valid("0123") && !cid_valid("g123456789abcdef0123456789abcdef"));
    }
}
