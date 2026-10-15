//! The 1.1 data as the panel shows it; writes go through aoe4core::userstore (same files and keys as Tauri 1.1).
use aoe4core::aoe4::Aoe4;
use aoe4core::game::GameAdapter;
use aoe4core::settings::{self, Settings};
use serde_json::Value;
use std::path::{Path, PathBuf};

pub use aoe4core::userstore::data_dir;

pub struct Data { pub set: Settings, pub ages: Vec<(String, String)>, pub user: Value, pub ed: Value, pub logged_in: bool, pub dir: PathBuf }

fn read(p: &Path) -> Value { std::fs::read_to_string(p).ok().and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null) }

pub fn load() -> Data {
    let dir = data_dir(); let set = settings::load_own(&dir);
    let probe = Aoe4::new(Box::new(|_, _| None));
    let ages = probe.ages().iter().map(|(k, l)| (k.to_string(), l.to_string())).collect();
    Data { user: read(&dir.join("config.json")), ed: read(&dir.join("intros.json")), logged_in: dir.join("token.json").is_file(), set, ages, dir }
}

impl Data {
    /// 1.1 plName: playlist / list / song display name.
    pub fn name(&self, uri: &str) -> String {
        if uri.is_empty() { return String::new(); }
        let id = uri.rsplit(':').next().unwrap_or("");
        if uri.starts_with("aoe4s:list:") { return if id == "liked" { "Liked Songs".into() } else { self.user["custom_lists"][id]["name"].as_str().unwrap_or("My list").into() }; }
        self.set.playlist_names.get(id).cloned().unwrap_or_else(|| if uri.starts_with("spotify:track:") { "Song".into() } else { "Playlist".into() })
    }
    /// Cached cover file for a uri (same lookup as the 1.1 `cover` command).
    pub fn cover(&self, uri: &str) -> Option<PathBuf> {
        let d = self.dir.join("covers"); let id = uri.rsplit(':').next()?;
        if uri.is_empty() { return None; }
        if uri.contains(":list:") { let p = d.join(format!("list_{id}.png")); return p.is_file().then_some(p); }
        if uri.starts_with("spotify:track:") { let p = d.join(format!("track_{id}.jpg")); return p.is_file().then_some(p); }
        std::fs::read_dir(&d).ok()?.flatten().filter(|e| e.file_name().to_string_lossy().starts_with(&format!("{id}_")))
            .max_by_key(|e| e.metadata().and_then(|m| m.modified()).ok()).map(|e| e.path())
    }
    /// Age Intros lit per age (intros on for that age), like the 1.1 overview.
    pub fn intro_lit(&self) -> Vec<bool> {
        let mut s = self.set.clone(); s.user_pools = self.ed["intro_pools"].clone(); s.custom_songs = self.ed["custom_songs"].clone();
        s.intro_ages = self.ed["intro_ages"].as_object().map(|o| o.iter().filter_map(|(k, v)| v.as_bool().map(|b| (k.clone(), b))).collect()).unwrap_or_default();
        let keys: Vec<String> = self.ages.iter().map(|a| a.0.clone()).collect();
        let ov = aoe4core::intros::overview(&s, &keys);
        keys.iter().map(|k| ov[k]["on"].as_bool().unwrap_or(false)).collect()
    }
    /// 1.1 amCfg: (mode, win/loss on, playlist, win, loss).
    pub fn after(&self) -> (String, bool, String, String, String) {
        let a = &self.set.after_match; let g = |k: &str| a[k].as_str().unwrap_or("").to_string();
        let mode = match a["mode"].as_str() { Some(m @ ("resume" | "playlist" | "stop")) => m.to_string(), None => "resume".into(), _ => "stop".into() };
        (mode, a["winloss_on"].as_bool().unwrap_or(a["mode"] == "winloss"), g("playlist"), g("win"), g("loss"))
    }
    /// 1.1 playlist revert: your playlists without age i and without entries equal to the default.
    pub fn playlists_without(&self, i: usize) -> Option<Value> {
        let k = &self.ages.get(i)?.0; let s = &self.set;
        Some(Value::Object(s.playlists.iter().filter(|(a, v)| *a != k && v.as_str() != s.default_playlists.get(*a).map(|x| x.as_str()).unwrap_or(""))
            .map(|(a, v)| (a.clone(), Value::String(v.clone()))).collect()))
    }
    /// 1.1 amSet: copy of after_match (object or {}), changed by f.
    pub fn after_with(&self, f: impl FnOnce(&mut Value)) -> Value {
        let mut a = if self.set.after_match.is_object() { self.set.after_match.clone() } else { serde_json::json!({}) }; f(&mut a); a
    }
}

/// Enabled switch side effect (1.0.9): mute / give back the game music. Windows-only (game registry / config);
/// lives in the launcher crate on BTR, a no-op elsewhere.
pub fn music_sync(_on: bool) {}
/// Login: the browser PKCE flow from aoe4core (runs off the UI thread).
pub fn login() {
    std::thread::spawn(|| { let d = load(); let mut sp = aoe4core::spotify::Spotify::new(d.set.client_id.clone(), d.dir.join("token.json")); let _ = sp.login(); });
}

/// 1.1 `trunc`: at most n characters, the last one an ellipsis (width fitting is done by the view's elide).
pub fn trunc(t: &str, n: usize) -> String { if t.chars().count() <= n { t.to_string() } else { t.chars().take(n - 1).collect::<String>() + "\u{2026}" } }
#[cfg(test)]
mod tests { #[test] fn trunc_like_1_1() { assert_eq!(super::trunc("Chill Lofi Study", 15), "Chill Lofi Stu\u{2026}"); assert_eq!(super::trunc("Peaceful Piano", 15), "Peaceful Piano"); } }
