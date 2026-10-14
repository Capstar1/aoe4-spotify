//! Log-replay tests: feed recorded / synthetic AoE4 log lines through adapter + switcher, assert the music actions.
use aoe4core::aoe4::{pick_id, playermap, Aoe4};
use aoe4core::game::{GameAdapter, GameEvent};
use aoe4core::logtail::{Poll, Tail};
use aoe4core::switcher::{Action, Switcher};
use std::collections::HashMap;

fn adapter() -> Aoe4 { Aoe4::new(Box::new(|slot, hidx| pick_id(&HashMap::from([(0, 6), (1, 7)]), slot, hidx))) }
fn lists() -> HashMap<String, String> {
    ["dark", "feudal", "castle", "imperial"].iter().map(|k| (k.to_string(), format!("spotify:playlist:{k}"))).collect()
}
fn run(lines: &[&str]) -> (Vec<GameEvent>, Vec<Action>) {
    let mut a = adapter(); let mut s = Switcher::new(true, 2.0, lists());
    let (mut evs, mut acts) = (vec![], vec![]);
    for l in lines { for e in a.feed(l) { acts.extend(s.on_event(&e)); evs.push(e); } }
    (evs, acts)
}
const MATCH: &[&str] = &[
    "GAME -- Current Steam name is [Capstar]",
    "[Match Flow] GameApp::RequestGameBegin()",
    "GAME -- Human Player: 0 Capstar 111 0 english",
    "GAME -- Human Player: 1 Enemy 222 1 french",
    "GAME -- Starting mission",
    "Age up started from dark_age to feudal_age for player id 7",
    "Age up started from dark_age to feudal_age for player id 6",
    "Age up complete from dark_age for player id 6",
    "Age up started from feudal_age to castle_age for player id 6",
    "Report sent for profileID[111] -> race=[1], result=[1]",
    "MOD -- Game Over at frame 12345",
];

#[test]
fn match_switches_ages_and_restores() {
    let (_, acts) = run(MATCH);
    let ages: Vec<_> = acts.iter().filter_map(|a| match a { Action::Play { age, .. } => Some(age.as_str()), _ => None }).collect();
    assert_eq!(ages, ["dark", "feudal", "castle"]);
    assert_eq!(acts.last(), Some(&Action::Restore));
}

#[test]
fn result_after_end_is_captured() {
    let mut l = MATCH.to_vec(); let r = l.remove(9); l.push(r);       // real logs: result line comes AFTER Game Over
    let (evs, _) = run(&l);
    assert!(evs.contains(&GameEvent::MatchEnd { result: None }));
    assert_eq!(evs.last(), Some(&GameEvent::MatchResult { result: 1 }));
}

#[test]
fn result_reported() {
    let (evs, _) = run(MATCH);
    assert!(evs.contains(&GameEvent::MatchEnd { result: Some(1) }));
}

#[test]
fn other_players_ages_ignored() {
    let (_, acts) = run(&MATCH[..6]);   // only the enemy (id 7) aged up
    assert_eq!(acts.len(), 1);          // just the start (dark)
}

#[test]
fn replay_leaves_music_alone() {
    let mut l = MATCH.to_vec(); l.insert(5, "PlaybackSynchronization::Start");
    let (evs, acts) = run(&l);
    assert!(evs.contains(&GameEvent::Replay));
    assert!(!acts.iter().any(|a| matches!(a, Action::Play { age, .. } if age != "dark")));
}

#[test]
fn observer_is_not_a_player() {
    let (_, acts) = run(&["GAME -- Current Steam name is [Capstar]", "[Match Flow] GameApp::RequestGameBegin()",
        "GAME -- Human Player: 0 A 1 0 english", "GAME -- Human Player: 1 B 2 1 french", "GAME -- Starting mission"]);
    assert!(acts.is_empty());
}

#[test]
fn disabled_does_nothing() {
    let mut a = adapter(); let mut s = Switcher::new(false, 2.0, lists());
    let n: usize = MATCH.iter().map(|l| a.feed(l).iter().map(|e| s.on_event(e).len()).sum::<usize>()).sum();
    assert_eq!(n, 0);
}

#[test]
fn playermap_parses_datacrc() {
    let t = "x\n  playermap: \n  {\n    index: [ 0 ]\n    setupindex: [ 0 ]\n    simid: [ 1006 ]\n    index: [ 1 ]\n    setupindex: [ 1 ]\n    simid: [ 1007 ]\n  }\n";
    let m = playermap(t);
    assert_eq!(m.get(&0), Some(&6)); assert_eq!(m.get(&1), Some(&7));
    assert_eq!(pick_id(&m, 3, Some(1)), Some(7));
}

#[test]
fn tail_follows_appends_and_truncation() {
    let p = std::env::temp_dir().join(format!("aoe4tail_{}.log", std::process::id()));
    std::fs::write(&p, "a\nb\npart").unwrap();
    let mut t = Tail::new(p.clone());
    assert!(matches!(t.poll(), Poll::Lines(v) if v == ["a", "b"]));
    use std::io::Write; std::fs::OpenOptions::new().append(true).open(&p).unwrap().write_all(b"ial\r\nc\n").unwrap();
    assert!(matches!(t.poll(), Poll::Lines(v) if v == ["partial", "c"]));
    std::fs::write(&p, "new\n").unwrap();
    assert!(matches!(t.poll(), Poll::Restarted(v) if v == ["new"]));
    let _ = std::fs::remove_file(p);
}

/// Real log smoke test (optional): AOE4_LOG=path to a COPY of warnings.log.
#[test]
fn real_log_replays_without_panic() {
    let Ok(p) = std::env::var("AOE4_LOG") else { return };
    let text = String::from_utf8_lossy(&std::fs::read(p).unwrap()).to_string();
    let mut a = match std::env::var("AOE4_CRC") { Ok(d) => Aoe4::new(Aoe4::datacrc_resolver(d.into())), Err(_) => adapter() };   // newest DataCRC = last match only
    let mut s = Switcher::new(true, 2.0, lists()); let mut n = 0;
    for l in text.lines() { for e in a.feed(l) { n += 1; let acts = s.on_event(&e); println!("  {:?} -> {:?}", e, acts); } }
    println!("real log: {} lines, {} events", text.lines().count(), n);
}