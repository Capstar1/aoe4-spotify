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
        app.spotify.lock().unwrap().reload_token();
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

/// Steam launch passes `skip_older_than` (now − 2 s) so the previous session's log is not replayed. `--attach` passes none.
pub struct WatchOpts { pub skip_older_than: Option<SystemTime> }

pub fn watch(app: Arc<Engine>, path: PathBuf, opts: WatchOpts) {
    let la = std::env::var_os("USERPROFILE").map(PathBuf::from).unwrap_or_default();
    let crc = la.join(r"Documents\My Games\Age of Empires IV\LogFiles");
    let mut game = Aoe4::new(Aoe4::datacrc_resolver(crc));
    let mut sw = { let s = app.settings.lock().unwrap(); let mut w = Switcher::new(s.enabled, s.fade_seconds, resolve(&s)); w.after = after_cfg(&s); w.start_delay = 3.0; w };
    let mut seen = app.ver.load(Ordering::SeqCst);
    let mut tail = Tail::new(path.clone());
    let mut prefs_stamp: Option<(SystemTime, u64)> = None;
    let cfg_path = app.dir.join("config.json");
    let mut cfg_stamp = file_stamp(&cfg_path);
    let mut was_enabled = sw.enabled;
    let mut skip_until = opts.skip_older_than;
    // catch-up: read what is already there silently (learn who you are), act only on new lines
    let mut catching = true;
    let mut published: Option<(bool, Option<String>, Option<String>)> = None;
    loop {
        if app.stop.load(Ordering::Relaxed) { break; }
        apply_cfg(&app, &mut sw, &mut cfg_stamp, &mut was_enabled, &cfg_path);
        // Music in replays is its own file. A newer file (the panel) wins when its mtime changes. Do not reset the match.
        let pref = std::fs::metadata(app.dir.join("settings.json")).ok().and_then(|m| m.modified().ok().map(|t| (t, m.len())));
        if pref != prefs_stamp { prefs_stamp = pref; app.replays.store(aoe4core::userstore::replays(&app.dir, app.replays.load(Ordering::SeqCst)), Ordering::SeqCst); }
        let replay_on = app.replays.load(Ordering::SeqCst);
        game.replay_music = replay_on;
        sw.music_in_replays = replay_on;
        if let Some(cut) = skip_until {
            match std::fs::metadata(&path) {
                Err(_) => {}
                Ok(m) => {
                    let old = m.modified().map(|t| t < cut).unwrap_or(false);
                    skip_until = None;
                    if old && tail.skip_to_end() {
                        push(&app.status, "Game log is from the previous session - waiting for the new one".into());
                        push(&app.status, format!("Watching {}", path.display()));
                        catching = false;
                    }
                }
            }
        }
        if !catching { sw.set_now(crate::wall()); }
        let (lines, restarted) = match tail.poll() {
            Poll::Lines(v) => (v, false), Poll::Restarted(v) => (v, true),
            Poll::Missing => {
                app.status.lock().unwrap().watching = false;
                for _ in 0..8 { if app.stop.load(Ordering::Relaxed) { return; } std::thread::sleep(Duration::from_millis(250)); }
                continue;
            }
        };
        if restarted {
            game.reset_session();
            { let mut s = app.status.lock().unwrap(); s.in_match = false; s.age = None; s.playing = None; }
            push(&app.status, "Game log recreated (new game session)".into());
        }
        app.status.lock().unwrap().watching = true;
        let v = app.ver.load(Ordering::SeqCst);
        if v != seen {
            seen = v; let s = app.settings.lock().unwrap().clone(); let now_on = s.enabled;
            sw.enabled = now_on; sw.fade_s = s.fade_seconds; sw.playlists = resolve(&s); sw.after = after_cfg(&s);
            if was_enabled && !now_on { deliver(&app, Action::Restore); }
            was_enabled = now_on;
        }
        for l in lines {
            for ev in game.feed(&l) {
                if catching { continue; }
                push(&app.status, format!("event: {}", serde_json::to_string(&ev).unwrap_or_default()));
                match &ev {
                    GameEvent::MatchStart { .. } => { let mut s = app.status.lock().unwrap(); s.in_match = true; s.result = None; s.match_n += 1; drop(s); app.cv.notify_all(); }
                    GameEvent::MatchResult { result } => { app.status.lock().unwrap().result = Some(*result); app.cv.notify_all(); push(&app.status, (if *result == 1 { "Result: victory" } else { "Result: defeat" }).into()) }
                    GameEvent::Replay => {
                        if game.watching() {
                            push(&app.status, "Replay detected - Music in replays is on, following it".into());
                        } else {
                            let mut s = app.status.lock().unwrap();
                            let late = s.playing.is_some();
                            s.in_match = false; s.age = None; s.playing = None;
                            drop(s);
                            push(&app.status, "Replay detected - ignoring this match".into());
                            // The 3 s start delay usually cancels the play before it starts. If the marker
                            // arrives after that play already went out, hand Spotify back.
                            if late { deliver(&app, Action::Restore); }
                            else { push(&app.status, "Match start cancelled (replay / ended)".into()); }
                        }
                    }
                    GameEvent::MatchEnd { .. } => { let mut s = app.status.lock().unwrap(); s.in_match = false; s.age = None; }
                    // A watched replay must not move the fire until the settled play actually starts.
                    GameEvent::Age { key, .. } if !game.watching() => app.status.lock().unwrap().age = Some(key.clone()),
                    _ => {}
                }
                for a in sw.on_event(&ev) { deliver(&app, a); }
            }
        }
        if !catching { for a in sw.poll() { deliver(&app, a); } }
        if catching { catching = false; push(&app.status, format!("Watching {}", path.display())); }
        if app.stop.load(Ordering::Relaxed) { break; }
        publish_now(&app, &mut published);
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn file_stamp(p: &std::path::Path) -> Option<(SystemTime, u64)> {
    std::fs::metadata(p).ok().and_then(|m| m.modified().ok().map(|t| (t, m.len())))
}
/// Panel writes config.json. Reload when the file's mtime or length changes. Do not reset the match.
/// Turning Enabled off hands the music back once and leaves the switcher running until the game closes.
fn apply_cfg(app: &Engine, sw: &mut Switcher, stamp: &mut Option<(SystemTime, u64)>, was_enabled: &mut bool, cfg: &std::path::Path) {
    let now = file_stamp(cfg);
    if now == *stamp { return; }
    *stamp = now;
    let s = aoe4core::settings::load_own(&app.dir);
    let now_on = s.enabled;
    { *app.settings.lock().unwrap() = s.clone(); }
    sw.enabled = s.enabled; sw.fade_s = s.fade_seconds; sw.playlists = resolve(&s); sw.after = after_cfg(&s);
    if *was_enabled && !now_on { deliver(app, Action::Restore); }
    *was_enabled = now_on;
}
fn publish_now(app: &Engine, last: &mut Option<(bool, Option<String>, Option<String>)>) {
    let cur = { let s = app.status.lock().unwrap(); (s.in_match, s.age.clone(), s.playing.clone()) };
    if last.as_ref() == Some(&cur) { return; }
    *last = Some(cur.clone());
    let _ = aoe4core::userstore::write_now(&app.dir, cur.0, cur.1.as_deref(), cur.2.as_deref());
}

fn deliver(app: &Engine, a: Action) {
    {
        let mut s = app.status.lock().unwrap();
        match &a {
            Action::Play { age, uri, .. } => { s.in_match = true; s.age = Some(age.clone()); s.playing = Some(uri.clone()); }
            _ => s.playing = None,
        }
    }
    let _ = app.tx.lock().unwrap().send(a);
}
