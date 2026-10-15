use aoe4core::boss::{Cue, Seq, Step};
use aoe4core::finish::Heard;

fn cue(age: &str, playlist: &str, intro: Option<&str>) -> Cue {
    Cue { age: age.into(), playlist: playlist.into(), intro: intro.map(str::to_string), fade_s: 0.0 }
}

fn intro(age: &str, track: &str) -> Step {
    Step::Intro { age: age.into(), track: track.into(), fade_s: 0.0 }
}

fn playlist(age: &str, uri: &str) -> Step {
    Step::Playlist { age: age.into(), uri: uri.into(), fade_s: 0.0 }
}

fn heard(pos: i64, dur: i64, playing: bool) -> Heard {
    Heard { uri: "spotify:track:old".into(), pos_ms: pos, dur_ms: dur, playing }
}

#[test]
fn age_up_plays_the_intro_then_the_playlist() {
    let mut s = Seq::new();
    assert_eq!(s.age(false, None, cue("dark", "spotify:playlist:d", Some("spotify:track:aaa"))), vec![intro("dark", "spotify:track:aaa")]);
    assert!(s.in_intro());
    assert_eq!(s.released(), vec![playlist("dark", "spotify:playlist:d")]);
    assert!(!s.in_intro());

    let mut s = Seq::new();
    assert_eq!(s.age(false, None, cue("dark", "spotify:playlist:d", None)), vec![playlist("dark", "spotify:playlist:d")]);
    assert!(s.released().is_empty());
}

#[test]
fn toggle_off_and_on() {
    let feudal = || cue("feudal", "spotify:playlist:f", Some("spotify:track:fff"));
    let mut s = Seq::new();
    assert_eq!(s.age(false, None, feudal()), vec![intro("feudal", "spotify:track:fff")]);

    let mut s = Seq::new();
    let long = heard(90_000, 180_000, true);
    assert_eq!(s.age(true, Some(&long), feudal()), vec![intro("feudal", "spotify:track:fff")]);

    let mut s = Seq::new();
    let short = heard(150_000, 180_000, true);
    assert_eq!(s.age(true, Some(&short), feudal()), vec![Step::Wait]);
    assert_eq!(s.released(), vec![intro("feudal", "spotify:track:fff")]);
    assert_eq!(s.released(), vec![playlist("feudal", "spotify:playlist:f")]);

    let mut s = Seq::new();
    let edge = heard(120_000, 180_000, true);
    assert_eq!(s.age(true, Some(&edge), cue("castle", "spotify:playlist:c", Some("spotify:track:ccc"))), vec![Step::Wait]);
    let over = heard(119_999, 180_000, true);
    let mut s = Seq::new();
    assert_eq!(s.age(true, Some(&over), cue("castle", "spotify:playlist:c", Some("spotify:track:ccc"))), vec![intro("castle", "spotify:track:ccc")]);

    let mut s = Seq::new();
    let paused = heard(170_000, 180_000, false);
    assert_eq!(s.age(true, Some(&paused), cue("castle", "spotify:playlist:c", Some("spotify:track:ccc"))), vec![intro("castle", "spotify:track:ccc")]);

    let mut s = Seq::new();
    assert_eq!(s.age(true, Some(&short), cue("imperial", "spotify:playlist:i", Some("spotify:track:iii"))), vec![Step::Wait]);
    assert_eq!(s.finish_off(), vec![intro("imperial", "spotify:track:iii")]);

    let mut s = Seq::new();
    assert_eq!(s.age(true, Some(&short), cue("dark", "spotify:playlist:d", Some("spotify:track:dark"))), vec![Step::Wait]);
    assert!(s.age(true, Some(&short), cue("feudal", "spotify:playlist:f", Some("spotify:track:fff"))).is_empty());
    assert_eq!(s.released(), vec![intro("feudal", "spotify:track:fff")]);
    assert_eq!(s.released(), vec![playlist("feudal", "spotify:playlist:f")]);

    let mut s = Seq::new();
    assert_eq!(s.age(true, Some(&short), cue("dark", "spotify:playlist:d", Some("spotify:track:dark"))), vec![Step::Wait]);
    s.clear();
    s.hold(feudal());
    assert_eq!(s.released(), vec![intro("feudal", "spotify:track:fff")]);
}

#[test]
fn newer_age_during_the_intro() {
    let mut s = Seq::new();
    assert_eq!(s.age(false, None, cue("dark", "spotify:playlist:d", Some("spotify:track:dark"))), vec![intro("dark", "spotify:track:dark")]);
    assert!(s.age(false, None, cue("feudal", "spotify:playlist:f", Some("spotify:track:feu"))).is_empty());
    let short = heard(170_000, 180_000, true);
    assert!(s.age(true, Some(&short), cue("castle", "spotify:playlist:c", Some("spotify:track:cas"))).is_empty());
    assert_eq!(s.intro_uri(), Some("spotify:track:dark"));
    assert!(s.finish_off().is_empty());
    assert_eq!(s.intro_uri(), Some("spotify:track:dark"));
    assert_eq!(s.released(), vec![intro("castle", "spotify:track:cas")]);
    assert_eq!(s.released(), vec![playlist("castle", "spotify:playlist:c")]);

    let mut s = Seq::new();
    s.age(false, None, cue("dark", "spotify:playlist:d", Some("spotify:track:dark")));
    assert!(s.age(false, None, cue("feudal", "spotify:playlist:f", None)).is_empty());
    assert_eq!(s.released(), vec![playlist("feudal", "spotify:playlist:f")]);
}
