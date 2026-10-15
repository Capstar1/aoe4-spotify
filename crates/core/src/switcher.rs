//! Game events -> music actions. Pure (no I/O), so it is tested by replaying logs.
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

pub struct Switcher {
    pub enabled: bool,
    pub fade_s: f32,
    pub playlists: HashMap<String, String>,
    pub current: Option<String>,
    pub after: AfterMatch,
    in_match: bool,
}

impl Switcher {
    pub fn new(enabled: bool, fade_s: f32, playlists: HashMap<String, String>) -> Self {
        Switcher { enabled, fade_s, playlists, current: None, after: AfterMatch::default(), in_match: false }
    }

    pub fn on_event(&mut self, ev: &GameEvent) -> Vec<Action> {
        match ev {
            GameEvent::MatchStart { .. } => { self.in_match = true; self.current = None; vec![] }
            GameEvent::Replay => { self.in_match = false; vec![] }
            GameEvent::Age { key, .. } if self.in_match && self.enabled => {
                if self.current.as_deref() == Some(key.as_str()) { return vec![]; }
                self.current = Some(key.clone());
                match self.playlists.get(key) {
                    Some(uri) if !uri.is_empty() => vec![Action::Play { age: key.clone(), uri: uri.clone(), fade_s: self.fade_s }],
                    _ => vec![],
                }
            }
            GameEvent::MatchEnd { .. } if self.in_match => {
                self.in_match = false; self.current = None;
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