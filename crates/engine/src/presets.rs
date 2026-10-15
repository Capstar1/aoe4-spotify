//! Age Intros edits (intros.json) and 1.0.9 share codes.
use crate::{Engine, data::ED_KEYS};
use std::sync::atomic::Ordering;

pub fn save_ed(app: &Engine, u: serde_json::Value) {
    let mut m = serde_json::Map::new(); for k in ED_KEYS { if !u[k].is_null() { m.insert(k.into(), u[k].clone()); } }
    let v = serde_json::Value::Object(m); let _ = std::fs::create_dir_all(&app.dir);
    let _ = std::fs::write(app.dir.join("intros.json"), serde_json::to_string_pretty(&v).unwrap_or_default()); *app.ed.lock().unwrap() = v; app.ver.fetch_add(1, Ordering::SeqCst);
}
/// 1.0.9 share codes: "AOE4S1:" + urlsafe base64 (no padding) of zlib(json {v,name,pools,ages,custom}).
pub fn encode_preset(p: serde_json::Value) -> String {
    use std::io::Write; use base64::Engine;
    let d = serde_json::json!({ "v": 1, "name": p["name"], "pools": p["pools"], "ages": p["ages"], "custom": p["custom"] });
    let mut z = flate2::write::ZlibEncoder::new(Vec::new(), flate2::Compression::best()); let _ = z.write_all(d.to_string().as_bytes());
    format!("AOE4S1:{}", base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(z.finish().unwrap_or_default()))
}
pub fn decode_preset(app: &Engine, code: String) -> Result<serde_json::Value, String> {
    use std::io::Read; use base64::Engine; use serde_json::{json, Value};
    let code: String = code.chars().filter(|c| !c.is_whitespace()).collect();
    let Some(rest) = code.strip_prefix("AOE4S") else { return Err("Not an AoE4 Spotify code".into()) };
    let (ver, b) = rest.split_once(':').ok_or("Not an AoE4 Spotify code")?;
    if ver != "1" { return Err("Made with a newer version - update AoE4 Spotify".into()); }
    if b.len() > 1 << 18 { return Err("Code is too big".into()); }
    let raw = base64::engine::general_purpose::URL_SAFE_NO_PAD.decode(b.trim_end_matches('=')).map_err(|_| "Code is incomplete or damaged")?;
    let mut out = Vec::new(); flate2::read::ZlibDecoder::new(&raw[..]).take((1 << 18) + 1).read_to_end(&mut out).map_err(|_| "Code is incomplete or damaged")?;
    if out.len() > 1 << 18 { return Err("Code is too big".into()); }
    let d: Value = serde_json::from_slice(&out).map_err(|_| "Code is incomplete or damaged")?;
    if d["v"] != json!(1) { return Err("Made with a newer version - update AoE4 Spotify".into()); }
    let track = |s: &str| s.len() == 36 && s.starts_with("spotify:track:") && s[14..].chars().all(|c| c.is_ascii_alphanumeric());
    let cat: Value = serde_json::from_str(aoe4core::intros::CATALOG).unwrap_or_default();
    let civs: Vec<String> = cat["factions"].as_array().cloned().unwrap_or_default().iter().filter_map(|f| f[0].as_str().map(String::from)).collect();
    let ages: Vec<String> = app.ages.iter().map(|a| a.0.clone()).collect();
    let mut pools = serde_json::Map::new(); let mut used: Vec<String> = vec![];
    if let Some(o) = d["pools"].as_object() { for (a, dd) in o { if !ages.contains(a) { continue; } let mut m = serde_json::Map::new();
        if let Some(dd) = dd.as_object() { for (c, v) in dd { if !civs.contains(c) { continue; } let mut l: Vec<String> = vec![];
            for x in v.as_array().cloned().unwrap_or_default() { if let Some(x) = x.as_str() { if track(x) && !l.iter().any(|y| y == x) && l.len() < 12 { l.push(x.into()); } } }
            if !l.is_empty() { used.extend(l.clone()); m.insert(c.clone(), json!(l)); } } }
        if !m.is_empty() { pools.insert(a.clone(), Value::Object(m)); } } }
    let mut ag = serde_json::Map::new(); if let Some(o) = d["ages"].as_object() { for (a, v) in o { if ages.contains(a) && v.is_boolean() { ag.insert(a.clone(), v.clone()); } } }
    let mut custom = vec![]; let mut known: Vec<String> = cat["songs"].as_array().cloned().unwrap_or_default().iter().filter_map(|s| s[3].as_str().map(String::from)).collect();
    for c in d["custom"].as_array().cloned().unwrap_or_default() { if let Some(u) = c["uri"].as_str() { if track(u) && used.iter().any(|x| x == u) {
        let n: String = c["name"].as_str().unwrap_or("Song").chars().take(80).collect(); let ar: String = c["artist"].as_str().unwrap_or("").chars().take(80).collect();
        custom.push(json!({ "uri": u, "name": n, "artist": ar })); known.push(u.into()); } } }
    if used.iter().any(|u| !known.contains(u)) { return Err("Code uses songs it doesn't include".into()); }
    if d.get("pools").is_none() && d.get("ages").is_none() { return Err("Code has no intro lists".into()); }
    let name: String = d["name"].as_str().unwrap_or("Shared").trim().chars().take(40).collect();
    Ok(json!({ "v": 1, "name": if name.is_empty() { "Shared".to_string() } else { name }, "pools": pools, "ages": ag, "custom": custom }))
}

