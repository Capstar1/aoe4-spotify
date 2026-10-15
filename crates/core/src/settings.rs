//! Reads the 1.0.x settings read-only: install config.json (defaults) with %APPDATA%\AoE4Spotify\config.json on top.
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

#[derive(Debug, Clone, serde::Serialize)]
pub struct Settings {
    pub enabled: bool,
    pub fade_seconds: f32,
    pub playlists: HashMap<String, String>,
    pub playlist_names: HashMap<String, String>,
    pub intro_ages: HashMap<String, bool>,
    pub log_path: Option<String>,
    /// public PKCE app id from the install config (not shown in the UI)
    #[serde(skip)]
    pub client_id: String,
    /// The shared app that ships with the installer (Your Spotify app: "Use the shared app instead").
    pub shared_client_id: String,
    /// Using your own Spotify app (own_app + a valid client_id in your settings).
    pub own_app: bool,
    /// Age Intros: install boss_intro (default pools) + your per-age pools; after-match choice; intros master switch
    #[serde(skip)]
    pub base_boss: Value,
    #[serde(skip)]
    pub user_pools: Value,
    pub after_match: Value,
    pub boss_on: bool,
    pub default_playlists: HashMap<String, String>,
    pub music_in_replays: bool,
    /// your own intro songs [{uri,name,artist}] (1.0.9 "custom_songs")
    #[serde(skip)]
    pub custom_songs: Value,
}

fn read(p: &Path) -> Value { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null) }

fn str_map(v: &Value) -> HashMap<String, String> {
    v.as_object().map(|o| o.iter().filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string()))).collect()).unwrap_or_default()
}

pub fn load(install_cfg: &Path, user_cfg: &Path, names: &Path) -> Settings {
    let base = read(install_cfg); let user = read(user_cfg);
    let mut playlists = str_map(&base["default_playlists"]);
    playlists.extend(str_map(&base["playlists"]));
    playlists.extend(str_map(&user["playlists"]));
    let get = |k: &str| if user[k].is_null() { base[k].clone() } else { user[k].clone() };
    let intro_ages = get("intro_ages").as_object()
        .map(|o| o.iter().map(|(k, v)| (k.clone(), v.as_bool().unwrap_or(true))).collect()).unwrap_or_default();
    Settings {
        enabled: get("enabled").as_bool().unwrap_or(true),
        fade_seconds: get("fade_seconds").as_f64().unwrap_or(2.0) as f32,
        playlists,
        playlist_names: str_map(&read(names)),
        intro_ages,
        base_boss: base["boss_intro"].clone(),
        user_pools: user["intro_pools"].clone(),
        after_match: user["after_match"].clone(),
        default_playlists: str_map(&base["default_playlists"]),
        boss_on: user["boss_intro_enabled"].as_bool().or(base["boss_intro"]["enabled"].as_bool()).unwrap_or(true),
        custom_songs: user["custom_songs"].clone(),
        music_in_replays: get("music_in_replays").as_bool().unwrap_or(false),
        client_id: own_cid(&user).unwrap_or_else(|| base["client_id"].as_str().unwrap_or_default().to_string()),
        shared_client_id: base["client_id"].as_str().unwrap_or_default().to_string(),
        own_app: own_cid(&user).is_some(),
        log_path: get("log_path").as_str().filter(|s| !s.is_empty()).map(|s| s.to_string()),
    }
}

/// 1.0.9 client_id_ok: a Spotify Client ID is 32 hex characters (the Client Secret has the same shape; the guide says which).
pub fn client_id_ok(v: &str) -> bool { v.len() == 32 && v.chars().all(|c| c.is_ascii_hexdigit()) }
fn own_cid(user: &serde_json::Value) -> Option<String> {
    let c = user["client_id"].as_str()?.trim(); if user["own_app"].as_bool() == Some(true) && client_id_ok(c) { Some(c.to_lowercase()) } else { None }
}

/// 1.1's own copies (imported once from 1.0.9 into %APPDATA%\AoE4Spotify-1.1).
pub fn load_own(dir: &Path) -> Settings {
    let exe_cfg = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.join("config.json")));
    let base = if dir.join("base.json").is_file() { dir.join("base.json") } else { exe_cfg.unwrap_or_else(|| dir.join("base.json")) };   // installer ships config.json next to the exe
    load(&base, &dir.join("config.json"), &dir.join("playlist_names.json"))
}

/// The 1.0.x files on this PC (installed app + user data) - only used by the one-time import.
pub fn load_installed() -> Settings {
    let la = std::env::var("LOCALAPPDATA").unwrap_or_default();
    let ad = std::env::var("APPDATA").unwrap_or_default();
    load(&Path::new(&la).join(r"Programs\AoE4 Spotify\_internal\config.json"),
         &Path::new(&ad).join(r"AoE4Spotify\config.json"),
         &Path::new(&ad).join(r"AoE4Spotify\playlist_names.json"))
}