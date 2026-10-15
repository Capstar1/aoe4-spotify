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
    assert!(!d.join("config.json.tmp").exists());
    let _ = std::fs::remove_dir_all(&d);
}
