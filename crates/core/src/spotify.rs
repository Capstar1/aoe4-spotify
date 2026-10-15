//! Spotify Web API client for 1.1: PKCE login with its OWN token file (separate from 1.0.9), playback,
//! volume fades through the API, and putting your previous music back after the match. Tokens are never logged.
/// Self-contained pages shown in the browser after the Spotify redirect (approved mockups).
const LOGIN_OK_HTML: &str = include_str!("../assets/login_ok.html");
const LOGIN_FAIL_HTML: &str = include_str!("../assets/login_fail.html");
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const REDIRECT: &str = "http://127.0.0.1:8888/callback";
pub const SCOPES: &str = "user-modify-playback-state user-read-playback-state playlist-read-private playlist-read-collaborative user-library-read";
const LIKED: &str = "aoe4s:list:liked";

#[derive(serde::Serialize, serde::Deserialize, Clone, Default)]
struct Token { access_token: String, refresh_token: String, expires_at: u64 }

/// Production endpoints; tests point a client at a local mock server (`Spotify::with_base`).
pub const API: &str = "https://api.spotify.com/v1";
pub const ACCOUNTS: &str = "https://accounts.spotify.com";

pub struct Spotify {
    cid: String,
    api_base: String,
    accounts_base: String,
    path: PathBuf,
    tok: Option<Token>,
    agent: ureq::Agent,
    device: Option<String>,
    /// what was playing before the first switch of this match (null = nothing)
    saved: Option<Value>,
    saved_volume: Option<i64>,
    /// Repeat mode from before the intro (`off` / `track` / `context`). Put back when the playlist starts.
    /// None when this play is not following an intro, so an ordinary age switch does not touch repeat.
    repeat_restore: Option<String>,
    /// Player stand-in for `AOE4S_TEST=1` + `AOE4S_FAKESP`. Never used against the live API.
    fake_player: Option<Value>,
    /// Wall-clock start of the current intro when `AOE4S_FAKESP=slow`.
    fake_from: Option<Instant>,
}

/// One Web API request with the 1.1 retry rules: network errors and 5xx are retried with backoff (0.3 s, 0.9 s),
/// 429 waits Retry-After (capped at 5 s) and tries again. `tries` = 1 means a single attempt (volume steps).
/// Every call here is idempotent (GET / PUT on the player), so a retry never does anything twice.
pub fn send(agent: &ureq::Agent, method: &str, url: &str, tok: &str, body: Option<&Value>, timeout: Duration, tries: u32) -> Result<(u16, Value), String> {
    let parse = |r: ureq::Response| { let c = r.status(); let t = r.into_string().unwrap_or_default(); (c, serde_json::from_str(&t).unwrap_or(Value::Null)) };
    let mut last = String::new();
    for n in 0..tries.max(1) {
        let req = agent.request(method, url).set("Authorization", &format!("Bearer {tok}")).timeout(timeout);
        let r = match body { Some(b) => req.send_json(b.clone()), None if method != "GET" => req.set("Content-Length", "0").call(), None => req.call() };
        let more = n + 1 < tries.max(1);
        match r {
            Ok(r) => return Ok(parse(r)),
            Err(ureq::Error::Status(429, r)) if more => {
                let wait = r.header("Retry-After").and_then(|v| v.trim().parse::<f64>().ok()).unwrap_or(1.0).clamp(0.0, 5.0);
                std::thread::sleep(Duration::from_secs_f64(wait)); last = "Spotify rate limit (429)".into();
            }
            Err(ureq::Error::Status(c, _)) if c >= 500 && more => { std::thread::sleep(backoff(n)); last = format!("Spotify error {c}"); }
            Err(ureq::Error::Status(_, r)) => return Ok(parse(r)),
            Err(e) => { last = format!("Spotify unreachable: {e}"); if more { std::thread::sleep(backoff(n)); } }
        }
    }
    Err(last)
}
fn backoff(n: u32) -> Duration { Duration::from_millis(300 * 3u64.pow(n.min(3))) }
const TRIES: u32 = 3;
const CALL_T: Duration = Duration::from_secs(10);
/// Fade steps: short, single try - a slow step is skipped instead of stretching the fade.
const VOL_T: Duration = Duration::from_secs(2);

/// A logged-in handle for reads WITHOUT the Spotify lock (picker, search, /me): the caller takes the lock only
/// to get this (token refreshed if needed), then does its HTTP after releasing it.
#[derive(Clone)]
pub struct Web { agent: ureq::Agent, api_base: String, tok: String }
impl Web {
    pub fn get(&self, path: &str) -> Result<(u16, Value), String> { send(&self.agent, "GET", &format!("{}{path}", self.api_base), &self.tok, None, CALL_T, TRIES) }
}
/// Plain download (cover art); needs no login, so never the Spotify lock.
pub fn fetch(url: &str) -> Result<Vec<u8>, String> {
    let r = ureq::get(url).timeout(CALL_T).call().map_err(|e| e.to_string())?; let mut b = vec![]; std::io::Read::read_to_end(&mut r.into_reader(), &mut b).map_err(|e| e.to_string())?; Ok(b)
}

fn now() -> u64 { SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0) }
fn rand_str(n: usize) -> String { let mut b = vec![0u8; n]; let _ = getrandom::getrandom(&mut b); URL_SAFE_NO_PAD.encode(b) }
pub fn enc(s: &str) -> String {
    s.bytes().map(|b| match b { b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => (b as char).to_string(), _ => format!("%{:02X}", b) }).collect()
}
pub fn challenge(verifier: &str) -> String { URL_SAFE_NO_PAD.encode(Sha256::digest(verifier.as_bytes())) }
fn query(q: &str, key: &str) -> Option<String> {
    q.split('&').find_map(|kv| { let (k, v) = kv.split_once('=')?; (k == key).then(|| v.to_string()) })
}

impl Spotify {
    pub fn new(cid: String, path: PathBuf) -> Self { Self::with_base(cid, path, API, ACCOUNTS) }
    /// Same client against other endpoints (tests: a local mock server).
    pub fn with_base(cid: String, path: PathBuf, api: &str, accounts: &str) -> Self {
        let tok = std::fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str(&s).ok());
        let agent = ureq::AgentBuilder::new().timeout(CALL_T).build();
        Spotify { cid, api_base: api.to_string(), accounts_base: accounts.to_string(), path, tok, agent, device: None, saved: None, saved_volume: None, repeat_restore: None, fake_player: None, fake_from: None }
    }
    /// Read handle for use outside the lock (see `Web`).
    pub fn web(&mut self) -> Result<Web, String> { let tok = self.access()?; Ok(Web { agent: self.agent.clone(), api_base: self.api_base.clone(), tok }) }
    pub fn logged_in(&self) -> bool { self.tok.is_some() }
    /// Re-read token.json. The panel may have logged in while this process was already up.
    /// A missing file clears the login. A half-written file keeps the previous login. The token is never logged.
    pub fn reload_token(&mut self) {
        if !self.path.is_file() { self.tok = None; return; }
        if let Ok(s) = std::fs::read_to_string(&self.path) { if let Ok(t) = serde_json::from_str::<Token>(&s) { self.tok = Some(t); } }
    }
    pub fn has_client(&self) -> bool { !self.cid.is_empty() }

    fn save(&self) {
        if let (Some(t), Some(dir)) = (&self.tok, self.path.parent()) {
            let _ = std::fs::create_dir_all(dir);
            let tmp = self.path.with_extension("tmp");
            if std::fs::write(&tmp, serde_json::to_vec(t).unwrap_or_default()).is_ok() { let _ = std::fs::rename(&tmp, &self.path); }
        }
    }

    fn token_req(&mut self, form: &[(&str, &str)]) -> Result<(), String> {
        let r = self.agent.post(&format!("{}/api/token", self.accounts_base)).send_form(form);
        let v: Value = match r {
            Ok(r) => r.into_json().map_err(|e| e.to_string())?,
            Err(ureq::Error::Status(c, r)) => {
                // Only a dead login (invalid_grant: refresh token revoked / expired) logs you out; any other refusal
                // (a short Spotify-side problem) keeps the saved login so the next try can work.
                let body: Value = r.into_json().unwrap_or(Value::Null);
                if c == 400 && body["error"].as_str() == Some("invalid_grant") { self.tok = None; let _ = std::fs::remove_file(&self.path); return Err("Spotify login expired - log in again".into()); }
                return Err(format!("Spotify login refused ({c}) - try again"));
            }
            Err(e) => return Err(format!("Spotify unreachable: {e}")),
        };
        let old = self.tok.take().unwrap_or_default();
        self.tok = Some(Token {
            access_token: v["access_token"].as_str().unwrap_or_default().to_string(),
            refresh_token: v["refresh_token"].as_str().map(|s| s.to_string()).unwrap_or(old.refresh_token),
            expires_at: now() + v["expires_in"].as_u64().unwrap_or(3600),
        });
        self.save(); Ok(())
    }

    fn access(&mut self) -> Result<String, String> {
        let t = self.tok.clone().ok_or("Not logged in to Spotify (1.1)")?;
        if t.expires_at > now() + 60 { return Ok(t.access_token); }
        let cid = self.cid.clone();
        self.token_req(&[("grant_type", "refresh_token"), ("refresh_token", &t.refresh_token), ("client_id", &cid)])?;
        Ok(self.tok.as_ref().unwrap().access_token.clone())
    }

    /// Browser login (PKCE). Blocks until Spotify redirects back or 3 minutes pass.
    pub fn login(&mut self) -> Result<(), String> { let (c, v) = Self::login_code(&self.cid.clone())?; self.login_finish(&c, &v) }
    pub fn client_id(&self) -> String { self.cid.clone() }
    /// Switch Spotify app (Your Spotify app / shared): a different id drops the old login (1.0.9 save_own_client).
    pub fn set_client(&mut self, cid: &str) -> bool {
        if self.cid == cid { return false; }
        self.cid = cid.to_string(); self.tok = None; let _ = std::fs::remove_file(&self.path); true
    }
    /// Browser part of the login: needs no &self, so callers can wait for it WITHOUT holding the Spotify lock
    /// (holding it froze the panel for up to 3 minutes while the auth tab was open). Returns (code, verifier).
    pub fn login_code(cid: &str) -> Result<(String, String), String> {
        if cid.is_empty() { return Err("No Spotify client id in the 1.0.9 install config".into()); }
        let verifier = rand_str(48); let state = rand_str(12);
        let listener = TcpListener::bind("127.0.0.1:8888").map_err(|_| "Port 8888 is busy (is a 1.0.9 login window open?)".to_string())?;
        let url = format!("https://accounts.spotify.com/authorize?client_id={}&response_type=code&redirect_uri={}&code_challenge_method=S256&code_challenge={}&scope={}&state={}",
            enc(cid), enc(REDIRECT), challenge(&verifier), enc(SCOPES), state);
        crate::os::open(&url).map_err(|e| e.to_string())?;
        listener.set_nonblocking(true).ok();
        let deadline = Instant::now() + Duration::from_secs(180);
        let code = loop {
            if Instant::now() > deadline { return Err("Login timed out".into()); }
            match listener.accept() {
                Ok((mut s, _)) => {
                    s.set_nonblocking(false).ok(); s.set_read_timeout(Some(Duration::from_secs(5))).ok();
                    let mut buf = [0u8; 4096]; let n = s.read(&mut buf).unwrap_or(0);
                    let req = String::from_utf8_lossy(&buf[..n]).to_string();
                    let path = req.split_whitespace().nth(1).unwrap_or("").to_string();
                    let Some(q) = path.strip_prefix("/callback?") else { let _ = s.write_all(b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"); continue };
                    let ok = query(q, "state").as_deref() == Some(state.as_str()) && query(q, "code").is_some();
                    let body = if ok { LOGIN_OK_HTML } else { LOGIN_FAIL_HTML };
                    let _ = s.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{}", body.len(), body).as_bytes());
                    if !ok { return Err("Login cancelled".into()); }
                    break query(q, "code").unwrap();
                }
                Err(_) => std::thread::sleep(Duration::from_millis(100)),
            }
        };
        Ok((code, verifier))
    }
    pub fn login_finish(&mut self, code: &str, verifier: &str) -> Result<(), String> {
        let cid = self.cid.clone();
        self.token_req(&[("grant_type", "authorization_code"), ("code", code), ("redirect_uri", REDIRECT), ("client_id", &cid), ("code_verifier", verifier)])
    }

    pub fn logout(&mut self) { self.tok = None; let _ = std::fs::remove_file(&self.path); }

    fn api(&mut self, method: &str, path: &str, body: Option<Value>) -> Result<(u16, Value), String> {
        if fake_on() { return self.fake(method, path, body); }
        let tok = self.access()?;
        send(&self.agent, method, &format!("{}{path}", self.api_base), &tok, body.as_ref(), CALL_T, TRIES)
    }


    fn ensure_device(&mut self) -> Result<String, String> {
        let (_, d) = self.api("GET", "/me/player/devices", None)?;
        let devs = d["devices"].as_array().cloned().unwrap_or_default();
        let pick = devs.iter().find(|x| x["is_active"].as_bool() == Some(true))
            .or_else(|| devs.iter().find(|x| x["type"].as_str() == Some("Computer")))
            .or_else(|| devs.first());
        let id = pick.and_then(|x| x["id"].as_str()).ok_or("No Spotify device - open Spotify on this PC")?.to_string();
        self.device = Some(id.clone()); Ok(id)
    }

    fn state(&mut self) -> Value { self.api("GET", "/me/player", None).map(|(_, v)| v).unwrap_or(Value::Null) }
    fn set_volume(&mut self, v: i64) {
        let q = self.device.as_ref().map(|d| format!("&device_id={d}")).unwrap_or_default();
        let pct = v.clamp(0, 100);
        if fake_on() { let _ = self.api("PUT", &format!("/me/player/volume?volume_percent={pct}{q}"), None); return; }
        let Ok(tok) = self.access() else { return };
        let _ = send(&self.agent, "PUT", &format!("{}/me/player/volume?volume_percent={pct}{q}", self.api_base), &tok, None, VOL_T, 1);
    }
    /// Volume ramp in a few API steps (Spotify rate-limits fast volume changes).
    fn fade(&mut self, from: i64, to: i64, secs: f32) {
        if secs <= 0.05 || from == to { self.set_volume(to); return; }
        let steps = 5; let dt = Duration::from_secs_f32(secs / steps as f32);
        for i in 1..=steps { self.set_volume(from + (to - from) * i / steps); std::thread::sleep(dt); }
    }

    fn payload(&mut self, uri: &str) -> Result<Value, String> {
        if uri == LIKED {
            let (_, v) = self.api("GET", "/me/tracks?limit=50", None)?;
            let uris: Vec<Value> = v["items"].as_array().cloned().unwrap_or_default().iter().filter_map(|i| i["track"]["uri"].as_str().map(|s| json!(s))).collect();
            if uris.is_empty() { return Err("Liked Songs is empty".into()); }
            return Ok(json!({ "uris": uris }));
        }
        if let Some(l) = uri.strip_prefix("uris:") { return Ok(json!({ "uris": l.split(',').collect::<Vec<_>>() })); }   // app-only list
        if uri.starts_with("spotify:track:") { return Ok(json!({ "uris": [uri] })); }
        if uri.starts_with("spotify:") { return Ok(json!({ "context_uri": uri })); }
        Err(format!("{uri}: app-only lists come in M3"))
    }

    fn put_play(&mut self, dev: &str, body: Value) -> Result<(), String> {
        let (c, v) = self.api("PUT", &format!("/me/player/play?device_id={dev}"), Some(body))?;
        if (200..300).contains(&c) { Ok(()) } else { Err(format!("Spotify play failed ({c}): {}", v["error"]["message"].as_str().unwrap_or(""))) }
    }

    /// Age-page chip click (1.0.9 preview): play that one track now / pause it.
    pub fn preview(&mut self, uri: &str) -> Result<(), String> { let dev = self.device_fast()?; self.put_play_or_retry(&dev, json!({ "uris": [uri] })) }
    /// Last known device, without the /me/player/devices round trip (one request per click instead of two).
    fn device_fast(&mut self) -> Result<String, String> { match self.device.clone() { Some(d) => Ok(d), None => self.ensure_device() } }
    /// Play on a cached device; if Spotify refuses it (device gone / switched), look the device up again once.
    fn put_play_or_retry(&mut self, dev: &str, body: Value) -> Result<(), String> {
        match self.put_play(dev, body.clone()) { Ok(()) => Ok(()), Err(_) => { let d = self.ensure_device()?; self.put_play(&d, body) } }
    }
    pub fn pause(&mut self) -> Result<(), String> {
        let dev = self.device_fast()?; let (c, _) = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None)?;
        if (200..300).contains(&c) { Ok(()) } else { Err(format!("pause failed ({c})")) }
    }

    /// Repeat off, then the intro. The user's repeat mode is remembered from the player snapshot this
    /// play already reads (no extra GET) and put back when the age playlist starts. A second intro
    /// before that playlist keeps the original mode. The repeat PUT is the one extra call.
    pub fn play_intro(&mut self, uri: &str, fade_s: f32) -> Result<(), String> {
        let dev = self.ensure_device()?;
        let st = self.state();
        let prev = if self.repeat_restore.is_none() {
            Some(st["repeat_state"].as_str().filter(|s| matches!(*s, "off" | "track" | "context")).unwrap_or("off").to_string())
        } else {
            None
        };
        self.put_repeat("off")?;
        if let Some(prev) = prev { self.repeat_restore = Some(prev); }
        self.play_from(&dev, &st, uri, fade_s)
    }

    /// Age switch: fade down, start the age's music, fade back up to your volume.
    /// After an intro, put the user's repeat mode back first. An ordinary switch leaves repeat alone.
    pub fn play_age(&mut self, uri: &str, fade_s: f32) -> Result<(), String> {
        self.restore_user_repeat();
        let dev = self.ensure_device()?;
        let st = self.state();
        self.play_from(&dev, &st, uri, fade_s)
    }

    fn play_from(&mut self, dev: &str, st: &Value, uri: &str, fade_s: f32) -> Result<(), String> {
        if self.saved.is_none() { self.saved = Some(st.clone()); self.saved_volume = st["device"]["volume_percent"].as_i64(); }
        let base = self.saved_volume.unwrap_or(60);
        let cur = st["device"]["volume_percent"].as_i64().unwrap_or(base);
        let playing = st["is_playing"].as_bool() == Some(true);
        let low = base / 5;
        if playing { self.fade(cur, low, fade_s / 2.0) } else { self.set_volume(low) }
        let body = self.payload(uri)?;
        let r = self.put_play(dev, body);
        self.fade(low, base, fade_s / 2.0);
        r
    }

    fn put_repeat(&mut self, state: &str) -> Result<(), String> {
        if !matches!(state, "off" | "track" | "context") { return Ok(()); }
        let q = self.device.as_ref().map(|d| format!("&device_id={d}")).unwrap_or_default();
        let (c, v) = self.api("PUT", &format!("/me/player/repeat?state={state}{q}"), None)?;
        if (200..300).contains(&c) { Ok(()) } else { Err(format!("Spotify repeat failed ({c}): {}", v["error"]["message"].as_str().unwrap_or(""))) }
    }

    /// Put back the repeat mode saved for an intro. Skipped when it was already off, and when no intro set it.
    fn restore_user_repeat(&mut self) {
        let Some(prev) = self.repeat_restore.take() else { return };
        if prev != "off" { let _ = self.put_repeat(&prev); }
    }

    /// Player state now (After match: waits for the Win / Loss song to end).
    pub fn player_state(&mut self) -> Value { self.state() }
    /// After match picked something else: the pre-match music is not put back.
    pub fn forget_saved(&mut self) { self.saved = None; self.saved_volume = None; }
    /// After match Stop (1.0.9 fade_pause): fade out, pause, put your volume back while paused.
    pub fn fade_pause(&mut self, fade_s: f32) -> Result<(), String> {
        self.restore_user_repeat();
        let dev = self.ensure_device()?;
        let st = self.state(); let cur = st["device"]["volume_percent"].as_i64().unwrap_or(60);
        let vol = self.saved_volume.take().unwrap_or(cur); self.saved = None;
        if st["is_playing"].as_bool() == Some(true) { self.fade(cur, vol / 5, fade_s); }
        let _ = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None);
        self.set_volume(vol); Ok(())
    }
    /// Match over: fade out, put back what was playing before (or pause), and your volume.
    pub fn restore(&mut self, fade_s: f32) -> Result<String, String> {
        self.restore_user_repeat();
        let Some(prev) = self.saved.take() else { return Ok("nothing to restore".into()) };
        let vol = self.saved_volume.take().unwrap_or(60);
        let dev = self.ensure_device()?;
        let cur = self.state()["device"]["volume_percent"].as_i64().unwrap_or(vol);
        self.fade(cur, vol / 5, fade_s / 2.0);
        let item = prev["item"]["uri"].as_str().map(|s| s.to_string());
        let msg = if let Some(item) = item {
            let pos = prev["progress_ms"].as_i64().unwrap_or(0);
            let body = match prev["context"]["uri"].as_str() {
                Some(ctx) if ctx.starts_with("spotify:") && !ctx.contains(":collection") => json!({ "context_uri": ctx, "offset": { "uri": item }, "position_ms": pos }),
                _ => json!({ "uris": [item], "position_ms": pos }),
            };
            self.put_play(&dev, body)?;
            if prev["is_playing"].as_bool() != Some(true) { let _ = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None); }
            "previous music restored".to_string()
        } else {
            let _ = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None);
            "nothing was playing before - paused".to_string()
        };
        self.fade(vol / 5, vol, fade_s / 2.0);
        Ok(msg)
    }

    /// Local player for the sandbox sim. No network, and the token is never read.
    fn fake(&mut self, method: &str, path: &str, body: Option<Value>) -> Result<(u16, Value), String> {
        if self.fake_player.is_none() {
            self.fake_player = Some(json!({
                "is_playing": true,
                "progress_ms": 1000,
                "repeat_state": "context",
                "device": { "id": "fake", "volume_percent": 50 },
                "item": { "uri": "spotify:track:before", "duration_ms": 180000 },
                "context": { "uri": "spotify:playlist:before" }
            }));
        }
        let (route, q) = path.split_once('?').unwrap_or((path, ""));
        match (method, route) {
            ("GET", "/me/player/devices") => Ok((200, json!({ "devices": [{ "id": "fake", "is_active": true, "type": "Computer" }] }))),
            ("GET", "/me/player") => { self.fake_tick(); Ok((200, self.fake_player.clone().unwrap_or(Value::Null))) }
            ("PUT", "/me/player/repeat") => {
                let state = query(q, "state").unwrap_or_else(|| "off".into());
                self.fake_note(&format!("repeat {state}"));
                if let Some(p) = self.fake_player.as_mut() { p["repeat_state"] = json!(state); }
                Ok((204, Value::Null))
            }
            ("PUT", "/me/player/play") => {
                let uri = body.as_ref().and_then(|b| {
                    b["uris"].as_array().and_then(|a| a.first()).and_then(|x| x.as_str()).or_else(|| b["context_uri"].as_str())
                }).unwrap_or("").to_string();
                self.fake_note(&format!("play {uri}"));
                let track = uri.starts_with("spotify:track:");
                let slow = track && fake_slow();
                let dur = if !track { 180_000 } else if slow { 3_000 } else { 10_000 };
                let pos = if slow || !track { 0 } else { dur - crate::boss::INTRO_LEAD_MS };
                self.fake_from = if slow { Some(Instant::now()) } else { None };
                if let Some(p) = self.fake_player.as_mut() {
                    p["is_playing"] = json!(true);
                    p["progress_ms"] = json!(pos);
                    p["item"] = json!({ "uri": uri, "duration_ms": dur });
                }
                Ok((204, Value::Null))
            }
            _ => Ok((204, Value::Null)),
        }
    }

    /// `AOE4S_FAKESP=slow`: an intro starts at position 0 and is about 3 s. Progress follows the
    /// wall clock. Past the end, Spotify's repeat-off report: same track, not playing, position 0.
    fn fake_tick(&mut self) {
        if !fake_slow() { return; }
        let Some(t0) = self.fake_from else { return; };
        let Some(p) = self.fake_player.as_mut() else { return; };
        let uri = p["item"]["uri"].as_str().unwrap_or("");
        if !uri.starts_with("spotify:track:") { return; }
        let dur = p["item"]["duration_ms"].as_i64().unwrap_or(0);
        if dur <= 0 { return; }
        let elapsed = t0.elapsed().as_millis() as i64;
        if elapsed >= dur {
            p["is_playing"] = json!(false);
            p["progress_ms"] = json!(0);
        } else {
            p["is_playing"] = json!(true);
            p["progress_ms"] = json!(elapsed);
        }
    }

    fn fake_note(&self, line: &str) {
        let Some(dir) = self.path.parent() else { return };
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("fake_spotify.log")) {
            let _ = writeln!(f, "{line}");
        }
    }
}

/// Sandbox playback. Both switches are required so a stray `AOE4S_FAKESP` cannot stand in for Spotify.
fn fake_on() -> bool { fake_mode().is_some() }
/// `1` parks an intro inside the handoff. `slow` plays it from the start for about 3 s.
fn fake_slow() -> bool { fake_mode().as_deref() == Some("slow") }
fn fake_mode() -> Option<String> {
    if std::env::var("AOE4S_TEST").ok().as_deref() != Some("1") { return None; }
    std::env::var("AOE4S_FAKESP").ok().filter(|s| !s.is_empty())
}
