//! Text drops from Spotify onto our windows (Windows: OLE drop target in aoe4winsys::droptext; elsewhere none).
#[derive(Clone, Copy)]
pub enum Target { Panel, Add, Pick }

/// The native window handle, once winit has created the window (it does so lazily, after show()).
#[cfg(windows)]
pub fn native_hwnd(w: &slint::Window) -> Option<isize> {
    use slint::winit_030::winit::raw_window_handle::{HasWindowHandle, RawWindowHandle};
    use slint::winit_030::WinitWindowAccessor;
    w.with_winit_window(|ww| match ww.window_handle().map(|h| h.as_raw()) { Ok(RawWindowHandle::Win32(h)) => Some(h.hwnd.get()), _ => None }).flatten()
}
/// Run `f` with the native handle as soon as it exists (now, or retried every 30 ms for up to 10 s).
#[cfg(windows)]
pub fn when_native<C: slint::ComponentHandle + 'static>(c: &C, f: impl FnOnce(isize) + 'static) {
    if let Some(h) = native_hwnd(c.window()) { return f(h); }
    let w = c.as_weak(); let f = std::cell::RefCell::new(Some(f)); let n = std::cell::Cell::new(0);
    let t = std::rc::Rc::new(slint::Timer::default()); let t2 = std::rc::Rc::downgrade(&t);
    t.start(slint::TimerMode::Repeated, std::time::Duration::from_millis(30), move || {
        n.set(n.get() + 1);
        let h = w.upgrade().and_then(|c| native_hwnd(c.window()));
        if h.is_some() || n.get() > 333 { if let (Some(h), Some(f)) = (h, f.borrow_mut().take()) { f(h); } if let Some(t) = t2.upgrade() { t.stop(); } }
    });
    KEEP.with(|k| k.borrow_mut().push(t));
}
#[cfg(windows)]
thread_local! { static KEEP: std::cell::RefCell<Vec<std::rc::Rc<slint::Timer>>> = const { std::cell::RefCell::new(Vec::new()) }; }

/// Hook a window up: the age page / Add a song take song links, the picker takes playlist (or song) links.
#[cfg(windows)]
pub fn register<C: slint::ComponentHandle + 'static>(c: &C, t: Target) {
    use aoe4winsys::droptext::{self, Ev};
    when_native(c, move |h| { droptext::register(h, move |ev| match ev { Ev::Enter(s) => event(t, Some(s), false), Ev::Leave => event(t, None, false), Ev::Drop(s) => event(t, Some(s), true) }); });
}
#[cfg(not(windows))]
pub fn register<C: slint::ComponentHandle + 'static>(_c: &C, _t: Target) {}

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
