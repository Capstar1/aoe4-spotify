//! Game log watcher and the Spotify worker (age music, After match).
use crate::{Engine, Status, data::{resolve, after_cfg}};
use aoe4core::aoe4::Aoe4;
use aoe4core::game::{GameAdapter, GameEvent};
use aoe4core::logtail::{Poll, Tail};
use aoe4core::switcher::{Action, Switcher};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// Spotify worker: actions run one after another so fades never overlap and the log watcher never blocks.
pub fn player(app: Arc<Engine>, rx: std::sync::mpsc::Receiver<Action>) {
    for a in rx {
        if let Action::AfterMatch { mode, playlist, wl, win, loss, fade_s } = &a {
            let r = after_match(&app, mode, playlist, *wl, win, loss, *fade_s);
            push(&app.status, match r { Ok(m) => format!("After match: {m}"), Err(e) => format!("After match failed: {e}") }); sync_logged(&app); continue;
        }
        let r = { let mut sp = app.spotify.lock().unwrap(); match &a {
            Action::AfterMatch { .. } => Ok(String::new()),
            Action::Play { age, uri, fade_s } => sp.play_age(uri, *fade_s).map(|_| format!("playing {uri} for {age}")),
            Action::Restore => sp.restore(app.settings.lock().unwrap().fade_seconds),
            Action::Stop => sp.fade_pause(app.settings.lock().unwrap().fade_seconds).map(|_| "stopped (faded out and paused)".to_string()),
        } };
        push(&app.status, match r { Ok(m) => format!("Spotify: {m}"), Err(e) => format!("Spotify error: {e}") });
        sync_logged(&app);
    }
}

/// 1.0.9 install_after_match (aoe4core::aftermatch): the app side - match status, condvar wait, Spotify under its lock per step.
pub struct Ctx<'a>(&'a Engine, std::time::Instant);
impl aoe4core::aftermatch::AfterCtx for Ctx<'_> {
    fn match_n(&self) -> u64 { self.0.status.lock().unwrap().match_n }
    fn result(&self) -> Option<i32> { self.0.status.lock().unwrap().result }
    fn wait(&self, d: Duration) { let g = self.0.status.lock().unwrap(); let _ = self.0.cv.wait_timeout(g, d); }
    fn elapsed(&self) -> Duration { self.1.elapsed() }
    fn play(&self, uri: &str, fade_s: f32) -> Result<(), String> { self.0.spotify.lock().unwrap().play_age(uri, fade_s) }
    fn state(&self) -> serde_json::Value { self.0.spotify.lock().unwrap().player_state() }
    fn forget_saved(&self) { self.0.spotify.lock().unwrap().forget_saved() }
    fn restore(&self, fade_s: f32) -> Result<String, String> { self.0.spotify.lock().unwrap().restore(fade_s) }
    fn fade_pause(&self, fade_s: f32) -> Result<(), String> { self.0.spotify.lock().unwrap().fade_pause(fade_s) }
    fn note(&self, line: String) { push(&self.0.status, line) }
}
pub fn after_match(app: &Engine, mode: &str, playlist: &str, wl: bool, win: &str, loss: &str, fade_s: f32) -> Result<String, String> {
    aoe4core::aftermatch::run(&Ctx(app, std::time::Instant::now()), mode, playlist, wl, win, loss, fade_s)
}
/// Login state for get_state without waiting on the Spotify lock (a fade holds it for seconds).
pub fn sync_logged(a: &Engine) { if let Ok(s) = a.spotify.lock() { a.logged.store(s.logged_in(), Ordering::SeqCst); } }

pub fn now() -> String {
    let s = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) + 2 * 3600;   // Oslo summer time (M1)
    format!("{:02}:{:02}:{:02}", (s / 3600) % 24, (s / 60) % 60, s % 60)
}

pub fn push(st: &Mutex<Status>, line: String) {
    crate::sys::log(&line);
    let mut s = st.lock().unwrap(); s.log.push(format!("{} {}", now(), line));
    let n = s.log.len(); if n > 200 { s.log.drain(..n - 200); }
}

pub fn watch(app: Arc<Engine>, path: PathBuf) {
    let la = std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap_or_default();
    let crc = la.join(r"Documents\My Games\Age of Empires IV\LogFiles");
    let mut game = Aoe4::new(Aoe4::datacrc_resolver(crc));
    let mut sw = { let s = app.settings.lock().unwrap(); let mut w = Switcher::new(s.enabled, s.fade_seconds, resolve(&s)); w.after = after_cfg(&s); w };
    let mut seen = app.ver.load(Ordering::SeqCst);
    let mut tail = Tail::new(path.clone());
    // catch-up: read what is already there silently (learn who you are), act only on new lines
    let mut catching = true;
    loop {
        let (lines, restarted) = match tail.poll() {
            Poll::Lines(v) => (v, false), Poll::Restarted(v) => (v, true),
            Poll::Missing => { app.status.lock().unwrap().watching = false; std::thread::sleep(Duration::from_secs(2)); continue; }
        };
        if restarted { game.reset_session(); push(&app.status, "Game log recreated (new game session)".into()); }
        app.status.lock().unwrap().watching = true;
        let v = app.ver.load(Ordering::SeqCst);
        if v != seen { seen = v; let s = app.settings.lock().unwrap(); sw.enabled = s.enabled; sw.fade_s = s.fade_seconds; sw.playlists = resolve(&s); sw.after = after_cfg(&s); }
        for l in lines {
            for ev in game.feed(&l) {
                if catching { continue; }
                push(&app.status, format!("event: {}", serde_json::to_string(&ev).unwrap_or_default()));
                match &ev {
                    GameEvent::MatchStart { .. } => { let mut s = app.status.lock().unwrap(); s.in_match = true; s.result = None; s.match_n += 1; drop(s); app.cv.notify_all(); }
                    GameEvent::MatchResult { result } => { app.status.lock().unwrap().result = Some(*result); app.cv.notify_all(); push(&app.status, (if *result == 1 { "Result: victory" } else { "Result: defeat" }).into()) }
                    GameEvent::MatchEnd { .. } | GameEvent::Replay => { let mut s = app.status.lock().unwrap(); s.in_match = false; s.age = None; }
                    GameEvent::Age { key, .. } => app.status.lock().unwrap().age = Some(key.clone()),
                    _ => {}
                }
                for a in sw.on_event(&ev) {
                    app.status.lock().unwrap().playing = match &a { Action::Play { uri, .. } => Some(uri.clone()), _ => None };
                    let _ = app.tx.lock().unwrap().send(a);
                }
            }
        }
        if catching { catching = false; push(&app.status, format!("Watching {}", path.display())); }
        std::thread::sleep(Duration::from_millis(250));
    }
}
