//! Age of Empires IV log adapter (port of games/aoe4.py, M1 subset: lobby, match, ages, replay, end).
use crate::game::{GameAdapter, GameEvent};
use regex::Regex;
use std::collections::HashMap;
use std::path::PathBuf;

/// lobby slot / index among humans -> sim player id (from LogFiles/DataCRC*.txt in the real app).
pub type IdResolver = Box<dyn Fn(i32, Option<usize>) -> Option<i32> + Send>;

pub struct Aoe4 {
    re: Res,
    me_name: Option<String>,
    me_profile: Option<String>,
    humans: Vec<String>,
    first_human: Option<(i32, String)>,
    my_slot: Option<i32>,
    my_civ: Option<String>,
    my_hidx: Option<usize>,
    my_id: Option<i32>,
    in_match: bool,
    replay: bool,
    result: Option<i32>,
    ended: bool,
    ages: HashMap<i32, String>,
    resolver: IdResolver,
}

struct Res { human: Regex, steam: Regex, profile: Regex, begin: Regex, start: Regex, replay: Regex, upstart: Regex, updone: Regex, result: Regex, end: Regex }

const AGES: &[(&str, &str)] = &[("dark", "Dark Age"), ("feudal", "Feudal Age"), ("castle", "Castle Age"), ("imperial", "Imperial Age")];

fn key(age: &str) -> Option<&'static str> {
    match age { "dark_age" => Some("dark"), "feudal_age" => Some("feudal"), "castle_age" => Some("castle"), "imperial_age" => Some("imperial"), _ => None }
}
fn next(age: &str) -> Option<&'static str> {
    match age { "dark_age" => Some("feudal_age"), "feudal_age" => Some("castle_age"), "castle_age" => Some("imperial_age"), _ => None }
}

impl Aoe4 {
    pub fn new(resolver: IdResolver) -> Self {
        let r = |s: &str| Regex::new(s).unwrap();
        Aoe4 {
            re: Res {
                human: r(r"GAME -- Human Player: (\d+) (.+) (\d+) (\d+) (\S+)$"),
                steam: r(r"GAME -- Current Steam name is \[(.*)\]"),
                profile: r(r#"WebSocketConnection::ProcessMessages: message=\[0,"\w+",(\d+),"#),
                begin: r(r"\[Match Flow\] GameApp::RequestGameBegin\(\)"),
                start: r(r"GAME -- Starting mission"),
                replay: r(r"PlaybackSynchronization::"),
                upstart: r(r"Age up started from (\w+) to (\w+) for player id (\d+)"),
                updone: r(r"Age up complete from (\w+) for player id (\d+)"),
                result: r(r"Report sent for profileID\[(\d+)\] -> race=\[\d+\], result=\[(\d+)\]"),
                end: r(r"MOD -- Game Over at frame|GameObj::ShutdownGameObj"),
            },
            me_name: None, me_profile: None, humans: vec![], first_human: None, my_slot: None, my_civ: None,
            my_hidx: None, my_id: None, in_match: false, replay: false, result: None, ended: false, ages: HashMap::new(), resolver,
        }
    }

    /// Real resolver: newest DataCRC*.txt playermap (setupindex -> simid - 1000).
    pub fn datacrc_resolver(dir: PathBuf) -> IdResolver {
        Box::new(move |slot, hidx| {
            let newest = std::fs::read_dir(&dir).ok()?.filter_map(|e| e.ok())
                .filter(|e| { let n = e.file_name().to_string_lossy().to_string(); n.starts_with("DataCRC") && n.ends_with(".txt") })
                .max_by_key(|e| e.metadata().and_then(|m| m.modified()).ok())?;
            let map = playermap(&std::fs::read_to_string(newest.path()).ok()?);
            pick_id(&map, slot, hidx)
        })
    }

    fn reset_match(&mut self) {
        self.humans.clear(); self.first_human = None; self.my_slot = None; self.my_civ = None; self.my_hidx = None;
        self.my_id = None; self.in_match = false; self.replay = false; self.result = None; self.ended = false; self.ages.clear();
    }

    fn is_player(&mut self, out: &mut Vec<GameEvent>) -> bool {
        if self.my_slot.is_some() { return true; }
        if self.humans.len() == 1 && self.me_profile.is_none() {
            if let Some((sl, civ)) = self.first_human.clone() {
                self.my_slot = Some(sl); self.my_civ = Some(civ.clone()); self.my_hidx = Some(0);
                out.push(GameEvent::Lobby { slot: sl, civ });
                return true;
            }
        }
        false
    }

    fn age_event(&mut self, pid: i32, new: &str, reason: &str, out: &mut Vec<GameEvent>) {
        if self.my_id.is_none() { if let Some(sl) = self.my_slot { self.my_id = (self.resolver)(sl, self.my_hidx); } }
        if Some(pid) != self.my_id { return; }
        if self.ages.get(&pid).map(|s| s.as_str()) == Some(new) { return; }
        self.ages.insert(pid, new.to_string());
        if let Some(k) = key(new) { out.push(GameEvent::Age { key: k.into(), reason: reason.into() }); }
    }
}

pub fn playermap(text: &str) -> HashMap<i32, i32> {
    let mut out = HashMap::new();
    let Some(i) = text.find("playermap:") else { return out };
    let blk = &text[i..]; let end = blk.find('}').unwrap_or(blk.len()); let blk = &blk[..end];
    let re = Regex::new(r"(setupindex|simid)\s*:\s*\[\s*(-?\d+)\s*\]").unwrap();
    let mut cur = None;
    for c in re.captures_iter(blk) {
        let v: i32 = c[2].parse().unwrap_or(0);
        if &c[1] == "setupindex" { cur = Some(v) } else if let Some(k) = cur.take() { out.insert(k, v - 1000); }
    }
    out
}

pub fn pick_id(map: &HashMap<i32, i32>, slot: i32, hidx: Option<usize>) -> Option<i32> {
    if let Some(h) = hidx { if let Some(v) = map.get(&(h as i32)) { return Some(*v); } }
    if let Some(v) = map.get(&slot) { return Some(*v); }
    if map.len() == 1 { return map.values().next().copied(); }
    None
}

impl GameAdapter for Aoe4 {
    fn id(&self) -> &'static str { "aoe4" }
    fn label(&self) -> &'static str { "Age of Empires IV" }
    fn process_names(&self) -> &'static [&'static str] { &["RelicCardinal.exe"] }
    fn default_log_path(&self) -> Option<PathBuf> {
        std::env::var_os("USERPROFILE").map(|h| PathBuf::from(h).join(r"Documents\My Games\Age of Empires IV\warnings.log"))
    }
    fn ages(&self) -> &'static [(&'static str, &'static str)] { AGES }
    fn reset_session(&mut self) { self.reset_match(); }

    fn feed(&mut self, line: &str) -> Vec<GameEvent> {
        let mut out = vec![];
        let line = line.trim_end_matches(['\r', '\n']);
        if let Some(c) = self.re.steam.captures(line) { self.me_name = Some(c[1].to_string()); self.me_profile = None; }
        if self.me_profile.is_none() { if let Some(c) = self.re.profile.captures(line) { self.me_profile = Some(c[1].to_string()); } }
        if let Some(c) = self.re.result.captures(line) {
            if Some(&c[1]) == self.me_profile.as_deref() {
                self.result = c[2].parse().ok();
                if self.ended && !self.replay { if let Some(r @ (0 | 1)) = self.result { out.push(GameEvent::MatchResult { result: r }); self.ended = false; } }
            }
            return out;
        }
        if self.re.begin.is_match(line) { self.reset_match(); return out; }
        if let Some(c) = self.re.human.captures(line) {
            let prof = c[3].to_string();
            if !self.humans.contains(&prof) {
                self.humans.push(prof.clone());
                if self.humans.len() == 1 { self.first_human = Some((c[1].parse().unwrap_or(0), c[5].to_string())); }
            }
            let mine = Some(&prof) == self.me_profile.as_ref() || (self.me_profile.is_none() && Some(&c[2]) == self.me_name.as_deref());
            if mine {
                let slot: i32 = c[1].parse().unwrap_or(0);
                self.my_slot = Some(slot); self.my_civ = Some(c[5].to_string());
                self.my_hidx = self.humans.iter().position(|h| *h == prof);
                if self.me_profile.is_none() && prof != "0" { self.me_profile = Some(prof); }
                out.push(GameEvent::Lobby { slot, civ: c[5].to_string() });
            }
            return out;
        }
        if self.re.replay.is_match(line) && self.in_match {
            if !self.replay { self.replay = true; out.push(GameEvent::Replay); }
            return out;
        }
        if self.re.start.is_match(line) {
            if self.in_match || self.replay { return out; }
            if !self.is_player(&mut out) { self.replay = true; return out; }
            self.in_match = true;
            if let Some(sl) = self.my_slot { self.my_id = (self.resolver)(sl, self.my_hidx); }
            if let Some(id) = self.my_id { self.ages.insert(id, "dark_age".into()); }
            out.push(GameEvent::MatchStart { civ: self.my_civ.clone() });
            out.push(GameEvent::Age { key: "dark".into(), reason: "start".into() });
            return out;
        }
        if self.re.end.is_match(line) && self.in_match {
            self.in_match = false; self.ended = self.result.is_none();
            out.push(GameEvent::MatchEnd { result: self.result });
            return out;
        }
        if let Some(c) = self.re.upstart.captures(line) {
            if self.in_match && !self.replay {
                let pid: i32 = c[3].parse().unwrap_or(-1); let new = c[2].to_string();
                self.age_event(pid, &new, "up_start", &mut out);
            }
            return out;
        }
        if let Some(c) = self.re.updone.captures(line) {
            if self.in_match && !self.replay {
                let pid: i32 = c[2].parse().unwrap_or(-1);
                if let Some(new) = next(&c[1]) { self.age_event(pid, new, "up_done", &mut out); }
            }
        }
        out
    }
}