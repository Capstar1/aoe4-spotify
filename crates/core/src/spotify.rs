//! Spotify Web API client for 1.1: PKCE login with its OWN token file (separate from 1.0.9), playback,
//! volume fades through the API, and putting your previous music back after the match. Tokens are never logged.
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

pub struct Spotify {
    cid: String,
    path: PathBuf,
    tok: Option<Token>,
    agent: ureq::Agent,
    device: Option<String>,
    /// what was playing before the first switch of this match (null = nothing)
    saved: Option<Value>,
    saved_volume: Option<i64>,
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
    pub fn new(cid: String, path: PathBuf) -> Self {
        let tok = std::fs::read_to_string(&path).ok().and_then(|s| serde_json::from_str(&s).ok());
        let agent = ureq::AgentBuilder::new().timeout(Duration::from_secs(10)).build();
        Spotify { cid, path, tok, agent, device: None, saved: None, saved_volume: None }
    }
    pub fn logged_in(&self) -> bool { self.tok.is_some() }
    pub fn has_client(&self) -> bool { !self.cid.is_empty() }

    fn save(&self) {
        if let (Some(t), Some(dir)) = (&self.tok, self.path.parent()) {
            let _ = std::fs::create_dir_all(dir);
            let tmp = self.path.with_extension("tmp");
            if std::fs::write(&tmp, serde_json::to_vec(t).unwrap_or_default()).is_ok() { let _ = std::fs::rename(&tmp, &self.path); }
        }
    }

    fn token_req(&mut self, form: &[(&str, &str)]) -> Result<(), String> {
        let r = self.agent.post("https://accounts.spotify.com/api/token").send_form(form);
        let v: Value = match r {
            Ok(r) => r.into_json().map_err(|e| e.to_string())?,
            Err(ureq::Error::Status(c, _)) => { if c == 400 { self.tok = None; let _ = std::fs::remove_file(&self.path); } return Err(format!("Spotify login refused ({c}) - log in again")); }
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
    pub fn login(&mut self) -> Result<(), String> {
        if self.cid.is_empty() { return Err("No Spotify client id in the 1.0.9 install config".into()); }
        let verifier = rand_str(48); let state = rand_str(12);
        let listener = TcpListener::bind("127.0.0.1:8888").map_err(|_| "Port 8888 is busy (is a 1.0.9 login window open?)".to_string())?;
        let url = format!("https://accounts.spotify.com/authorize?client_id={}&response_type=code&redirect_uri={}&code_challenge_method=S256&code_challenge={}&scope={}&state={}",
            enc(&self.cid), enc(REDIRECT), challenge(&verifier), enc(SCOPES), state);
        { use std::os::windows::process::CommandExt; std::process::Command::new("rundll32").args(["url.dll,FileProtocolHandler", &url]).creation_flags(0x0800_0000).spawn() }.map_err(|e| e.to_string())?;
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
                    let body = if ok { "AoE4 Spotify 1.1: logged in. You can close this tab." } else { "AoE4 Spotify 1.1: login was cancelled." };
                    let _ = s.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\n\r\n{}", body.len(), body).as_bytes());
                    if !ok { return Err("Login cancelled".into()); }
                    break query(q, "code").unwrap();
                }
                Err(_) => std::thread::sleep(Duration::from_millis(100)),
            }
        };
        let cid = self.cid.clone();
        self.token_req(&[("grant_type", "authorization_code"), ("code", &code), ("redirect_uri", REDIRECT), ("client_id", &cid), ("code_verifier", &verifier)])
    }

    pub fn logout(&mut self) { self.tok = None; let _ = std::fs::remove_file(&self.path); }

    fn api(&mut self, method: &str, path: &str, body: Option<Value>) -> Result<(u16, Value), String> {
        let tok = self.access()?;
        let req = self.agent.request(method, &format!("https://api.spotify.com/v1{path}")).set("Authorization", &format!("Bearer {tok}"));
        let r = match body { Some(b) => req.send_json(b), None if method != "GET" => req.set("Content-Length", "0").call(), None => req.call() };
        let parse = |r: ureq::Response| { let c = r.status(); let t = r.into_string().unwrap_or_default(); (c, serde_json::from_str(&t).unwrap_or(Value::Null)) };
        match r { Ok(r) => Ok(parse(r)), Err(ureq::Error::Status(_, r)) => Ok(parse(r)), Err(e) => Err(format!("Spotify unreachable: {e}")) }
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
        let _ = self.api("PUT", &format!("/me/player/volume?volume_percent={}{q}", v.clamp(0, 100)), None);
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
        if uri.starts_with("spotify:track:") { return Ok(json!({ "uris": [uri] })); }
        if uri.starts_with("spotify:") { return Ok(json!({ "context_uri": uri })); }
        Err(format!("{uri}: app-only lists come in M3"))
    }

    fn put_play(&mut self, dev: &str, body: Value) -> Result<(), String> {
        let (c, v) = self.api("PUT", &format!("/me/player/play?device_id={dev}"), Some(body))?;
        if (200..300).contains(&c) { Ok(()) } else { Err(format!("Spotify play failed ({c}): {}", v["error"]["message"].as_str().unwrap_or(""))) }
    }

    /// Age switch: fade down, start the age's music, fade back up to your volume.
    pub fn play_age(&mut self, uri: &str, fade_s: f32) -> Result<(), String> {
        let dev = self.ensure_device()?;
        let st = self.state();
        if self.saved.is_none() { self.saved = Some(st.clone()); self.saved_volume = st["device"]["volume_percent"].as_i64(); }
        let base = self.saved_volume.unwrap_or(60);
        let cur = st["device"]["volume_percent"].as_i64().unwrap_or(base);
        let playing = st["is_playing"].as_bool() == Some(true);
        let low = base / 5;
        if playing { self.fade(cur, low, fade_s / 2.0) } else { self.set_volume(low) }
        let body = self.payload(uri)?;
        let r = self.put_play(&dev, body);
        self.fade(low, base, fade_s / 2.0);
        r
    }

    /// Match over: fade out, put back what was playing before (or pause), and your volume.
    pub fn restore(&mut self, fade_s: f32) -> Result<String, String> {
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
}
