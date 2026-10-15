//! Game log watcher and the Spotify worker (age music, After match).
use crate::{Engine, Status, data::{resolve, after_cfg}};
use aoe4core::aoe4::Aoe4;
use aoe4core::boss::{intro_nap, intro_poll, Cue, IntroPoll, Seq, Step};
use aoe4core::finish::{release, within_minute, Heard, Latch};
use aoe4core::game::{GameAdapter, GameEvent};
use aoe4core::logtail::{Poll, Tail};
use aoe4core::switcher::{Action, Switcher};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::{Arc, Mutex};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

fn holdable(a: &Action) -> bool {
    matches!(a, Action::Play { .. } | Action::Stop | Action::AfterMatch { .. } | Action::HandBack)
}

fn heard(v: &serde_json::Value) -> Option<Heard> {
    let uri = v["item"]["uri"].as_str().unwrap_or("").to_string();
    if uri.is_empty() { return None; }
    Some(Heard {
        uri,
        pos_ms: v["progress_ms"].as_i64().unwrap_or(0),
        dur_ms: v["item"]["duration_ms"].as_i64().unwrap_or(0),
        playing: v["is_playing"].as_bool() == Some(true),
    })
}

fn nap(h: Option<&Heard>) -> Duration {
    let ms = match h {
        Some(h) if h.playing && h.dur_ms > 0 => (h.dur_ms - h.pos_ms - 1500).clamp(400, 2000) as u64,
        _ => 500,
    };
    Duration::from_millis(ms)
}

fn label(a: &Action) -> String {
    match a {
        Action::Play { age, .. } => format!("play {age}"),
        Action::HandBack => "hand Spotify back".into(),
        Action::Stop => "stop".into(),
        Action::AfterMatch { .. } => "after match".into(),
        Action::Restore => "restore".into(),
    }
}

fn intro_memory(dir: &std::path::Path) -> serde_json::Value { aoe4core::userstore::read_json(&dir.join("intro_last.json")) }

/// Intro for this age, from the local civ pools. No Spotify call.
fn make_cue(app: &Engine, age: &str, playlist: &str, fade_s: f32) -> Cue {
    let civ = app.status.lock().unwrap().civ.clone().unwrap_or_default();
    let settings = app.settings.lock().unwrap().clone();
    let edited = crate::data::with_ed(&settings, &crate::data::load_ed(&app.dir));
    let mem = intro_memory(&app.dir);
    let last = mem[&civ].as_str();
    let n = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.subsec_nanos() as u64).unwrap_or(0);
    Cue { age: age.to_string(), playlist: playlist.to_string(), intro: aoe4core::intros::intro_track(&edited, age, &civ, last, n), fade_s }
}

fn remember_intro(app: &Engine, track: &str) {
    let civ = app.status.lock().unwrap().civ.clone().unwrap_or_default();
    if civ.is_empty() { return; }
    let mut m = intro_memory(&app.dir);
    m[&civ] = serde_json::json!(track);
    let _ = aoe4core::userstore::write_atomic(&app.dir.join("intro_last.json"), &m);
}

#[derive(Clone, Copy)]
enum WaitOn { Track, Intro }

enum WaitOut { Steps(Vec<Step>), Now(Action), Closed }

enum Drive { Done, Exit, Follow(Action) }

/// Wait out `latch`. The first Spotify read happens after the nap, so a gate snapshot already in
/// `heard_now` is not fetched again before the intro. Finish song first is ignored during an intro.
/// An intro pauses its clock: a pause does not release, and if the track reaches the handoff while
/// paused the playlist waits until playback resumes. A skip releases at once.
fn wait(app: &Engine, rx: &std::sync::mpsc::Receiver<Action>, seq: &mut Seq, mode: WaitOn, mut latch: Latch, mut heard_now: Option<Heard>, mut preempt: Option<Action>) -> WaitOut {
    use std::sync::mpsc::RecvTimeoutError;
    let started = std::time::Instant::now();
    let mut blanks = 0u8;
    let mut held = false;
    let mut hold_said = false;
    loop {
        if matches!(mode, WaitOn::Track) && !app.finish.load(Ordering::SeqCst) {
            if let Some(a) = preempt.take() { seq.clear(); return WaitOut::Now(a); }
            return WaitOut::Steps(seq.finish_off());
        }
        let delay = match mode {
            WaitOn::Intro => intro_nap(heard_now.as_ref()),
            WaitOn::Track => nap(heard_now.as_ref()),
        };
        match rx.recv_timeout(delay) {
            Ok(Action::Play { age, uri, fade_s }) => {
                let cue = make_cue(app, &age, &uri, fade_s);
                preempt = None;
                match mode {
                    WaitOn::Intro => { let _ = seq.age(false, None, cue); }
                    WaitOn::Track => {
                        push(&app.status, format!("Finish song first: waiting to play {age}"));
                        seq.hold(cue);
                    }
                }
            }
            Ok(a) if holdable(&a) => match mode {
                WaitOn::Intro => { seq.clear(); return WaitOut::Now(a); }
                WaitOn::Track => {
                    seq.clear();
                    push(&app.status, format!("Finish song first: waiting to {}", label(&a)));
                    preempt = Some(a);
                }
            },
            Ok(a) => { seq.clear(); return WaitOut::Now(a); }
            Err(RecvTimeoutError::Disconnected) => return WaitOut::Closed,
            Err(RecvTimeoutError::Timeout) => {
                heard_now = { let v = app.spotify.lock().unwrap().player_state(); heard(&v) };
                if !latch.seen && started.elapsed() > Duration::from_secs(8) { return finish_wait(seq, preempt); }
                if heard_now.is_none() {
                    if latch.seen {
                        blanks += 1;
                        if blanks >= 2 { return finish_wait(seq, preempt); }
                    }
                } else {
                    blanks = 0;
                    match mode {
                        WaitOn::Track => { if release(&mut latch, heard_now.as_ref()) { return finish_wait(seq, preempt); } }
                        WaitOn::Intro if held => {
                            let skip = heard_now.as_ref().is_some_and(|h| h.uri != latch.uri);
                            let resumed = heard_now.as_ref().is_some_and(|h| h.playing);
                            if skip || resumed { return finish_wait(seq, preempt); }
                        }
                        WaitOn::Intro => match intro_poll(&mut latch, heard_now.as_ref()) {
                            IntroPoll::Release => return finish_wait(seq, preempt),
                            IntroPoll::Hold => {
                                held = true;
                                if !hold_said {
                                    hold_said = true;
                                    push(&app.status, "Spotify paused by user - holding the playlist until resume".into());
                                }
                            }
                            IntroPoll::Stay { .. } => {}
                        },
                    }
                }
            }
        }
    }
}

fn finish_wait(seq: &mut Seq, preempt: Option<Action>) -> WaitOut {
    if let Some(a) = preempt { seq.clear(); WaitOut::Now(a) } else { WaitOut::Steps(seq.released()) }
}

fn drive(app: &Engine, rx: &std::sync::mpsc::Receiver<Action>, seq: &mut Seq, mut steps: Vec<Step>, mut gate_heard: Option<Heard>) -> Drive {
    while !steps.is_empty() {
        match steps.remove(0) {
            Step::Wait => {
                let Some(h) = gate_heard.take() else { steps = seq.released(); continue };
                match wait(app, rx, seq, WaitOn::Track, Latch::playing(h.uri.clone()), Some(h), None) {
                    WaitOut::Steps(s) => steps = s,
                    WaitOut::Now(a) => return Drive::Follow(a),
                    WaitOut::Closed => return Drive::Exit,
                }
            }
            Step::Intro { age, track, fade_s } => {
                let r = { let mut sp = app.spotify.lock().unwrap(); sp.reload_token(); sp.play_intro(&track, fade_s) };
                push(&app.status, match &r { Ok(()) => format!("Spotify: {age} intro {track}"), Err(e) => format!("Spotify error: {e}") });
                if r.is_ok() {
                    remember_intro(app, &track);
                    sync_logged(app);
                    match wait(app, rx, seq, WaitOn::Intro, Latch::expect(track), None, None) {
                        WaitOut::Steps(s) => steps = s,
                        WaitOut::Now(a) => return Drive::Follow(a),
                        WaitOut::Closed => return Drive::Exit,
                    }
                } else {
                    steps = seq.released();
                }
            }
            Step::Playlist { age, uri, fade_s } => {
                let r = { let mut sp = app.spotify.lock().unwrap(); sp.reload_token(); sp.play_age(&uri, fade_s).map(|_| format!("playing {uri} for {age}")) };
                push(&app.status, match r { Ok(m) => format!("Spotify: {m}"), Err(e) => format!("Spotify error: {e}") });
            }
        }
    }
    Drive::Done
}

fn run_now(app: &Engine, action: Action) -> Drive {
    if let Action::AfterMatch { mode, playlist, wl, win, loss, fade_s } = &action {
        app.spotify.lock().unwrap().reload_token();
        let r = after_match(app, mode, playlist, *wl, win, loss, *fade_s);
        push(&app.status, match r { Ok(m) => format!("After match: {m}"), Err(e) => format!("After match failed: {e}") });
        return Drive::Done;
    }
    let r = { let mut sp = app.spotify.lock().unwrap(); sp.reload_token(); match &action {
        Action::AfterMatch { .. } => Ok(String::new()),
        Action::Play { age, uri, fade_s } => sp.play_age(uri, *fade_s).map(|_| format!("playing {uri} for {age}")),
        Action::HandBack | Action::Restore => sp.restore(app.settings.lock().unwrap().fade_seconds),
        Action::Stop => sp.fade_pause(app.settings.lock().unwrap().fade_seconds).map(|_| "stopped (faded out and paused)".to_string()),
    } };
    push(&app.status, match r { Ok(m) => format!("Spotify: {m}"), Err(e) => format!("Spotify error: {e}") });
    Drive::Done
}

fn dispatch(app: &Engine, rx: &std::sync::mpsc::Receiver<Action>, seq: &mut Seq, action: Action, skip_gate: bool) -> Drive {
    // A newer age during an intro only replaces what follows it. The track already playing runs out.
    if seq.in_intro() {
        if let Action::Play { ref age, ref uri, fade_s } = action {
            let _ = seq.age(false, None, make_cue(app, age, uri, fade_s));
            let uri = seq.intro_uri().unwrap_or("").to_string();
            return match wait(app, rx, seq, WaitOn::Intro, Latch::expect(uri), None, None) {
                WaitOut::Steps(steps) => drive(app, rx, seq, steps, None),
                WaitOut::Now(a) => Drive::Follow(a),
                WaitOut::Closed => Drive::Exit,
            };
        }
        seq.clear();
        return run_now(app, action);
    }
    if let Action::Play { ref age, ref uri, fade_s } = action {
        let cue = make_cue(app, age, uri, fade_s);
        // The 60 s read is the only player-state call before the intro. Toggle off skips it.
        let finish = !skip_gate && app.finish.load(Ordering::SeqCst);
        let now = if finish { let v = app.spotify.lock().unwrap().player_state(); heard(&v) } else { None };
        let steps = seq.age(finish, now.as_ref(), cue);
        if steps.iter().any(|s| matches!(s, Step::Wait)) {
            push(&app.status, format!("Finish song first: waiting to play {age}"));
        }
        return drive(app, rx, seq, steps, now);
    }
    if !skip_gate && holdable(&action) && app.finish.load(Ordering::SeqCst) {
        let v = app.spotify.lock().unwrap().player_state();
        if let Some(h) = heard(&v).filter(within_minute) {
            push(&app.status, format!("Finish song first: waiting to {}", label(&action)));
            let latch = Latch::playing(h.uri.clone());
            return match wait(app, rx, seq, WaitOn::Track, latch, Some(h), Some(action)) {
                WaitOut::Steps(steps) => drive(app, rx, seq, steps, None),
                WaitOut::Now(a) => Drive::Follow(a),
                WaitOut::Closed => Drive::Exit,
            };
        }
    }
    run_now(app, action)
}

/// Spotify worker. Ages run one at a time so fades never overlap and the log watcher never blocks.
/// An age with an intro plays it, then the playlist when that intro ends or is skipped.
/// A pause holds the playlist until playback resumes. Finish song first waits out a track
/// with a minute or less left before the intro.
pub fn player(app: Arc<Engine>, rx: std::sync::mpsc::Receiver<Action>) {
    let mut seq = Seq::new();
    let mut follow: Option<Action> = None;
    loop {
        let (action, skip_gate) = match follow.take() {
            Some(a) => (a, true),
            None => match rx.recv() { Ok(a) => (a, false), Err(_) => return },
        };
        match dispatch(&app, &rx, &mut seq, action, skip_gate) {
            Drive::Done => sync_logged(&app),
            Drive::Exit => return,
            Drive::Follow(a) => follow = Some(a),
        }
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
    let crc = crate::sys::test_env("AOE4S_LOGFILES").map(PathBuf::from).unwrap_or_else(|| la.join(r"Documents\My Games\Age of Empires IV\LogFiles"));
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
