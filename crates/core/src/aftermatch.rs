//! 1.0.9 install_after_match, independent of the app so it can be tested with a fake clock and fake Spotify:
//! wait (max 6 s) for the result, play the Win / Loss pick to its end, then Resume / Playlist / Stop.
//! The match number is checked before every Spotify step, so a new match always wins.
use serde_json::Value;
use std::time::Duration;

/// What after-match needs from the app: match status, a clock / wait, and the Spotify steps.
pub trait AfterCtx {
    /// Current match number (bumped on every MatchStart).
    fn match_n(&self) -> u64;
    /// Final result of the current match (1 = victory, 0 = defeat).
    fn result(&self) -> Option<i32>;
    /// Sleep up to `d`, waking early when the match status changes.
    fn wait(&self, d: Duration);
    /// Time since an arbitrary fixed start (monotonic).
    fn elapsed(&self) -> Duration;
    fn play(&self, uri: &str, fade_s: f32) -> Result<(), String>;
    fn state(&self) -> Value;
    fn forget_saved(&self);
    fn restore(&self, fade_s: f32) -> Result<String, String>;
    fn fade_pause(&self, fade_s: f32) -> Result<(), String>;
    fn note(&self, line: String);
}

pub const RESULT_WAIT: Duration = Duration::from_secs(6);
pub const POLL: Duration = Duration::from_secs(2);
pub const MAX_SONG: Duration = Duration::from_secs(15 * 60);

pub fn run(cx: &dyn AfterCtx, mode: &str, playlist: &str, wl: bool, win: &str, loss: &str, fade_s: f32) -> Result<String, String> {
    let n = cx.match_n(); let same = || cx.match_n() == n;
    let mut fade = fade_s;
    if wl {
        let t0 = cx.elapsed();
        while cx.result().is_none() && same() {
            let left = RESULT_WAIT.saturating_sub(cx.elapsed() - t0);
            if left.is_zero() { break; }
            cx.wait(left);   // wakes as soon as the result (or a new match) arrives
        }
        if !same() { return Ok("a new match already started".into()); }
        let r = cx.result(); let pick = match r { Some(1) => win, Some(0) => loss, _ => "" };
        cx.note(format!("After match: {}", match r { Some(1) => "victory", Some(0) => "defeat", _ => "no final result" }));
        if !pick.is_empty() {
            cx.note(format!("After match: play {} first", pick.split(',').next().unwrap_or(pick)));
            cx.play(pick, fade)?;
            // until that song / list item ends, you skip, or you pause (then: nothing more)
            let t0 = cx.elapsed(); let mut first: Option<String> = None;
            loop {
                cx.wait(POLL);
                if !same() { return Ok("a new match started".into()); }
                let st = cx.state();
                if !same() { return Ok("a new match started".into()); }
                let item = st["item"]["uri"].as_str().map(String::from); let dur = st["item"]["duration_ms"].as_i64().unwrap_or(0); let pos = st["progress_ms"].as_i64().unwrap_or(0);
                if first.is_none() { first = item.clone(); }
                if st["is_playing"].as_bool() != Some(true) { if pos == 0 { break; } cx.forget_saved(); return Ok("Spotify paused by you - doing nothing".into()); }
                if item != first || (dur > 0 && pos >= dur - 1500) { if dur > 0 && pos >= dur - 1500 { cx.wait(Duration::from_millis(1500)); } break; }
                if cx.elapsed() - t0 > MAX_SONG { break; }
            }
            fade = fade.min(1.0);
        }
    }
    if !same() { return Ok("a new match started".into()); }
    match mode {
        "playlist" if !playlist.is_empty() => { cx.play(playlist, fade)?; cx.forget_saved(); Ok(format!("play {}", playlist.split(',').next().unwrap_or(""))) }
        "resume" => cx.restore(fade),
        _ => cx.fade_pause(fade).map(|_| "stop (fade out and pause)".into()),
    }
}
