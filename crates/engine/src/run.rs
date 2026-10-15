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

/// One queued music change. `after_intro` is the intro track already started; the playlist runs when it ends.
/// `waited` is set once this change held for a track with a minute or less left. The intro plays only then.
struct Job { a: Action, after_intro: Option<String>, waited: bool }
impl Job { fn new(a: Action) -> Self { Self { a, after_intro: None, waited: false } } }

fn holdable(a: &Action) -> bool {
    matches!(a, Action::Play { .. } | Action::Stop | Action::AfterMatch { .. } | Action::HandBack)
}

fn heard(v: &serde_json::Value) -> Option<aoe4core::finish::Heard> {
    let uri = v["item"]["uri"].as_str().unwrap_or("").to_string();
    if uri.is_empty() { return None; }
    Some(aoe4core::finish::Heard {
        uri,
        pos_ms: v["progress_ms"].as_i64().unwrap_or(0),
        dur_ms: v["item"]["duration_ms"].as_i64().unwrap_or(0),
        playing: v["is_playing"].as_bool() == Some(true),
    })
}

fn nap(h: Option<&aoe4core::finish::Heard>) -> Duration {
    let ms = match h {
        Some(h) if h.playing && h.dur_ms > 0 => (h.dur_ms - h.pos_ms - 1500).clamp(400, 2000) as u64,
        _ => 500,
    };
    Duration::from_millis(ms)
}

/// Wait out the latched track when a minute or less remains. An intro already started always waits.
/// A newer age or after-match action replaces the queued one.
/// Restore (replay off, disabled, game closed) runs immediately and drops the queue.
/// None means the action channel closed. More than a minute left returns the job unwaited.
fn hold(app: &Engine, rx: &std::sync::mpsc::Receiver<Action>, mut job: Job) -> Option<Job> {
    use aoe4core::finish::{release, within_minute, Latch};
    use std::sync::mpsc::RecvTimeoutError;
    let snap = { let v = app.spotify.lock().unwrap().player_state(); heard(&v) };
    let mut latch = if let Some(uri) = job.after_intro.clone() {
        Latch::expect(uri)
    } else {
        match snap.as_ref() { Some(h) if within_minute(h) => Latch::playing(h.uri.clone()), _ => return Some(job) }
    };
    job.waited = true;
    let label = |a: &Action| match a {
        Action::Play { age, .. } => format!("play {age}"),
        Action::HandBack => "hand Spotify back".into(),
        Action::Stop => "stop".into(),
        Action::AfterMatch { .. } => "after match".into(),
        Action::Restore => "restore".into(),
    };
    push(&app.status, format!("Finish song first: waiting to {}", label(&job.a)));
    let mut heard_now = snap;
    let started = std::time::Instant::now();
    let mut blanks = 0u8;
    loop {
        if !app.finish.load(Ordering::SeqCst) { return Some(job); }
        match rx.recv_timeout(nap(heard_now.as_ref())) {
            Ok(a) if holdable(&a) => {
                job = Job { a, after_intro: None, waited: true };
                push(&app.status, format!("Finish song first: waiting to {}", label(&job.a)));
            }
            Ok(a) => return Some(Job::new(a)),
            Err(RecvTimeoutError::Disconnected) => return None,
            Err(RecvTimeoutError::Timeout) => {
                heard_now = { let v = app.spotify.lock().unwrap().player_state(); heard(&v) };
                if !latch.seen && started.elapsed() > Duration::from_secs(8) { return Some(job); }
                // One empty reply is a failed poll or the gap between tracks. Two in a row means the player is idle.
                if heard_now.is_none() {
                    if latch.seen {
                        blanks += 1;
                        if blanks >= 2 { return Some(job); }
                    }
                } else {
                    blanks = 0;
                    if release(&mut latch, heard_now.as_ref()) { return Some(job); }
                }
            }
        }
    }
}

fn intro_memory(dir: &std::path::Path) -> serde_json::Value { aoe4core::userstore::read_json(&dir.join("intro_last.json")) }

/// Spotify worker: actions run one after another so fades never overlap and the log watcher never blocks.
/// With Finish song first on, that change waits when the track already playing has a minute or less left.
pub fn player(app: Arc<Engine>, rx: std::sync::mpsc::Receiver<Action>) {
    let mut queued: Option<Job> = None;
    loop {
        let job = match queued.take() {
            Some(j) => j,
            None => match rx.recv() { Ok(a) => Job::new(a), Err(_) => return },
        };
        let job = if holdable(&job.a) && (job.after_intro.is_some() || app.finish.load(Ordering::SeqCst)) {
            match hold(&app, &rx, job) { Some(j) => j, None => return }
        } else { job };
        app.spotify.lock().unwrap().reload_token();
        if let Some(next) = run_job(&app, job) { queued = Some(next); }
        sync_logged(&app);
    }
}

/// Some(job) means an intro just started and `job` is the playlist that follows it.
fn run_job(app: &Engine, job: Job) -> Option<Job> {
    if let Action::Play { age, fade_s, .. } = &job.a {
        if job.after_intro.is_none() && job.waited && app.finish.load(Ordering::SeqCst) {
            let civ = app.status.lock().unwrap().civ.clone().unwrap_or_default();
            let s = { let s = app.settings.lock().unwrap().clone(); crate::data::with_ed(&s, &crate::data::load_ed(&app.dir)) };
            let mem = intro_memory(&app.dir);
            let last = mem[&civ].as_str();
            let n = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.subsec_nanos() as u64).unwrap_or(0);
            if let Some(track) = aoe4core::intros::intro_track(&s, age, &civ, last, n) {
                let fade = *fade_s;
                let r = { let mut sp = app.spotify.lock().unwrap(); sp.play_age(&track, fade) };
                push(&app.status, match &r { Ok(()) => format!("Spotify: {age} intro {track}"), Err(e) => format!("Spotify error: {e}") });
                if r.is_ok() {
                    let mut m = mem; m[&civ] = serde_json::json!(track);
                    let _ = aoe4core::userstore::write_atomic(&app.dir.join("intro_last.json"), &m);
                    return Some(Job { a: job.a, after_intro: Some(track), waited: true });
                }
            }
        }
    }
    if let Action::AfterMatch { mode, playlist, wl, win, loss, fade_s } = &job.a {
        let r = after_match(app, mode, playlist, *wl, win, loss, *fade_s);
        push(&app.status, match r { Ok(m) => format!("After match: {m}"), Err(e) => format!("After match failed: {e}") });
        return None;
    }
    let r = { let mut sp = app.spotify.lock().unwrap(); match &job.a {
        Action::AfterMatch { .. } => Ok(String::new()),
        Action::Play { age, uri, fade_s } => sp.play_age(uri, *fade_s).map(|_| format!("playing {uri} for {age}")),
        Action::HandBack | Action::Restore => sp.restore(app.settings.lock().unwrap().fade_seconds),
        Action::Stop => sp.fade_pause(app.settings.lock().unwrap().fade_seconds).map(|_| "stopped (faded out and paused)".to_string()),
    } };
    push(&app.status, match r { Ok(m) => format!("Spotify: {m}"), Err(e) => format!("Spotify error: {e}") });
    None
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
        if pref != prefs_stamp {
            prefs_stamp = pref;
            app.replays.store(aoe4core::userstore::replays(&app.dir, app.replays.load(Ordering::SeqCst)), Ordering::SeqCst);
            app.finish.store(aoe4core::userstore::finish_song(&app.dir, false), Ordering::SeqCst);
        }
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
                    GameEvent::MatchStart { civ } => { let mut s = app.status.lock().unwrap(); s.in_match = true; s.result = None; s.match_n += 1; s.civ = civ.clone(); drop(s); app.cv.notify_all(); }
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
