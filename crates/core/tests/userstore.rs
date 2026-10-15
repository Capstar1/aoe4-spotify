use aoe4core::userstore::*;
use serde_json::json;
#[test]
fn set_and_remove_keys() {
    let d = std::env::temp_dir().join(format!("aoe4s_us_{}", std::process::id())); let _ = std::fs::remove_dir_all(&d);
    assert!(set_user(&d, "fade_seconds", json!(3.5)));
    assert!(!set_user(&d, "client_id", json!("x")));
    assert_eq!(read_user(&d)["fade_seconds"], json!(3.5));
    assert!(set_user(&d, "fade_seconds", json!(null)));
    assert!(read_user(&d).get("fade_seconds").is_none() && read_user(&d).get("client_id").is_none());
    assert!(!replays(&d, false)); assert!(set_replays(&d, true)); assert!(replays(&d, false));
    let mut extra = read_json(&d.join("settings.json")); extra["kept"] = json!(1); assert!(write_atomic(&d.join("settings.json"), &extra).is_ok());
    assert!(set_replays(&d, false)); assert!(!replays(&d, true)); assert_eq!(read_json(&d.join("settings.json"))["kept"], json!(1));
    assert!(read_now(&d).is_none());
    assert!(write_now(&d, true, Some("dark"), Some("spotify:playlist:x")));
    assert_eq!(read_now(&d), Some(NowPlay { in_match: true, age: Some("dark".into()), playing: Some("spotify:playlist:x".into()) }));
    clear_now(&d); assert!(read_now(&d).is_none());
    assert!(!d.join("config.json.tmp").exists());
    let _ = std::fs::remove_dir_all(&d);
}
