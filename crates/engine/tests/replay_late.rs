//! A replay marker that arrives after the opening play already started must hand Spotify back.
use aoe4core::switcher::Action;
use aoe4engine::run::{watch, WatchOpts};
use aoe4engine::Engine;
use std::io::Write;
use std::sync::atomic::Ordering;
use std::time::Duration;

#[test]
fn late_replay_marker_restores() {
    let root = std::env::temp_dir().join(format!("aoe4s_late_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    let dir = root.join("AoE4Spotify-1.1");
    std::fs::create_dir_all(&dir).unwrap();
    std::env::set_var("APPDATA", &root);
    std::fs::write(dir.join("base.json"), r#"{"enabled":true,"music_in_replays":false,"playlists":{"dark":"spotify:playlist:dark"}}"#).unwrap();
    let log = dir.join("warnings.log");
    std::fs::write(&log, b"").unwrap();
    let (eng, rx, _) = Engine::new(dir.clone());
    let app = eng.clone();
    let path = log.clone();
    let worker = std::thread::spawn(move || watch(app, path, WatchOpts { skip_older_than: None }));
    let deadline = std::time::Instant::now() + Duration::from_secs(2);
    while !eng.status.lock().unwrap().watching && std::time::Instant::now() < deadline { std::thread::sleep(Duration::from_millis(20)); }
    let mut f = std::fs::OpenOptions::new().append(true).open(&log).unwrap();
    for l in [
        "GAME -- Current Steam name is [Capstar]",
        "[Match Flow] GameApp::RequestGameBegin()",
        "GAME -- Human Player: 0 Capstar 111 0 english",
        "GAME -- Human Player: 1 Enemy 222 1 french",
        "GAME -- Starting mission",
    ] { writeln!(f, "{l}").unwrap(); }
    f.flush().unwrap();
    let play = rx.recv_timeout(Duration::from_secs(6)).expect("opening play");
    assert!(matches!(play, Action::Play { ref age, .. } if age == "dark"), "{play:?}");
    writeln!(f, "PlaybackSynchronization::Start").unwrap();
    f.flush().unwrap();
    let back = rx.recv_timeout(Duration::from_secs(3)).expect("late replay restore");
    assert!(matches!(back, Action::Restore), "{back:?}");
    eng.stop.store(true, Ordering::Relaxed);
    let _ = worker.join();
    let _ = std::fs::remove_dir_all(&root);
}
