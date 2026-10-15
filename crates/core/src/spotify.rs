//! Spotify Web API client for 1.1: PKCE login with its OWN token file (separate from 1.0.9), playback,
//! volume fades, and putting your previous music back after the match. On this PC the fade is the Windows
//! per-app volume of Spotify.exe (60 fps). Anywhere else it is the Web API volume. Tokens are never logged.
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

/// How a Windows-volume ramp ended. `last` is the last readback written, so a dead session
/// can be put back only while the slider is still sitting on that write.
enum Ramp {
    Done,
    Moved,
    Failed { last: Option<f32> },
}

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
    /// Web API volume ramp. Cosine ease, and at most one request per 100 ms, so a slow reply skips ahead
    /// on the curve instead of adding a stair and stretching the fade. Spotify rate-limits faster sends.
    fn fade(&mut self, from: i64, to: i64, secs: f32) {
        if secs <= 0.05 || from == to { self.set_volume(to); return; }
        let t0 = Instant::now();
        let mut held = None;
        let mut next = t0;
        loop {
            let t = (t0.elapsed().as_secs_f32() / secs).min(1.0);
            let e = 0.5 - 0.5 * (std::f32::consts::PI * t).cos();
            let v = (from as f32 + (to as f32 - from as f32) * e).round() as i64;
            if Instant::now() >= next && held != Some(v) {
                self.set_volume(v);
                held = Some(v);
                next = Instant::now() + Duration::from_millis(100);
            }
            if t >= 1.0 { break; }
            std::thread::sleep(Duration::from_millis(20));
        }
        if held != Some(to) { self.set_volume(to); }
    }

    /// This PC's Spotify desktop app is the device that is playing. Tests and the fake player never take this path.
    fn local_session(&self, st: &Value) -> Option<crate::appvol::Session> {
        if std::env::var("AOE4S_TEST").ok().as_deref() == Some("1") { return None; }
        let dev = &st["device"];
        if !dev["type"].as_str().unwrap_or("").eq_ignore_ascii_case("computer") { return None; }
        let id = dev["id"].as_str().unwrap_or("");
        let name = dev["name"].as_str().unwrap_or("");
        let here = std::env::var("COMPUTERNAME").unwrap_or_default();
        let ours = !id.is_empty() && self.device.as_deref() == Some(id);
        if !ours && (here.is_empty() || !name.eq_ignore_ascii_case(&here)) { return None; }
        let sess = crate::appvol::find()?;
        sess.get()?;
        Some(sess)
    }

fn near(a: f32, b: f32) -> bool { (a - b).abs() <= 0.02 }

    /// Record the readback, not the commanded level, so a crash still matches `restore_after_crash`.
    fn note_level(sess: &crate::appvol::Session, orig: f32, commanded: f32) -> f32 {
        let back = sess.get().unwrap_or(commanded);
        crate::appvol::guard(Some(orig), Some(back));
        back
    }

    /// Put `orig` back when the live level is still our last write. Leave the guard file if that write does not land.
    fn recover(sess: &crate::appvol::Session, orig: f32, last: Option<f32>) {
        let Some(prev) = last else { return };
        match sess.get() {
            Some(cur) if Self::near(cur, prev) => {
                if !sess.set(orig) { return; }
                match sess.get() {
                    Some(back) if Self::near(back, orig) => crate::appvol::guard(None, None),
                    Some(back) => crate::appvol::guard(Some(orig), Some(back)),
                    None => crate::appvol::guard(Some(orig), Some(orig)),
                }
            }
            Some(_) => crate::appvol::guard(None, None),
            None => {}
        }
    }

    /// Fade back to `orig`. A listener move keeps their level. A dead session is restored in place.
    fn settle(sess: &crate::appvol::Session, orig: f32, secs: f32) {
        match Self::ramp(sess, orig, secs, false) {
            Ramp::Done | Ramp::Moved => crate::appvol::guard(None, None),
            Ramp::Failed { last } => Self::recover(sess, orig, last),
        }
    }

    /// 60 fps dip or return on the Windows app volume.
    fn ramp(sess: &crate::appvol::Session, orig: f32, secs: f32, down: bool) -> Ramp {
        let level = |t: f32| (orig * crate::appvol::fade_gain(if down { t } else { 1.0 - t })).clamp(0.0, 1.0);
        if secs <= 0.05 {
            let v = level(1.0);
            if !sess.set(v) { return Ramp::Failed { last: None }; }
            Self::note_level(sess, orig, v);
            return Ramp::Done;
        }
        let t0 = Instant::now();
        let frame = Duration::from_secs_f64(1.0 / 60.0);
        let mut last: Option<f32> = None;
        loop {
            if let Some(prev) = last {
                match sess.get() {
                    Some(cur) if Self::near(cur, prev) => {}
                    Some(_) => return Ramp::Moved,
                    None => return Ramp::Failed { last: Some(prev) },
                }
            }
            let t = (t0.elapsed().as_secs_f32() / secs).min(1.0);
            let v = level(t);
            if !sess.set(v) { return Ramp::Failed { last }; }
            last = Some(Self::note_level(sess, orig, v));
            if t >= 1.0 { return Ramp::Done; }
            let step = (t0.elapsed().as_secs_f64() / frame.as_secs_f64()).floor() as u32 + 1;
            let wake = t0 + frame * step;
            let now = Instant::now();
            if wake > now { std::thread::sleep(wake - now); }
        }
    }

    /// Hold at the floor until the new music is really playing, so the fade-in is not a swell over silence.
    fn wait_started(&mut self, old: Option<&str>) {
        let t0 = Instant::now();
        while t0.elapsed() < Duration::from_millis(1600) {
            let st = self.state();
            let uri = st["item"]["uri"].as_str();
            let playing = st["is_playing"].as_bool() == Some(true);
            let pos = st["progress_ms"].as_i64().unwrap_or(0);
            if playing && pos > 0 && uri.is_some() && uri != old { return; }
            std::thread::sleep(Duration::from_millis(250));
        }
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
        let half = fade_s / 2.0;
        let old = st["item"]["uri"].as_str().map(|s| s.to_string());
        if playing && fade_s > 0.05 {
            if let Some(sess) = self.local_session(st) {
                if let Some(orig) = sess.get() {
                    crate::appvol::note(&format!("Fade: Windows app volume, {half:.1}s each way"));
                    match Self::ramp(&sess, orig, half, true) {
                        Ramp::Done => {
                            let body = match self.payload(uri) {
                                Ok(b) => b,
                                Err(e) => { Self::settle(&sess, orig, half); return Err(e); }
                            };
                            let r = self.put_play(dev, body);
                            self.wait_started(old.as_deref());
                            Self::settle(&sess, orig, half);
                            return r;
                        }
                        Ramp::Moved => {
                            crate::appvol::guard(None, None);
                            let body = self.payload(uri)?;
                            return self.put_play(dev, body);
                        }
                        Ramp::Failed { last } => {
                            Self::recover(&sess, orig, last);
                            let body = self.payload(uri)?;
                            return self.put_play(dev, body);
                        }
                    }
                }
            }
        }
        if playing { self.fade(cur, low, half) } else { self.set_volume(low) }
        let body = self.payload(uri)?;
        let r = self.put_play(dev, body);
        if playing && fade_s > 0.05 { self.wait_started(old.as_deref()); }
        self.fade(low, base, half);
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
        let playing = st["is_playing"].as_bool() == Some(true);
        if playing && fade_s > 0.05 {
            if let Some(sess) = self.local_session(&st) {
                if let Some(orig) = sess.get() {
                    crate::appvol::note(&format!("Fade: Windows app volume, {fade_s:.1}s out"));
                    let end = Self::ramp(&sess, orig, fade_s, true);
                    let _ = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None);
                    match end {
                        Ramp::Done => {
                            if sess.set(orig) {
                                match sess.get() {
                                    Some(back) if Self::near(back, orig) => crate::appvol::guard(None, None),
                                    Some(back) => crate::appvol::guard(Some(orig), Some(back)),
                                    None => crate::appvol::guard(Some(orig), Some(orig)),
                                }
                            }
                        }
                        Ramp::Moved => crate::appvol::guard(None, None),
                        Ramp::Failed { last } => Self::recover(&sess, orig, last),
                    }
                    return Ok(());
                }
            }
        }
        if playing { self.fade(cur, vol / 5, fade_s); }
        let _ = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None);
        self.set_volume(vol); Ok(())
    }
    /// Match over: fade out, put back what was playing before (or pause), and your volume.
    pub fn restore(&mut self, fade_s: f32) -> Result<String, String> {
        self.restore_user_repeat();
        let Some(prev) = self.saved.take() else { return Ok("nothing to restore".into()) };
        let vol = self.saved_volume.take().unwrap_or(60);
        let dev = self.ensure_device()?;
        let st = self.state();
        let cur = st["device"]["volume_percent"].as_i64().unwrap_or(vol);
        let half = fade_s / 2.0;
        let old = st["item"]["uri"].as_str().map(|s| s.to_string());
        if st["is_playing"].as_bool() == Some(true) && fade_s > 0.05 {
            if let Some(sess) = self.local_session(&st) {
                if let Some(orig) = sess.get() {
                    crate::appvol::note(&format!("Fade: Windows app volume, {half:.1}s each way"));
                    match Self::ramp(&sess, orig, half, true) {
                        Ramp::Done => match self.restore_body(&dev, &prev) {
                            Ok(msg) => {
                                if prev["is_playing"].as_bool() == Some(true) { self.wait_started(old.as_deref()); }
                                Self::settle(&sess, orig, half);
                                return Ok(msg);
                            }
                            Err(e) => {
                                self.saved = Some(prev);
                                self.saved_volume = Some(vol);
                                Self::settle(&sess, orig, half);
                                return Err(e);
                            }
                        },
                        Ramp::Moved => {
                            crate::appvol::guard(None, None);
                            return self.restore_or_keep(&dev, prev, vol);
                        }
                        Ramp::Failed { last } => {
                            Self::recover(&sess, orig, last);
                            return self.restore_or_keep(&dev, prev, vol);
                        }
                    }
                }
            }
        }
        self.fade(cur, vol / 5, half);
        let msg = self.restore_body(&dev, &prev)?;
        if prev["is_playing"].as_bool() == Some(true) && fade_s > 0.05 { self.wait_started(old.as_deref()); }
        self.fade(vol / 5, vol, half);
        Ok(msg)
    }

    /// Put the saved playback back if the restore request fails, so a later close can try again.
    fn restore_or_keep(&mut self, dev: &str, prev: Value, vol: i64) -> Result<String, String> {
        match self.restore_body(dev, &prev) {
            Ok(msg) => Ok(msg),
            Err(e) => { self.saved = Some(prev); self.saved_volume = Some(vol); Err(e) }
        }
    }

    fn restore_body(&mut self, dev: &str, prev: &Value) -> Result<String, String> {
        let item = prev["item"]["uri"].as_str().map(|s| s.to_string());
        if let Some(item) = item {
            let pos = prev["progress_ms"].as_i64().unwrap_or(0);
            let body = match prev["context"]["uri"].as_str() {
                Some(ctx) if ctx.starts_with("spotify:") && !ctx.contains(":collection") => json!({ "context_uri": ctx, "offset": { "uri": item }, "position_ms": pos }),
                _ => json!({ "uris": [item], "position_ms": pos }),
            };
            self.put_play(dev, body)?;
            if prev["is_playing"].as_bool() != Some(true) { let _ = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None); }
            Ok("previous music restored".into())
        } else {
            let _ = self.api("PUT", &format!("/me/player/pause?device_id={dev}"), None);
            Ok("nothing was playing before - paused".into())
        }
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
