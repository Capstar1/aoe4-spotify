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
