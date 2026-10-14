use std::path::PathBuf;

/// What a game adapter reports. Age keys are adapter-defined ("dark", "feudal", ...).
#[derive(Debug, Clone, PartialEq, serde::Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum GameEvent {
    Lobby { slot: i32, civ: String },
    MatchStart { civ: Option<String> },
    Age { key: String, reason: String },
    Replay,
    MatchEnd { result: Option<i32> },
    /// The game reports win/loss a moment AFTER the end line: 1 victory, 0 defeat.
    MatchResult { result: i32 },
}

/// One supported game. Core only talks to this trait.
pub trait GameAdapter: Send {
    fn id(&self) -> &'static str;
    fn label(&self) -> &'static str;
    fn process_names(&self) -> &'static [&'static str];
    fn default_log_path(&self) -> Option<PathBuf>;
    /// (key, label) in play order; the first is the start age.
    fn ages(&self) -> &'static [(&'static str, &'static str)];
    fn feed(&mut self, line: &str) -> Vec<GameEvent>;
    /// The log was recreated (new game session).
    fn reset_session(&mut self);
}