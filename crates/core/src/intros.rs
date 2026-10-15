//! Age Intros overview data, same rules as 1.0.9 intros.py pools(): the default age (Imperial) = install
//! default pools with your per-civ changes on top; the other ages hold only what you added.
use crate::settings::Settings;
use serde_json::{json, Value};

pub const CATALOG: &str = include_str!("../aoe4_catalog.json");
pub const DEFAULT_AGE: &str = "imperial";

pub fn overview(s: &Settings, ages: &[String]) -> Value {
    let cat: Value = serde_json::from_str(CATALOG).unwrap_or_default();
    let civs: Vec<String> = cat["factions"].as_array().cloned().unwrap_or_default().iter().filter_map(|f| f[0].as_str().map(String::from)).collect();
    let songs: Vec<(String, String, String)> = cat["songs"].as_array().cloned().unwrap_or_default().iter()
        .map(|x| (x[0].as_str().unwrap_or("").into(), x[3].as_str().unwrap_or("").into(), x[4].as_str().unwrap_or("#3a3a3a").into())).collect();
    let strs = |v: &Value| -> Vec<String> { v.as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default() };
    let def_pool = |civ: &str| { let p = &s.base_boss["pools"][civ]; let l = strs(p); if l.is_empty() { strs(&s.base_boss["default"]) } else { l } };
    let mut out = serde_json::Map::new();
    for a in ages {
        let bp = &s.user_pools[a.as_str()];
        let mut n = 0; let mut used: Vec<String> = vec![];
        for c in &civs {
            let l = if a == DEFAULT_AGE { if bp.get(c).is_some() { strs(&bp[c]) } else { def_pool(c) } } else { strs(&bp[c]) };
            if !l.is_empty() { n += 1; }
            for u in l { if !used.contains(&u) { used.push(u); } }
        }
        // canonical chip order = song list order; only known songs get chips
        let mut chips: Vec<(String, String)> = songs.iter().filter(|(_, uri, _)| used.contains(uri)).map(|(k, _, col)| (k.clone(), col.clone())).collect();
        let total = chips.len(); chips.truncate(5);
        let on = s.intro_ages.get(a.as_str()).copied().unwrap_or(a == DEFAULT_AGE) && n > 0;
        out.insert(a.clone(), json!({ "n": n, "civs": civs.len(), "on": on, "chips": chips, "more": total.saturating_sub(5) }));
    }
    Value::Object(out)
}

/// Everything the age pages draw (1.0.9 intros.py): factions, songs (built-ins then your songs, canonical order),
/// each age's pools (default age = install defaults with your changes on top), install default pools.
pub fn age_data(s: &Settings, ages: &[String]) -> Value {
    let cat: Value = serde_json::from_str(CATALOG).unwrap_or_default();
    let civs: Vec<Value> = cat["factions"].as_array().cloned().unwrap_or_default();
    let mut songs: Vec<Value> = cat["songs"].as_array().cloned().unwrap_or_default();
    let nb = songs.len();
    for c in s.custom_songs.as_array().cloned().unwrap_or_default() {
        let uri = c["uri"].as_str().unwrap_or("");
        if !uri.starts_with("spotify:track:") { continue; }
        let key = format!("c_{}", uri.rsplit(':').next().unwrap_or(""));
        songs.push(json!([key, c["name"].as_str().unwrap_or("Song"), c["artist"].as_str().unwrap_or(""), uri, "#1DB954"]));
    }
    let idx: std::collections::HashMap<String, usize> = songs.iter().enumerate().map(|(i, x)| (x[3].as_str().unwrap_or("").to_string(), i)).collect();
    let sorted = |v: &Value| -> Vec<String> {
        let mut l: Vec<String> = vec![];
        for x in v.as_array().cloned().unwrap_or_default() { if let Some(u) = x.as_str() { if !l.iter().any(|y| y == u) { l.push(u.into()); } } }
        let pos: Vec<String> = l.clone();
        l.sort_by_key(|u| (idx.get(u).copied().unwrap_or(idx.len()), pos.iter().position(|y| y == u).unwrap_or(0))); l
    };
    let def_pool = |civ: &str| { let p = &s.base_boss["pools"][civ]; if p.as_array().map_or(true, |a| a.is_empty()) { sorted(&s.base_boss["default"]) } else { sorted(p) } };
    let mut pools = serde_json::Map::new(); let mut custom = serde_json::Map::new(); let mut defs = serde_json::Map::new();
    for c in &civs { let k = c[0].as_str().unwrap_or(""); defs.insert(k.into(), json!(def_pool(k))); }
    for a in ages {
        let bp = &s.user_pools[a.as_str()]; let mut m = serde_json::Map::new();
        for c in &civs {
            let k = c[0].as_str().unwrap_or("");
            let l = if a == DEFAULT_AGE && bp.get(k).is_none() { def_pool(k) } else { sorted(&bp[k]) };
            m.insert(k.into(), json!(l));
        }
        pools.insert(a.clone(), Value::Object(m));
        custom.insert(a.clone(), json!(bp.as_object().map_or(false, |o| !o.is_empty())));
    }
    json!({ "civs": civs, "songs": songs, "nb": nb, "pools": pools, "defs": defs, "custom": custom, "default_age": DEFAULT_AGE })
}

fn track_list(v: &Value) -> Vec<String> {
    v.as_array().map(|a| a.iter().filter_map(|x| x.as_str()).filter(|u| u.starts_with("spotify:track:")).map(String::from).collect()).unwrap_or_default()
}

/// Intro track for this age and civ, or None when intros are off or that civ has no songs.
/// `n` picks among the pool. The previous uri is skipped when another song is available.
pub fn intro_track(s: &Settings, age: &str, civ: &str, last: Option<&str>, n: u64) -> Option<String> {
    if civ.is_empty() || !s.boss_on { return None; }
    if !s.intro_ages.get(age).copied().unwrap_or(age == DEFAULT_AGE) { return None; }
    let mine = track_list(&s.user_pools[age][civ]);
    let pool = if !mine.is_empty() {
        mine
    } else if age == DEFAULT_AGE {
        let p = track_list(&s.base_boss["pools"][civ]);
        if !p.is_empty() { p } else { track_list(&s.base_boss["default"]) }
    } else {
        Vec::new()
    };
    if pool.is_empty() { return None; }
    let alt: Vec<&String> = pool.iter().filter(|u| last != Some(u.as_str())).collect();
    let pick = if alt.is_empty() { pool.iter().collect::<Vec<_>>() } else { alt };
    Some(pick[(n as usize) % pick.len()].clone())
}