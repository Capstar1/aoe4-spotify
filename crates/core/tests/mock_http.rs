//! Spotify client against a local mock server: call sequence, retries, 429 Retry-After, token refresh, invalid_grant.
use aoe4core::spotify::Spotify;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::sync::{Arc, Mutex};

type Handler = Box<dyn Fn(&str, &str, &str) -> (u16, String, String) + Send + Sync>;
struct Mock { base: String, log: Arc<Mutex<Vec<String>>> }

fn mock(h: Handler) -> Mock {
    let l = TcpListener::bind("127.0.0.1:0").unwrap(); let base = format!("http://{}", l.local_addr().unwrap());
    let log = Arc::new(Mutex::new(vec![])); let lg = log.clone();
    std::thread::spawn(move || for s in l.incoming() {
        let Ok(mut s) = s else { continue };
        let mut r = BufReader::new(s.try_clone().unwrap()); let mut first = String::new(); r.read_line(&mut first).unwrap();
        let (mut len, mut line) = (0usize, String::new());
        loop { line.clear(); r.read_line(&mut line).unwrap(); if line.trim().is_empty() { break; }
            if let Some(v) = line.to_ascii_lowercase().strip_prefix("content-length:") { len = v.trim().parse().unwrap_or(0); } }
        let mut body = vec![0u8; len]; r.read_exact(&mut body).unwrap();
        let mut p = first.split_whitespace(); let (m, path) = (p.next().unwrap_or("").to_string(), p.next().unwrap_or("").to_string());
        lg.lock().unwrap().push(format!("{m} {path}"));
        let (c, hd, b) = h(&m, &path, &String::from_utf8_lossy(&body));
        let _ = s.write_all(format!("HTTP/1.1 {c} X\r\nContent-Type: application/json\r\nConnection: close\r\n{hd}Content-Length: {}\r\n\r\n{b}", b.len()).as_bytes());
    });
    Mock { base, log }
}
fn tmp(name: &str, expires_at: u64) -> std::path::PathBuf {
    let d = std::env::temp_dir().join(format!("aoe4s-test-{name}-{}", std::process::id())); let _ = std::fs::create_dir_all(&d);
    let p = d.join("token.json"); std::fs::write(&p, format!(r#"{{"access_token":"a","refresh_token":"r","expires_at":{expires_at}}}"#)).unwrap(); p
}
const FAR: u64 = 9_999_999_999;
fn ok(b: &str) -> (u16, String, String) { (200, String::new(), b.to_string()) }
fn player(path: &str, playing: bool) -> Option<(u16, String, String)> {
    if path.starts_with("/me/player/devices") { return Some(ok(r#"{"devices":[{"id":"D1","is_active":true,"type":"Computer"}]}"#)); }
    if path == "/me/player" { return Some(ok(&format!(r#"{{"is_playing":{playing},"progress_ms":5000,"device":{{"volume_percent":50}},"item":{{"uri":"spotify:track:old"}},"context":{{"uri":"spotify:playlist:pre"}}}}"#))); }
    if path.starts_with("/me/player/") { return Some((204, String::new(), String::new())); }
    None
}
fn calls(m: &Mock) -> Vec<String> { m.log.lock().unwrap().clone() }

#[test]
fn play_age_sequence() {
    let m = mock(Box::new(|_, p, _| player(p, true).unwrap_or((404, String::new(), "{}".into()))));
    let mut sp = Spotify::with_base("cid".into(), tmp("seq", FAR), &m.base, &m.base);
    sp.play_age("spotify:playlist:x", 0.0).unwrap();
    let c = calls(&m);
    assert_eq!(c[0], "GET /me/player/devices"); assert_eq!(c[1], "GET /me/player");
    assert_eq!(c[2], "PUT /me/player/volume?volume_percent=10&device_id=D1");
    assert_eq!(c[3], "PUT /me/player/play?device_id=D1");
    assert_eq!(c[4], "PUT /me/player/volume?volume_percent=50&device_id=D1");
    assert_eq!(c.len(), 5);
}

#[test]
fn restore_puts_back_previous_music() {
    let m = mock(Box::new(|_, p, _| player(p, true).unwrap()));
    let mut sp = Spotify::with_base("cid".into(), tmp("restore", FAR), &m.base, &m.base);
    sp.play_age("spotify:playlist:x", 0.0).unwrap();
    assert_eq!(sp.restore(0.0).unwrap(), "previous music restored");
    assert_eq!(sp.restore(0.0).unwrap(), "nothing to restore");
    let plays = calls(&m).iter().filter(|c| c.starts_with("PUT /me/player/play")).count(); assert_eq!(plays, 2);
}

#[test]
fn retries_429_with_retry_after() {
    let n = Arc::new(Mutex::new(0)); let n2 = n.clone();
    let m = mock(Box::new(move |_, p, _| {
        if p == "/me/player/devices" { let mut k = n2.lock().unwrap(); *k += 1; if *k == 1 { return (429, "Retry-After: 0\r\n".into(), "{}".into()); } }
        player(p, false).unwrap()
    }));
    let mut sp = Spotify::with_base("cid".into(), tmp("429", FAR), &m.base, &m.base);
    sp.pause().unwrap();
    assert_eq!(*n.lock().unwrap(), 2);
}

#[test]
fn retries_5xx_then_gives_up() {
    let m = mock(Box::new(|_, p, _| if p == "/me/player/devices" { (503, String::new(), "{}".into()) } else { player(p, false).unwrap() }));
    let mut sp = Spotify::with_base("cid".into(), tmp("5xx", FAR), &m.base, &m.base);
    assert!(sp.pause().is_err());
    assert_eq!(calls(&m).iter().filter(|c| *c == "GET /me/player/devices").count(), 3);
}

#[test]
fn refreshes_expired_token() {
    let m = mock(Box::new(|_, p, b| if p == "/api/token" { assert!(b.contains("grant_type=refresh_token")); ok(r#"{"access_token":"new","expires_in":3600}"#) } else { player(p, false).unwrap() }));
    let path = tmp("refresh", 0);
    let mut sp = Spotify::with_base("cid".into(), path.clone(), &m.base, &m.base);
    sp.pause().unwrap();
    assert_eq!(calls(&m)[0], "POST /api/token");
    let saved = std::fs::read_to_string(&path).unwrap(); assert!(saved.contains("\"new\"") && saved.contains("\"r\""));   // refresh token kept
}

#[test]
fn only_invalid_grant_logs_out() {
    let m = mock(Box::new(|_, _, _| (400, String::new(), r#"{"error":"invalid_request"}"#.into())));
    let path = tmp("badreq", 0);
    let mut sp = Spotify::with_base("cid".into(), path.clone(), &m.base, &m.base);
    assert!(sp.pause().is_err()); assert!(sp.logged_in() && path.exists());
    let m = mock(Box::new(|_, _, _| (400, String::new(), r#"{"error":"invalid_grant"}"#.into())));
    let mut sp = Spotify::with_base("cid".into(), path.clone(), &m.base, &m.base);
    assert!(sp.pause().is_err()); assert!(!sp.logged_in() && !path.exists());
}

#[test]
fn web_reads_without_spotify() {
    let m = mock(Box::new(|_, _, _| ok(r#"{"id":"me"}"#)));
    let mut sp = Spotify::with_base("cid".into(), tmp("web", FAR), &m.base, &m.base);
    let w = sp.web().unwrap(); drop(sp);
    assert_eq!(w.get("/me").unwrap().1["id"], "me");
}
