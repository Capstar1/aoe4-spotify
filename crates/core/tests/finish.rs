use aoe4core::finish::{release, within_minute, Heard, Latch};
use aoe4core::intros::intro_track;
use aoe4core::settings;

fn heard(uri: &str, pos: i64, dur: i64, playing: bool) -> Heard {
    Heard { uri: uri.into(), pos_ms: pos, dur_ms: dur, playing }
}

#[test]
fn release_on_pause_skip_and_end() {
    let mut lat = Latch::playing("spotify:track:a");
    let now = heard("spotify:track:a", 1000, 10000, true);
    assert!(!release(&mut lat, Some(&now)));
    let paused = heard("spotify:track:a", 1000, 10000, false);
    assert!(release(&mut lat, Some(&paused)));
    let mut lat = Latch::playing("spotify:track:a");
    let skip = heard("spotify:track:b", 0, 10000, true);
    assert!(release(&mut lat, Some(&skip)));
    let mut lat = Latch::playing("spotify:track:a");
    let end = heard("spotify:track:a", 9000, 10000, true);
    assert!(release(&mut lat, Some(&end)));
    let mut lat = Latch::playing("spotify:track:a");
    assert!(release(&mut lat, None));
}

#[test]
fn a_minute_or_less_waits() {
    assert!(within_minute(&heard("spotify:track:a", 120_000, 180_000, true)));
    assert!(within_minute(&heard("spotify:track:a", 170_000, 180_000, true)));
    assert!(within_minute(&heard("spotify:track:a", 180_000, 180_000, true)));
    assert!(!within_minute(&heard("spotify:track:a", 119_999, 180_000, true)));
    assert!(!within_minute(&heard("spotify:track:a", 170_000, 180_000, false)));
    assert!(!within_minute(&heard("spotify:track:a", 0, 0, true)));
}

#[test]
fn an_intro_that_has_not_started_is_not_a_skip() {
    let mut lat = Latch::expect("spotify:track:intro");
    let stale = heard("spotify:track:old", 5000, 10000, true);
    assert!(!release(&mut lat, Some(&stale)));
    assert!(!release(&mut lat, None));
    let live = heard("spotify:track:intro", 1000, 20000, true);
    assert!(!release(&mut lat, Some(&live)));
    assert!(lat.seen);
    let gone = heard("spotify:track:old", 0, 10000, true);
    assert!(release(&mut lat, Some(&gone)));
}

#[test]
fn intro_track_follows_the_pool() {
    let d = std::env::temp_dir().join(format!("aoe4s_intro_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&d); std::fs::create_dir_all(&d).unwrap();
    std::fs::write(d.join("base.json"), r#"{"boss_intro":{"enabled":true,"pools":{"english":["spotify:track:aaa","spotify:track:bbb"]},"default":["spotify:track:zzz"]},"default_playlists":{}}"#).unwrap();
    std::fs::write(d.join("user.json"), r#"{"boss_intro_enabled":true,"intro_ages":{"imperial":true,"feudal":true},"intro_pools":{"feudal":{"english":["spotify:track:fff"]}}}"#).unwrap();
    std::fs::write(d.join("names.json"), "{}").unwrap();
    let s = settings::load(&d.join("base.json"), &d.join("user.json"), &d.join("names.json"));
    assert_eq!(intro_track(&s, "feudal", "english", None, 0).as_deref(), Some("spotify:track:fff"));
    assert_eq!(intro_track(&s, "imperial", "english", Some("spotify:track:aaa"), 0).as_deref(), Some("spotify:track:bbb"));
    assert_eq!(intro_track(&s, "imperial", "english", Some("spotify:track:zzz"), 0).as_deref(), Some("spotify:track:aaa"));
    assert!(intro_track(&s, "dark", "english", None, 0).is_none());
    assert!(intro_track(&s, "imperial", "", None, 0).is_none());
    let _ = std::fs::remove_dir_all(&d);
}
