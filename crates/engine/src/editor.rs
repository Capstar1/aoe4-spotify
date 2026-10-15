//! Age Intros editor model (Tauri 1.1 ui/age.js, from 1.0.9 intros.py pools/commit/record + settings.py presets),
//! UI independent: every edit takes the current intros.json value `u` and returns the new one; `History` is undo/redo.
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, HashMap};

pub const DEFAULT_PRESET: &str = "Default";

/// Song row as age_data() sends it: [key, name, artist, uri, colour].
#[derive(Clone, Debug, PartialEq)]
pub struct Song { pub key: String, pub name: String, pub artist: String, pub uri: String, pub col: String }

/// What the editor needs from age_data(): factions, built-in songs, default pools, the ages.
#[derive(Clone, Debug, Default)]
pub struct Ctx { pub civs: Vec<(String, String)>, pub builtin: Vec<Song>, pub defs: HashMap<String, Vec<String>>, pub default_age: String, pub ages: Vec<String> }

fn strs(v: &Value) -> Vec<String> { v.as_array().map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect()).unwrap_or_default() }

impl Ctx {
    pub fn from_state(agedata: &Value, ages: &[(String, String)]) -> Ctx {
        let nb = agedata["nb"].as_u64().unwrap_or(0) as usize;
        let songs: Vec<Song> = agedata["songs"].as_array().cloned().unwrap_or_default().iter().take(nb).map(song).collect();
        let civs = agedata["civs"].as_array().cloned().unwrap_or_default().iter().map(|c| (c[0].as_str().unwrap_or("").to_string(), c[1].as_str().unwrap_or("").to_string())).collect();
        let defs = agedata["defs"].as_object().map(|o| o.iter().map(|(k, v)| (k.clone(), strs(v))).collect()).unwrap_or_default();
        Ctx { civs, builtin: songs, defs, default_age: agedata["default_age"].as_str().unwrap_or("").into(), ages: ages.iter().map(|a| a.0.clone()).collect() }
    }
    /// Built-ins then your songs (custom_songs with a track uri).
    pub fn songs_of(&self, u: &Value) -> Vec<Song> {
        let mut v = self.builtin.clone();
        for c in u["custom_songs"].as_array().cloned().unwrap_or_default() {
            let uri = c["uri"].as_str().unwrap_or("");
            if !uri.starts_with("spotify:track:") { continue; }
            v.push(Song { key: format!("c_{}", uri.rsplit(':').next().unwrap_or("")), name: c["name"].as_str().unwrap_or("Song").into(), artist: c["artist"].as_str().unwrap_or("").into(), uri: uri.into(), col: "#1DB954".into() });
        }
        v
    }
    /// Dedupe, then canonical song order (unknown songs last, stable).
    pub fn sorted(&self, u: &Value, l: &[String]) -> Vec<String> {
        let idx: HashMap<String, usize> = self.songs_of(u).into_iter().enumerate().map(|(i, s)| (s.uri, i)).collect();
        let mut d: Vec<String> = vec![]; for x in l { if !d.contains(x) { d.push(x.clone()); } }
        let mut e: Vec<(usize, String)> = d.into_iter().enumerate().collect();
        e.sort_by_key(|(i, x)| (idx.get(x).copied().unwrap_or(usize::MAX), *i));
        e.into_iter().map(|(_, x)| x).collect()
    }
    fn def(&self, c: &str) -> Vec<String> { self.defs.get(c).cloned().unwrap_or_default() }
    /// Lists of one age (the default age falls back to the default pools).
    pub fn pools_of(&self, u: &Value, a: &str) -> BTreeMap<String, Vec<String>> {
        let bp = &u["intro_pools"][a];
        self.civs.iter().map(|(c, _)| {
            let l = if a == self.default_age { if bp.get(c).is_some() { strs(&bp[c]) } else { self.def(c) } } else { strs(&bp[c]) };
            (c.clone(), self.sorted(u, &l))
        }).collect()
    }
    pub fn ages_on(&self, u: &Value) -> BTreeMap<String, bool> {
        self.ages.iter().map(|a| (a.clone(), u["intro_ages"][a].as_bool().unwrap_or(*a == self.default_age))).collect()
    }
    pub fn age_empty(&self, u: &Value, a: &str) -> bool { !self.pools_of(u, a).values().any(|v| !v.is_empty()) }
    /// Default + your presets.
    pub fn presets(&self, u: &Value) -> Vec<Value> {
        let mut v = vec![json!({ "v": 1, "name": DEFAULT_PRESET, "pools": {}, "ages": {}, "custom": [], "builtin": true })];
        for p in u["intro_presets"].as_array().cloned().unwrap_or_default() { if p["name"].as_str().is_some_and(|n| !n.is_empty()) { v.push(p); } }
        v
    }
    /// Comparable form of (pools, ages on) of a preset or of the current edit (p = None).
    pub fn preset_key(&self, u: &Value, p: Option<&Value>) -> String {
        let (pools, ages) = match p { Some(p) => (&p["pools"], &p["ages"]), None => (&u["intro_pools"], &u["intro_ages"]) };
        let mut pk: BTreeMap<String, BTreeMap<String, Vec<String>>> = BTreeMap::new();
        if let Some(o) = pools.as_object() { for (a, d) in o { let mut m = BTreeMap::new();
            if let Some(d) = d.as_object() { for (c, v) in d { let mut l = strs(v); if !l.is_empty() { l.sort(); m.insert(c.clone(), l); } } }
            if !m.is_empty() { pk.insert(a.clone(), m); } } }
        let on: BTreeMap<String, bool> = self.ages.iter().map(|a| (a.clone(), ages[a].as_bool().unwrap_or(*a == self.default_age))).collect();
        json!([pk, on]).to_string()
    }
    pub fn preset_from_user(&self, u: &Value, name: &str) -> Value {
        let pools = if u["intro_pools"].is_object() { u["intro_pools"].clone() } else { json!({}) };
        let mut used: Vec<String> = vec![];
        if let Some(o) = pools.as_object() { for d in o.values() { if let Some(d) = d.as_object() { for v in d.values() { used.extend(strs(v)); } } } }
        let custom: Vec<Value> = u["custom_songs"].as_array().cloned().unwrap_or_default().into_iter().filter(|c| c["uri"].as_str().is_some_and(|x| used.iter().any(|y| y == x)))
            .map(|c| { let mut o = Map::new(); for k in ["uri", "name", "artist"] { if !c[k].is_null() { o.insert(k.into(), c[k].clone()); } } Value::Object(o) }).collect();
        json!({ "v": 1, "name": name.chars().take(40).collect::<String>(), "pools": pools, "ages": if u["intro_ages"].is_object() { u["intro_ages"].clone() } else { json!({}) }, "custom": custom })
    }
    pub fn unique_name(&self, u: &Value, name: &str) -> String {
        let names: Vec<String> = self.presets(u).iter().map(|p| p["name"].as_str().unwrap_or("").to_lowercase()).collect();
        let t: String = name.trim().chars().take(40).collect(); let name = if t.is_empty() { "Preset".to_string() } else { t };
        if !names.contains(&name.to_lowercase()) { return name; }
        let mut n = 2; while names.contains(&format!("{name} ({n})").to_lowercase()) { n += 1; } format!("{name} ({n})")
    }
    /// Keep the current preset in step with the edit; editing Default (built-in) forks a new "Custom" preset (its name is returned).
    pub fn autosave(&self, u: &mut Value) -> Option<String> {
        let n = u["intro_preset"].as_str().unwrap_or(DEFAULT_PRESET).to_string();
        let cur = self.presets(u).into_iter().find(|p| p["name"] == json!(n));
        if let Some(c) = &cur { if self.preset_key(u, Some(c)) == self.preset_key(u, None) { return None; } }
        let ps: Vec<Value> = u["intro_presets"].as_array().cloned().unwrap_or_default().into_iter().filter(|p| p.is_object()).collect();
        if cur.as_ref().is_some_and(|c| c["builtin"] != json!(true)) {
            let me = self.preset_from_user(u, &n);
            u["intro_presets"] = json!(ps.into_iter().map(|p| if p["name"] == json!(n) { me.clone() } else { p }).collect::<Vec<_>>());
            return None;
        }
        let name = self.unique_name(u, if cur.is_some() || n == DEFAULT_PRESET { "Custom" } else { &n });
        let mut ps = ps; ps.push(self.preset_from_user(u, &name));
        u["intro_presets"] = json!(ps); u["intro_preset"] = json!(name); Some(name)
    }
    pub fn apply_preset(&self, u: &mut Value, p: &Value) {
        let o = u.as_object_mut().expect("object");
        if p["pools"].as_object().is_some_and(|m| !m.is_empty()) { o.insert("intro_pools".into(), p["pools"].clone()); } else { o.remove("intro_pools"); }
        if p["ages"].as_object().is_some_and(|m| !m.is_empty()) { o.insert("intro_ages".into(), p["ages"].clone()); } else { o.remove("intro_ages"); }
        let mut cs = o.get("custom_songs").and_then(|v| v.as_array().cloned()).unwrap_or_default();
        for c in p["custom"].as_array().cloned().unwrap_or_default() { if !cs.iter().any(|x| x["uri"] == c["uri"]) { cs.push(c); } }
        if !cs.is_empty() { o.insert("custom_songs".into(), json!(cs)); }
        o.insert("intro_preset".into(), p["name"].as_str().map(|s| json!(s)).unwrap_or(json!(DEFAULT_PRESET)));
    }
    /// Store one age's lists (default age: only differences from the defaults).
    pub fn commit_pools(&self, u: &mut Value, a: &str, p: &BTreeMap<String, Vec<String>>) {
        let mut bp = Map::new();
        for (c, l) in p { let v = self.sorted(u, l);
            if a == self.default_age { if v != self.sorted(u, &self.def(c)) { bp.insert(c.clone(), json!(v)); } } else if !v.is_empty() { bp.insert(c.clone(), json!(v)); } }
        let mut ip = u["intro_pools"].as_object().cloned().unwrap_or_default();
        if bp.is_empty() { ip.remove(a); } else { ip.insert(a.into(), Value::Object(bp)); }
        let o = u.as_object_mut().expect("object");
        if ip.is_empty() { o.remove("intro_pools"); } else { o.insert("intro_pools".into(), Value::Object(ip)); }
    }
    /// An emptied age switches itself off.
    pub fn fix_ages(&self, u: &mut Value) {
        let on = self.ages_on(u);
        for a in &self.ages { if on[a] && self.age_empty(u, a) { set_obj(u, "intro_ages", a, json!(false)); } }
    }
    pub fn remove_custom(&self, u: &mut Value, uri: &str) {
        let cs: Vec<Value> = u["custom_songs"].as_array().cloned().unwrap_or_default().into_iter().filter(|c| c["uri"] != json!(uri)).collect();
        u["custom_songs"] = json!(cs);
        if let Some(ip) = u.get_mut("intro_pools").and_then(|v| v.as_object_mut()) {
            for (a, d) in ip.iter_mut() { if let Some(d) = d.as_object_mut() {
                let keys: Vec<String> = d.keys().cloned().collect();
                for c in keys { let l: Vec<String> = strs(&d[&c]).into_iter().filter(|x| x != uri).collect();
                    if l.is_empty() && *a != self.default_age { d.remove(&c); } else { d.insert(c, json!(l)); } } } }
        }
    }
    /// List of one civ in a preset (missing = default pools on the default age).
    fn preset_list(&self, p: &Value, a: &str, c: &str) -> Vec<String> {
        let dd = &p["pools"][a];
        if dd.get(c).is_some() { strs(&dd[c]) } else if a == self.default_age { self.def(c) } else { vec![] }
    }
    /// Songs a preset uses (canonical order; the menu shows the first three).
    pub fn preset_songs(&self, u: &Value, p: &Value) -> Vec<String> {
        let mut out = vec![]; for a in &self.ages { for (c, _) in &self.civs { out.extend(self.preset_list(p, a, c)); } }
        self.sorted(u, &out)
    }
    /// Civs with a list, per age.
    pub fn preset_counts(&self, p: &Value) -> BTreeMap<String, usize> {
        self.ages.iter().map(|a| (a.clone(), self.civs.iter().filter(|(c, _)| !self.preset_list(p, a, c).is_empty()).count())).collect()
    }
    /// Add songs to YOURS (no duplicates); returns how many were new.
    pub fn add_songs(&self, u: &mut Value, items: &[Value]) -> Vec<Value> {
        let mut have: Vec<String> = self.songs_of(u).into_iter().map(|s| s.uri).collect();
        let mut cs = u["custom_songs"].as_array().cloned().unwrap_or_default(); let mut fresh = vec![];
        for it in items { let uri = it["uri"].as_str().unwrap_or("");
            if !(uri.len() == 36 && uri.starts_with("spotify:track:") && uri[14..].chars().all(|c| c.is_ascii_alphanumeric())) || have.iter().any(|h| h == uri) { continue; }
            have.push(uri.into());
            let c = json!({ "uri": uri, "name": it["name"].as_str().unwrap_or("Song").chars().take(80).collect::<String>(), "artist": it["artist"].as_str().unwrap_or("").chars().take(80).collect::<String>() });
            cs.push(c.clone()); fresh.push(c); }
        if !fresh.is_empty() { u["custom_songs"] = json!(cs); u["intro_pack_open"] = json!(false); }
        fresh
    }
}

fn song(x: &Value) -> Song { let s = |i: usize| x[i].as_str().unwrap_or("").to_string(); Song { key: s(0), name: s(1), artist: s(2), uri: s(3), col: s(4) } }
fn set_obj(u: &mut Value, k: &str, a: &str, v: Value) { let mut m = u[k].as_object().cloned().unwrap_or_default(); m.insert(a.into(), v); u[k] = Value::Object(m); }
pub fn set_age_on(cx: &Ctx, u: &mut Value, a: &str, on: bool) -> bool { if on && cx.age_empty(u, a) { return false; } set_obj(u, "intro_ages", a, json!(on)); true }

/// The part of intros.json undo/redo covers.
pub fn snap(u: &Value) -> Value { json!(["intro_pools", "intro_ages", "custom_songs", "intro_preset", "intro_presets"].iter().map(|k| (k.to_string(), u[*k].clone())).collect::<Map<String, Value>>()) }

/// age.js ED: undo / redo stacks of snapshots (500 deep).
#[derive(Default)]
pub struct History { pub undo: Vec<Value>, pub redo: Vec<Value>, pub cur: Option<Value> }
impl History {
    /// record(): auto-off empty ages, autosave the preset, push undo. Returns (new u, forked preset name).
    pub fn record(&mut self, cx: &Ctx, before: &Value, mut u: Value) -> (Value, Option<String>) {
        if self.cur.is_none() { self.cur = Some(snap(before)); }
        cx.fix_ages(&mut u);
        let np = cx.autosave(&mut u); let sn = snap(&u);
        if Some(&sn) != self.cur.as_ref() { self.undo.push(self.cur.take().unwrap_or(Value::Null)); self.redo.clear(); self.cur = Some(sn);
            let n = self.undo.len(); if n > 500 { self.undo.drain(0..n - 500); } }
        (u, np)
    }
    /// Ctrl+Z (back) / Ctrl+Y. None when there is nothing to do.
    pub fn step(&mut self, cx: &Ctx, now: &Value, back: bool) -> Option<Value> {
        let (src, dst) = if back { (&mut self.undo, &mut self.redo) } else { (&mut self.redo, &mut self.undo) };
        let s = src.pop()?; dst.push(self.cur.take().unwrap_or_else(|| snap(now))); 
        let mut u = now.clone();
        if let (Some(o), Some(m)) = (u.as_object_mut(), s.as_object()) { for (k, v) in m { if v.is_null() { o.remove(k); } else { o.insert(k.clone(), v.clone()); } } }
        if cx.autosave(&mut u).is_some() { self.cur = Some(snap(&u)); } else { self.cur = Some(s); }
        Some(u)
    }
}
