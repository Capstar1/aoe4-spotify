//! After match with a fake clock: no real sleeping, every Spotify step recorded.
use aoe4core::aftermatch::{run, AfterCtx};
use serde_json::{json, Value};
use std::cell::{Cell, RefCell};
use std::time::Duration;

#[derive(Default)]
struct Fake { t: Cell<Duration>, n: Cell<u64>, res: Option<i32>, res_at: Duration, new_match_at: Option<Duration>, states: RefCell<Vec<Value>>, calls: RefCell<Vec<String>> }
impl Fake {
    fn rec(&self, s: String) { self.calls.borrow_mut().push(s); }
    fn calls(&self) -> Vec<String> { self.calls.borrow().clone() }
}
impl AfterCtx for Fake {
    fn match_n(&self) -> u64 { if self.new_match_at.map_or(false, |t| self.t.get() >= t) { 2 } else { self.n.get() } }
    fn result(&self) -> Option<i32> { if self.t.get() >= self.res_at { self.res } else { None } }
    fn wait(&self, d: Duration) {   // like the condvar: wakes early when the result or a new match arrives
        let now = self.t.get(); let mut end = now + d;
        for e in [Some(self.res_at), self.new_match_at].into_iter().flatten() { if e > now && e < end { end = e; } }
        self.t.set(end);
    }
    fn elapsed(&self) -> Duration { self.t.get() }
    fn play(&self, uri: &str, f: f32) -> Result<(), String> { self.rec(format!("play {uri} {f}")); Ok(()) }
    fn state(&self) -> Value { let mut s = self.states.borrow_mut(); if s.len() > 1 { s.remove(0) } else { s.first().cloned().unwrap_or(Value::Null) } }
    fn forget_saved(&self) { self.rec("forget".into()); }
    fn restore(&self, f: f32) -> Result<String, String> { self.rec(format!("restore {f}")); Ok("restored".into()) }
    fn fade_pause(&self, f: f32) -> Result<(), String> { self.rec(format!("stop {f}")); Ok(()) }
    fn note(&self, _: String) {}
}
fn st(uri: &str, pos: i64, dur: i64, playing: bool) -> Value { json!({ "is_playing": playing, "progress_ms": pos, "item": { "uri": uri, "duration_ms": dur } }) }

#[test]
fn win_song_to_end_then_resume() {
    let f = Fake { n: Cell::new(1), res: Some(1), res_at: Duration::from_millis(800), states: RefCell::new(vec![st("w", 1000, 60000, true), st("w", 59000, 60000, true)]), ..Default::default() };
    assert_eq!(run(&f, "resume", "", true, "w", "l", 3.0).unwrap(), "restored");
    assert_eq!(f.calls(), vec!["play w 3", "restore 1"]);
    // 0.8 s result wait + two 2 s polls + 1.5 s tail
    assert_eq!(f.t.get(), Duration::from_millis(800 + 4000 + 1500));
}

#[test]
fn no_result_after_6s_goes_straight_to_playlist() {
    let f = Fake { n: Cell::new(1), res: None, ..Default::default() };
    assert_eq!(run(&f, "playlist", "spotify:playlist:p", true, "w", "l", 2.0).unwrap(), "play spotify:playlist:p");
    assert_eq!(f.calls(), vec!["play spotify:playlist:p 2", "forget"]);
    assert_eq!(f.t.get(), Duration::from_secs(6));
}

#[test]
fn paused_by_you_does_nothing_more() {
    let f = Fake { n: Cell::new(1), res: Some(0), states: RefCell::new(vec![st("l", 3000, 60000, false)]), ..Default::default() };
    assert_eq!(run(&f, "stop", "", true, "w", "l", 2.0).unwrap(), "Spotify paused by you - doing nothing");
    assert_eq!(f.calls(), vec!["play l 2", "forget"]);
}

#[test]
fn new_match_stops_after_match() {
    let f = Fake { n: Cell::new(1), res: Some(1), new_match_at: Some(Duration::from_secs(3)), states: RefCell::new(vec![st("w", 1000, 600000, true)]), ..Default::default() };
    assert_eq!(run(&f, "resume", "", true, "w", "l", 2.0).unwrap(), "a new match started");
    assert_eq!(f.calls(), vec!["play w 2"]);
}

#[test]
fn caps_win_song_at_15_minutes() {
    let f = Fake { n: Cell::new(1), res: Some(1), states: RefCell::new(vec![st("w", 1000, 3_600_000, true)]), ..Default::default() };
    run(&f, "stop", "", true, "w", "l", 2.0).unwrap();
    assert_eq!(f.calls(), vec!["play w 2", "stop 1"]);
    assert!(f.t.get() > Duration::from_secs(15 * 60) && f.t.get() <= Duration::from_secs(15 * 60 + 2));
}

#[test]
fn without_winloss_just_stops() {
    let f = Fake { n: Cell::new(1), ..Default::default() };
    run(&f, "stop", "", false, "w", "l", 2.5).unwrap();
    assert_eq!(f.calls(), vec!["stop 2.5"]); assert_eq!(f.t.get(), Duration::ZERO);
}
