//! Game events -> music actions. Pure (no I/O), so it is tested by replaying logs.
use crate::game::GameEvent;
use std::collections::HashMap;

#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(tag = "do", rename_all = "snake_case")]
pub enum Action {
    Play { age: String, uri: String, fade_s: f32 },
    /// Match over: give the music back (M4: after-match options).
    Restore,
}

pub struct Switcher {
    pub enabled: bool,
    pub fade_s: f32,
    pub playlists: HashMap<String, String>,
    pub current: Option<String>,
    in_match: bool,
}

impl Switcher {
    pub fn new(enabled: bool, fade_s: f32, playlists: HashMap<String, String>) -> Self {
        Switcher { enabled, fade_s, playlists, current: None, in_match: false }
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
            GameEvent::MatchEnd { .. } if self.in_match => { self.in_match = false; self.current = None; if self.enabled { vec![Action::Restore] } else { vec![] } }
            _ => vec![],
        }
    }
}