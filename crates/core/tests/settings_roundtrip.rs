//! Settings: install base + user config, changed and read back (the panel's set_user path).
use aoe4core::settings::{client_id_ok, load_own};
use serde_json::{json, Value};

#[test]
fn roundtrip() {
    let d = std::env::temp_dir().join(format!("aoe4s-set-{}", std::process::id())); let _ = std::fs::remove_dir_all(&d); std::fs::create_dir_all(&d).unwrap();
    std::fs::write(d.join("base.json"), json!({ "client_id": "0123456789abcdef0123456789abcdef", "default_playlists": { "dark": "spotify:playlist:d", "feudal": "spotify:playlist:f" }, "fade_seconds": 2.0 }).to_string()).unwrap();
    std::fs::write(d.join("playlist_names.json"), json!({ "spotify:playlist:u": "Mine" }).to_string()).unwrap();
    let s = load_own(&d);
    assert!(s.enabled && s.fade_seconds == 2.0 && !s.own_app && !s.music_in_replays);
    assert_eq!(s.client_id, "0123456789abcdef0123456789abcdef"); assert_eq!(s.playlists["dark"], "spotify:playlist:d");
    // user edits (as set_user writes them), incl. Your Spotify app
    let mut u: Value = json!({});
    u["enabled"] = json!(false); u["fade_seconds"] = json!(3.5); u["playlists"] = json!({ "feudal": "spotify:playlist:u" });
    u["after_match"] = json!({ "mode": "playlist", "playlist": "spotify:playlist:a", "winloss_on": true });
    u["own_app"] = json!(true); u["client_id"] = json!(" FEDCBA9876543210FEDCBA9876543210 "); u["real_playback"] = json!(false);
    std::fs::write(d.join("config.json"), serde_json::to_string_pretty(&u).unwrap()).unwrap();
    let s = load_own(&d);
    assert!(!s.enabled); assert_eq!(s.fade_seconds, 3.5);
    assert_eq!(s.playlists["feudal"], "spotify:playlist:u"); assert_eq!(s.playlists["dark"], "spotify:playlist:d");
    assert_eq!(s.playlist_names["spotify:playlist:u"], "Mine");
    assert_eq!(s.after_match["mode"], "playlist"); assert_eq!(s.after_match["winloss_on"], true);
    assert!(s.own_app); assert_eq!(s.client_id, "fedcba9876543210fedcba9876543210"); assert_eq!(s.shared_client_id, "0123456789abcdef0123456789abcdef");
    let j = serde_json::to_value(&s).unwrap(); assert!(j.get("real_playback").is_none() && j.get("client_id").is_none());
    // own app off -> back to the shared one; bad id never used
    u["own_app"] = json!(false); std::fs::write(d.join("config.json"), u.to_string()).unwrap();
    assert_eq!(load_own(&d).client_id, "0123456789abcdef0123456789abcdef");
    u["own_app"] = json!(true); u["client_id"] = json!("secret-looking-but-not-hex-xxxxxx"); std::fs::write(d.join("config.json"), u.to_string()).unwrap();
    assert!(!load_own(&d).own_app); assert!(!client_id_ok("xyz"));
    let _ = std::fs::remove_dir_all(&d);
}
