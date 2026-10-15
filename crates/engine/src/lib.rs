//! AoE4 Spotify app logic without any UI toolkit: the same state, files and behaviour as the Tauri 1.1 app
//! (0e13c77), so a front end only draws `Engine` state and calls its methods.
#![deny(warnings)]
pub mod sys;
pub mod data;
pub mod run;
pub mod updater;
pub mod presets;
pub mod editor;
pub mod picker;
pub mod guides;
pub mod menu;

use aoe4core::aoe4::Aoe4;
use aoe4core::game::GameAdapter;
use aoe4core::settings::{self, Settings};
use aoe4core::spotify::Spotify;
use aoe4core::switcher::Action;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Condvar, Mutex};

#[derive(Default, serde::Serialize, Clone, Debug)]
pub struct Status { pub result: Option<i32>, pub match_n: u64, pub game: String, pub log_path: String, pub watching: bool, pub in_match: bool, pub age: Option<String>, pub playing: Option<String>, pub civ: Option<String>, pub log: Vec<String> }

/// Everything the app knows (Tauri 1.1 AppState without the window bits).
pub struct Engine {
    pub settings: Mutex<Settings>, pub ver: AtomicU64, pub upd: Mutex<serde_json::Value>, pub ages: Vec<(String, String)>,
    pub status: Mutex<Status>, pub cv: Condvar, pub logged: AtomicBool, pub stat: Mutex<Option<(u64, serde_json::Value)>>,
    pub replays: AtomicBool, pub finish: AtomicBool, pub busy: AtomicBool, pub spotify: Mutex<Spotify>, pub tx: Mutex<Sender<Action>>, pub dir: PathBuf, pub ed: Mutex<serde_json::Value>,
    pub pick: Mutex<serde_json::Value>, pub gtg: Mutex<serde_json::Value>,
    /// Set when the game closes so the log watcher leaves the loop.
    pub stop: AtomicBool,
}

impl Engine {
    /// Load everything from `dir` (normally %APPDATA%\AoE4Spotify-1.1). Returns the engine and the Spotify worker queue.
    pub fn new(dir: PathBuf) -> (Arc<Engine>, Receiver<Action>, PathBuf) {
        let settings = settings::load_own(&dir);
        let probe = Aoe4::new(Box::new(|_, _| None));
        let path = settings.log_path.clone().map(PathBuf::from).or_else(|| probe.default_log_path()).unwrap_or_default();
        let ages = probe.ages().iter().map(|(k, l)| (k.to_string(), l.to_string())).collect();
        let status = Status { game: probe.label().into(), log_path: path.display().to_string(), ..Default::default() };
        let spotify = Spotify::new(settings.client_id.clone(), dir.join("token.json")); let logged0 = spotify.logged_in();
        let (tx, rx) = channel(); let replays0 = aoe4core::userstore::replays(&dir, settings.music_in_replays);
        let finish0 = aoe4core::userstore::finish_song(&dir, false);
        let updated = std::env::args().any(|a| a == "--updated");
        let e = Arc::new(Engine { settings: Mutex::new(settings), ver: AtomicU64::new(0),
            upd: Mutex::new(serde_json::json!({ "phase": if updated { "done" } else { "idle" }, "msg": format!("Updated to {}", env!("CARGO_PKG_VERSION")) })),
            ages, status: Mutex::new(status), cv: Condvar::new(), logged: AtomicBool::new(logged0), stat: Mutex::new(None),
            replays: AtomicBool::new(replays0), finish: AtomicBool::new(finish0), busy: AtomicBool::new(false), spotify: Mutex::new(spotify), tx: Mutex::new(tx),
            ed: Mutex::new(data::load_ed(&dir)), dir, pick: Mutex::new(serde_json::Value::Null), gtg: Mutex::new(serde_json::Value::Null),
            stop: AtomicBool::new(false) });
        (e, rx, path)
    }
    /// Start the game-log watcher and the Spotify worker threads. The panel does not call this.
    pub fn start(self: &Arc<Self>, rx: Receiver<Action>, log_path: PathBuf, opts: run::WatchOpts) {
        let a = self.clone(); std::thread::spawn(move || run::watch(a, log_path, opts));
        let b = self.clone(); std::thread::spawn(move || run::player(b, rx));
    }
    /// Settings-side state (settings, your lists / after match, intros, age data, edits), cached per settings version.
    pub fn static_state(&self) -> (u64, serde_json::Value) {
        let v = self.ver.load(Ordering::SeqCst);
        let mut c = self.stat.lock().unwrap();
        if let Some((k, s)) = c.as_ref() { if *k == v { return (v, s.clone()); } }
        let keys: Vec<String> = self.ages.iter().map(|(k, _)| k.clone()).collect();
        let ed = self.ed.lock().unwrap().clone(); let set = self.settings.lock().unwrap().clone(); let es = data::with_ed(&set, &ed);
        let user = data::read_user(&self.dir);
        let s = serde_json::json!({ "settings": set, "user": { "custom_lists": user["custom_lists"], "after_match": user["after_match"], "fade_seconds": user["fade_seconds"] }, "ages": self.ages, "intros": aoe4core::intros::overview(&es, &keys), "agedata": aoe4core::intros::age_data(&es, &keys), "ed": ed });
        *c = Some((v, s.clone())); (v, s)
    }
    /// Live state; never waits for the Spotify lock (a fade holds it for seconds).
    pub fn live_state(&self) -> serde_json::Value {
        let st = self.status.lock().unwrap().clone();
        let logged_in = match self.spotify.try_lock() { Ok(s) => { let v = s.logged_in(); self.logged.store(v, Ordering::SeqCst); v } Err(_) => self.logged.load(Ordering::SeqCst) };
        serde_json::json!({ "upd": self.upd.lock().unwrap().clone(), "status": st, "spotify": { "logged_in": logged_in, "replays": self.replays.load(Ordering::SeqCst), "finish": self.finish.load(Ordering::SeqCst), "busy": self.busy.load(Ordering::SeqCst) } })
    }
    /// Full state, like the Tauri `get_state` (since = settings version the caller already has).
    pub fn state(&self, since: Option<u64>) -> serde_json::Value {
        let mut out = self.live_state(); let (k, s) = self.static_state();
        if since != Some(k) { if let (Some(o), Some(m)) = (out.as_object_mut(), s.as_object()) { for (a, b) in m { o.insert(a.clone(), b.clone()); } } }
        out["skey"] = serde_json::json!(k); out
    }
    /// Fingerprint of everything a view shows (Tauri notifier): changes => redraw.
    pub fn fingerprint(&self) -> String {
        let st = self.status.lock().unwrap().clone();
        serde_json::json!([self.ver.load(Ordering::SeqCst), self.upd.lock().unwrap().clone(), st.in_match, st.age, st.watching, st.playing, st.result, st.match_n,
            self.logged.load(Ordering::SeqCst), self.replays.load(Ordering::SeqCst), self.finish.load(Ordering::SeqCst), self.busy.load(Ordering::SeqCst)]).to_string()
    }
    pub fn push(&self, line: String) { run::push(&self.status, line) }
    pub fn sync_logged(&self) { if let Ok(s) = self.spotify.lock() { self.logged.store(s.logged_in(), Ordering::SeqCst); } }
    pub fn logout(&self) { self.spotify.lock().unwrap().logout(); self.sync_logged(); self.push("Spotify: logged out".into()); }
    pub fn bump(&self) { self.ver.fetch_add(1, Ordering::SeqCst); }
}

pub fn wall() -> f64 { std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs_f64()).unwrap_or(0.0) }
