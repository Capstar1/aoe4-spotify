//! Age intros. Every age change with an intro plays that track, then the age playlist when the
//! intro ends, pauses, or is skipped. Finish song first, when it is on, waits out a track that
//! has a minute or less left before that intro. A newer age during the intro keeps the track
//! that is already playing and follows it with the newest age.

use crate::finish::{within_minute, Heard};

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
