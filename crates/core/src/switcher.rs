//! Game events -> music actions. Pure (no I/O), so it is tested by replaying logs.
//!
//! The first play waits `start_delay` seconds (the engine uses 3, matching 1.0.9) so a replay
//! marker that trails "Starting mission" can cancel it. With Music in replays on, later ages
//! wait `replay_settle` seconds and only move forward. Tests leave `start_delay` at 0.
use crate::game::GameEvent;
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(tag = "do", rename_all = "snake_case")]
pub enum Action {
    Play { age: String, uri: String, fade_s: f32 },
    /// Match over: give the music back (After match: Resume, the default).
    Restore,
    /// Fade out and pause (After match: Stop).
    Stop,
    /// After match with Win / Loss on or Playlist: the worker waits for the result (~6 s, like 1.0.9), plays the
    /// victory / defeat pick to its end, then does `mode` (resume | playlist | stop).
    AfterMatch { mode: String, playlist: String, wl: bool, win: String, loss: String, fade_s: f32 },
}

/// 1.0.9 after_match_cfg.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct AfterMatch { pub mode: String, pub wl: bool, pub playlist: String, pub win: String, pub loss: String }

struct Pending { age: String, at: f64 }

pub struct Switcher {
    pub enabled: bool,
    pub fade_s: f32,
    pub playlists: HashMap<String, String>,
    pub current: Option<String>,
    pub after: AfterMatch,
    /// Seconds to hold the opening play. 0 plays on the start line (unit tests). The engine sets 3.
    pub start_delay: f32,
    /// Seconds an age must hold in a watched replay before the playlist follows. 1.0.9 uses 5.
    pub replay_settle: f32,
    /// Cog menu "Music in replays", read live by the engine before each event.
    pub music_in_replays: bool,
    now: f64,
    in_match: bool,
    watching: bool,
    pending_start: Option<Pending>,
    rp_pending: Option<Pending>,
    rp_age: String,
}

fn age_ord(k: &str) -> i32 {
    match k { "dark" => 0, "feudal" => 1, "castle" => 2, "imperial" => 3, _ => -1 }
}

impl Switcher {
    pub fn new(enabled: bool, fade_s: f32, playlists: HashMap<String, String>) -> Self {
        Switcher {
            enabled, fade_s, playlists, current: None, after: AfterMatch::default(),
            start_delay: 0.0, replay_settle: 5.0, music_in_replays: false,
            now: 0.0, in_match: false, watching: false,
            pending_start: None, rp_pending: None, rp_age: "dark".into(),
        }
    }

    /// Test and engine clock, in seconds. Delayed plays release from `poll`.
    pub fn set_now(&mut self, t: f64) { self.now = t; }

    /// Release a held opening play or a replay age whose settle time has passed.
    pub fn poll(&mut self) -> Vec<Action> {
        let mut out = vec![];
        if let Some(p) = self.pending_start.take() {
            if self.now >= p.at && self.in_match && self.enabled { out.extend(self.play_key(&p.age)); }
            else if self.now < p.at { self.pending_start = Some(p); }
        }
        if let Some(p) = self.rp_pending.take() {
            if self.now >= p.at && self.in_match && self.watching && self.enabled && age_ord(&p.age) > age_ord(&self.rp_age) {
                self.rp_age = p.age.clone();
                out.extend(self.play_key(&p.age));
            } else if self.now < p.at && self.in_match && self.watching { self.rp_pending = Some(p); }
        }
        out
    }

    fn play_key(&mut self, key: &str) -> Vec<Action> {
        if self.current.as_deref() == Some(key) { return vec![]; }
        self.current = Some(key.to_string());
        match self.playlists.get(key) {
            Some(uri) if !uri.is_empty() => vec![Action::Play { age: key.to_string(), uri: uri.clone(), fade_s: self.fade_s }],
            _ => vec![],
        }
    }

    fn clear_replay_hold(&mut self) {
        self.watching = false;
        self.pending_start = None;
        self.rp_pending = None;
    }

    pub fn on_event(&mut self, ev: &GameEvent) -> Vec<Action> {
        match ev {
            GameEvent::MatchStart { .. } => {
                self.in_match = true; self.current = None; self.clear_replay_hold(); self.rp_age = "dark".into();
                vec![]
            }
            GameEvent::Replay => {
                if self.music_in_replays {
                    self.watching = true;
                    if let Some(c) = &self.current { self.rp_age = c.clone(); }
                    vec![]
                } else {
                    // The opening play is still held, so nothing has started. Do not send Stop.
                    self.in_match = false; self.current = None; self.clear_replay_hold();
                    vec![]
                }
            }
            GameEvent::Age { key, reason } if self.in_match && self.enabled && reason == "start" && self.start_delay > 0.0 => {
                self.pending_start = Some(Pending { age: key.clone(), at: self.now + f64::from(self.start_delay) });
                vec![]
            }
            GameEvent::Age { key, .. } if self.watching && self.in_match && self.enabled => {
                if age_ord(key) <= age_ord(&self.rp_age) { return vec![]; }
                let settle = if self.replay_settle < 0.0 { 0.0 } else { f64::from(self.replay_settle) };
                self.rp_pending = Some(Pending { age: key.clone(), at: self.now + settle });
                if settle <= 0.0 { return self.poll(); }
                vec![]
            }
            GameEvent::Age { key, .. } if self.in_match && self.enabled => self.play_key(key),
            GameEvent::MatchEnd { .. } if self.in_match => {
                self.in_match = false; self.current = None; self.clear_replay_hold();
                if !self.enabled { return vec![]; }
                let a = &self.after;
                if !a.wl && (a.mode == "resume" || a.mode.is_empty()) { return vec![Action::Restore]; }
                if !a.wl && a.mode == "stop" { return vec![Action::Stop]; }
                vec![Action::AfterMatch { mode: if a.mode.is_empty() { "resume".into() } else { a.mode.clone() }, playlist: a.playlist.clone(), wl: a.wl, win: a.win.clone(), loss: a.loss.clone(), fade_s: self.fade_s }]
            }
            _ => vec![],
        }
    }
}
