//! Text drops from Spotify onto our windows (Windows: OLE drop target in aoe4winsys::droptext; elsewhere none).
#[derive(Clone, Copy)]
pub enum Target { Panel, Add, Pick }

/// Hook a window up: the age page / Add a song take song links, the picker takes playlist (or song) links.
#[cfg(windows)]
pub fn register(w: &slint::Window, t: Target) {
    use aoe4winsys::droptext::{self, Ev};
    use slint::winit_030::winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
    use slint::winit_030::WinitWindowAccessor;
    w.with_winit_window(|ww| { if let Ok(h) = ww.window_handle() { if let RawWindowHandle::Win32(h) = h.as_raw() {
        droptext::register(h.hwnd.get(), move |ev| match ev { Ev::Enter(s) => event(t, Some(s), false), Ev::Leave => event(t, None, false), Ev::Drop(s) => event(t, Some(s), true) });
    } } });
}
#[cfg(not(windows))]
pub fn register(_w: &slint::Window, _t: Target) {}

/// One drag event: `text` None = left; `drop` = released.
#[cfg_attr(not(windows), allow(dead_code))]
pub fn event(t: Target, text: Option<String>, drop: bool) {
    match t {
        Target::Panel => { crate::intros::drag_over(text.is_some() && !drop); if drop { if let Some(s) = text { crate::intros::drop_on_page(s); } } }
        Target::Add => { let n = text.as_deref().map_or(0, |s| crate::add::track_ids(s).len()); crate::add::zone(text.is_some() && !drop, n);
            if drop { if let Some(s) = text { if crate::add::track_ids(&s).is_empty() { crate::add::say("Drop a Spotify song or song link", true); } else { crate::intros::drop_text(s); } } } }
        Target::Pick => crate::pick::drag(text, drop),
    }
}
