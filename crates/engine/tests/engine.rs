use aoe4engine::{data, menu, presets, Engine};
use serde_json::json;

/// Also points APPDATA at a temp dir: engine log lines must never land in the real app log.
fn tmp(n: &str) -> std::path::PathBuf { std::env::set_var("APPDATA", std::env::temp_dir().join(format!("aoe4s_eng_appdata_{}", std::process::id()))); let d = std::env::temp_dir().join(format!("aoe4s_eng_{n}_{}", std::process::id())); let _ = std::fs::remove_dir_all(&d); std::fs::create_dir_all(&d).unwrap(); d }

#[test]
fn import_check_and_timestamp() {
    use data::{covered, iso_now};
    assert!(covered(&json!(null), &json!({ "a": 1 })) && covered(&json!({}), &json!({ "a": 1 })) && covered(&json!({ "a": 1 }), &json!({ "a": 2, "b": 3 })));
    assert!(!covered(&json!({ "a": 1, "c": 1 }), &json!({ "a": 1 })) && covered(&json!([1, 2]), &json!([2, 1, 3])) && !covered(&json!([4]), &json!([1])));
    let t = iso_now(); assert!(t.len() == 20 && t.starts_with("20") && t.ends_with('Z') && &t[10..11] == "T", "{t}");
}

#[test]
fn settings_writes_bump_version_and_respect_allow_list() {
    let d = tmp("set"); let (e, _rx, _p) = Engine::new(d.clone());
    let (k0, _) = e.static_state();
    assert!(data::set_user(&e, "fade_seconds", json!(4.0)));
    assert!(!data::set_user(&e, "client_id", json!("nope")));
    let (k1, s) = e.static_state(); assert!(k1 > k0);
    assert_eq!(s["settings"]["fade_seconds"], json!(4.0));
    assert!(data::read_user(&d).get("client_id").is_none());
    let st = e.state(Some(k1)); assert!(st.get("settings").is_none() && st["skey"] == json!(k1));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn preset_code_roundtrip() {
    let d = tmp("pre"); let (e, _rx, _p) = Engine::new(d.clone());
    let cat: serde_json::Value = serde_json::from_str(aoe4core::intros::CATALOG).unwrap();
    let civ = cat["factions"][0][0].as_str().unwrap().to_string(); let song = cat["songs"][0][3].as_str().unwrap().to_string();
    let age = e.ages[0].0.clone();
    let code = presets::encode_preset(json!({ "name": "Mine", "pools": { age.clone(): { civ.clone(): [song.clone()] } }, "ages": { age.clone(): true }, "custom": [] }));
    assert!(code.starts_with("AOE4S1:"));
    let p = presets::decode_preset(&e, code).unwrap();
    assert_eq!(p["name"], json!("Mine")); assert_eq!(p["pools"][&age][&civ][0], json!(song)); assert_eq!(p["ages"][&age], json!(true));
    assert!(presets::decode_preset(&e, "hello".into()).is_err());
    assert!(presets::decode_preset(&e, "AOE4S2:abc".into()).unwrap_err().contains("newer"));
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn menu_opens_and_replays_toggle() {
    let d = tmp("menu"); let (e, _rx, _p) = Engine::new(d.clone());
    let log = d.join("dry.txt"); std::env::set_var("AOE4S_DRYOPEN", &log);
    menu::menu(&e, "github"); menu::menu(&e, "pl:37i9dQZF1DX8Uebhn9wzrS"); menu::menu(&e, "pl:short");
    let r0 = aoe4core::userstore::replays(&d, false); menu::menu(&e, "replays"); assert_ne!(aoe4core::userstore::replays(&d, false), r0);
    let f0 = aoe4core::userstore::finish_song(&d, false); menu::menu(&e, "finish"); assert_ne!(aoe4core::userstore::finish_song(&d, false), f0); assert!(e.finish.load(std::sync::atomic::Ordering::SeqCst));
    assert_eq!(menu::menu(&e, "uninstall"), "Uninstaller not found (not installed?).");
    let t = std::fs::read_to_string(&log).unwrap();
    assert_eq!(t.lines().collect::<Vec<_>>(), vec!["https://github.com/Capstar1/aoe4-spotify", "spotify:playlist:37i9dQZF1DX8Uebhn9wzrS"]);
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn lists_save_pick_and_delete() {
    let d = tmp("list"); let (e, _rx, _p) = Engine::new(d.clone());
    let uri = aoe4engine::picker::save_list(&e, "".into(), "  Fav ".into(), json!([{ "uri": "spotify:track:1111111111111111111111", "name": "A" }, { "uri": "x" }]), b"png");
    assert!(uri.starts_with("aoe4s:list:"));
    let u = data::read_user(&d); let id = uri.rsplit(':').next().unwrap();
    assert_eq!(u["custom_lists"][id]["name"], json!("Fav")); assert_eq!(u["custom_lists"][id]["tracks"].as_array().unwrap().len(), 1);
    let age = e.ages[1].0.clone();
    aoe4engine::picker::open_pick(&e, &format!("age:{age}"), "Feudal", false, "");
    aoe4engine::picker::pick_done(&e, uri.clone(), "".into(), "".into());
    assert_eq!(data::read_user(&d)["playlists"][&age], json!(uri));
    aoe4engine::picker::delete_list(&e, id.to_string());
    let u = data::read_user(&d); assert!(u["custom_lists"].get(id).is_none() && u["playlists"].get(&age).is_none());
    assert!(!d.join("covers").join(format!("list_{id}.png")).exists());
    let _ = std::fs::remove_dir_all(&d);
}

#[test]
fn email_rules() { use aoe4engine::guides::email_ok; assert!(email_ok("a@b.co")); assert!(!email_ok("a@b")); assert!(!email_ok("a b@c.de")); assert!(!email_ok("@c.de")); }
