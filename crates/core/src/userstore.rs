//! Your 1.1 settings files in %APPDATA%\AoE4Spotify-1.1 (config.json, settings.json), shared by every front end.
//! Same rules as the Tauri 1.1 `set_user`: only known keys, atomic write (tmp + rename), null removes the key.
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

/// Keys the panel may write to config.json (1.1 `set_user` allow-list).
pub const USER_KEYS: [&str; 6] = ["enabled", "fade_seconds", "playlists", "boss_intro_enabled", "after_match", "custom_lists"];

pub fn data_dir() -> PathBuf { PathBuf::from(std::env::var("APPDATA").unwrap_or_default()).join("AoE4Spotify-1.1") }

pub fn read_json(p: &Path) -> Value { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(&s).ok()).filter(|v: &Value| v.is_object()).unwrap_or_else(|| json!({})) }

pub fn write_atomic(p: &Path, v: &Value) -> std::io::Result<()> {
    if let Some(d) = p.parent() { std::fs::create_dir_all(d)?; }
    let tmp = p.with_extension("json.tmp");
    std::fs::write(&tmp, serde_json::to_string_pretty(v).unwrap_or_default())?;
    std::fs::rename(&tmp, p)
}

pub fn read_user(dir: &Path) -> Value { read_json(&dir.join("config.json")) }

/// Set (or with null: remove) one allowed key in config.json. Returns false for an unknown key.
pub fn set_user(dir: &Path, k: &str, v: Value) -> bool {
    if !USER_KEYS.contains(&k) { return false; }
    let mut u = read_user(dir);
    if v.is_null() { if let Some(o) = u.as_object_mut() { o.remove(k); } } else { u[k] = v; }
    write_atomic(&dir.join("config.json"), &u).is_ok()
}

/// "Music in replays" (settings.json, 1.1 prefs).
pub fn replays(dir: &Path, default: bool) -> bool { read_json(&dir.join("settings.json"))["music_in_replays"].as_bool().unwrap_or(default) }
pub fn set_replays(dir: &Path, on: bool) -> bool { write_atomic(&dir.join("settings.json"), &json!({ "music_in_replays": on })).is_ok() }
