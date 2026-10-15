//! "Finish song first": when a queued music change waits.
//! A minute or less left on the track that is already playing, and the change waits for that
//! track. A pause, a skip, or the end releases it. A uri we have not heard yet (an intro that
//! just started) does not.

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Heard {
    pub uri: String,
    pub pos_ms: i64,
    pub dur_ms: i64,
    pub playing: bool,
}

/// The track a queued change is waiting on.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Latch {
    pub uri: String,
    /// False until Spotify reports this uri. Used right after an intro starts, while the player
    /// may still be showing the previous track.
    pub seen: bool,
    /// Intro only: a pause at a position past 0 is in effect. A later stop at position 0
    /// then holds for resume. Cleared when this intro is reported playing. The finish-song gate does not read this.
    pub user_paused: bool,
}

impl Latch {
    pub fn playing(uri: impl Into<String>) -> Self { Self { uri: uri.into(), seen: true, user_paused: false } }
    pub fn expect(uri: impl Into<String>) -> Self { Self { uri: uri.into(), seen: false, user_paused: false } }
}

/// The track already playing has 60 seconds or less left.
pub fn within_minute(now: &Heard) -> bool {
    now.playing && now.dur_ms > 0 && now.dur_ms - now.pos_ms <= 60_000
}

/// True when the queued change should run now.
pub fn release(latch: &mut Latch, now: Option<&Heard>) -> bool {
    let Some(now) = now else { return latch.seen };
    if now.uri != latch.uri { return latch.seen; }
    latch.seen = true;
    if !now.playing { return true; }
    now.dur_ms > 0 && now.pos_ms + 1500 >= now.dur_ms
}
