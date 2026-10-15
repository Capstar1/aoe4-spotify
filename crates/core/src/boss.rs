//! Age intros. Every age change with an intro plays that track, then the age playlist when the
//! intro ends or is skipped. A pause does not release: the intro clock stops, and if the intro
//! reaches the handoff while paused the playlist waits until playback resumes. Finish song first,
//! when it is on, waits out a track that has a minute or less left before that intro. A newer age
//! during the intro keeps the track that is already playing and follows it with the newest age.

use crate::finish::{within_minute, Heard, Latch};
use std::time::Duration;

/// Hand the age playlist over this long before the intro track ends (1.0.9 `INTRO_LEAD` is 1.2 s).
pub const INTRO_LEAD_MS: i64 = 1_000;

#[derive(Clone, Debug, PartialEq)]
pub struct Cue {
    pub age: String,
    pub playlist: String,
    pub intro: Option<String>,
    pub fade_s: f32,
}

#[derive(Clone, Debug, PartialEq)]
pub enum Step {
    /// The current track has a minute or less left. The intro has not started.
    Wait,
    Intro { age: String, track: String, fade_s: f32 },
    Playlist { age: String, uri: String, fade_s: f32 },
}

enum Live {
    Idle,
    /// Finish song first: the age is queued, the current track is still playing.
    Holding(Cue),
    /// `uri` is the intro that is playing. `next` is the age that follows it.
    Intro { uri: String, next: Cue },
}

pub struct Seq {
    live: Live,
}

impl Seq {
    pub fn new() -> Self { Self { live: Live::Idle } }

    /// An age change. A playing intro is not cut: `cue` becomes what follows it, and this
    /// returns nothing. A cue already inside the 60 s gate is replaced the same way, with no
    /// second wait. `now` is only read while idle, and only when `finish` is on.
    pub fn age(&mut self, finish: bool, now: Option<&Heard>, cue: Cue) -> Vec<Step> {
        if let Live::Intro { ref mut next, .. } = self.live {
            *next = cue;
            return Vec::new();
        }
        if matches!(self.live, Live::Holding(_)) {
            self.live = Live::Holding(cue);
            return Vec::new();
        }
        if finish && now.is_some_and(within_minute) {
            self.live = Live::Holding(cue);
            return vec![Step::Wait];
        }
        start(self, cue)
    }

    /// The latched track ended, paused, or was skipped.
    pub fn released(&mut self) -> Vec<Step> {
        let cue = match std::mem::replace(&mut self.live, Live::Idle) {
            Live::Holding(cue) => cue,
            Live::Intro { next, .. } => next,
            Live::Idle => return Vec::new(),
        };
        start(self, cue)
    }

    /// Finish song first turned off during the 60 s gate. The queued age starts at once.
    /// An intro that already started is left alone.
    pub fn finish_off(&mut self) -> Vec<Step> {
        match std::mem::replace(&mut self.live, Live::Idle) {
            Live::Holding(cue) => start(self, cue),
            other => {
                self.live = other;
                Vec::new()
            }
        }
    }

    /// Drop the intro and anything queued behind it. The caller plays something else now.
    pub fn clear(&mut self) { self.live = Live::Idle; }

    /// Queue `cue` and stay in the 60 s gate. A play that arrives during that gate uses this,
    /// including after a non-play cleared the previous cue. A playing intro is not dropped.
    pub fn hold(&mut self, cue: Cue) {
        if let Live::Intro { ref mut next, .. } = self.live {
            *next = cue;
            return;
        }
        self.live = Live::Holding(cue);
    }

    pub fn in_intro(&self) -> bool { self.intro_uri().is_some() }

    pub fn intro_uri(&self) -> Option<&str> {
        match &self.live {
            Live::Intro { uri, .. } => Some(uri.as_str()),
            _ => None,
        }
    }
}

fn start(seq: &mut Seq, mut cue: Cue) -> Vec<Step> {
    if let Some(track) = cue.intro.take() {
        let step = Step::Intro { age: cue.age.clone(), track: track.clone(), fade_s: cue.fade_s };
        seq.live = Live::Intro { uri: track, next: cue };
        return vec![step];
    }
    let step = Step::Playlist { age: cue.age.clone(), uri: cue.playlist.clone(), fade_s: cue.fade_s };
    seq.live = Live::Idle;
    vec![step]
}

/// What one look at the player means while an intro is the latched track.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum IntroPoll {
    /// Keep waiting. `paused` freezes the intro clock (poll again shortly; do not treat the nap as elapsed).
    Stay { paused: bool },
    /// The intro finished, Spotify stopped it at position 0 after a missed handoff, or the listener skipped it.
    Release,
    /// The listener paused with time left, or inside the handoff. The playlist waits until playback resumes.
    Hold,
}

/// Pause does not release. A skip does, once this intro has been seen. The handoff is `INTRO_LEAD_MS`
/// before the track's duration. Once the intro has been seen, a stop at position 0 (repeat off, the
/// track ended) or inside that handoff releases, unless a pause at a position past 0 was already
/// seen for this intro: that one holds until playback resumes (1.0.9 `progress_ms == 0` break).
pub fn intro_poll(latch: &mut Latch, now: Option<&Heard>) -> IntroPoll {
    let Some(now) = now else { return IntroPoll::Stay { paused: false }; };
    if now.uri != latch.uri {
        return if latch.seen { IntroPoll::Release } else { IntroPoll::Stay { paused: false } };
    }
    latch.seen = true;
    let ending = now.dur_ms > 0 && now.pos_ms >= now.dur_ms - INTRO_LEAD_MS;
    if !now.playing {
        // Position 0 is Spotify after a track ends with repeat off. The handoff window is the
        // same end. Either one releases, unless this intro was already paused past 0.
        if (now.pos_ms == 0 || ending) && !latch.user_paused { return IntroPoll::Release; }
        if now.pos_ms > 0 { latch.user_paused = true; }
        if now.pos_ms == 0 || ending { return IntroPoll::Hold; }
        return IntroPoll::Stay { paused: true };
    }
    if ending { IntroPoll::Release } else { IntroPoll::Stay { paused: false } }
}

/// How long to sleep before the next intro poll. While it is playing, sleep until the handoff,
/// clamped to 100 ms .. 2 s. While it is paused or the player is unknown, look again in 500 ms.
pub fn intro_nap(now: Option<&Heard>) -> Duration {
    let ms = match now {
        Some(h) if h.playing && h.dur_ms > h.pos_ms => (h.dur_ms - h.pos_ms - INTRO_LEAD_MS).clamp(100, 2_000) as u64,
        _ => 500,
    };
    Duration::from_millis(ms)
}
