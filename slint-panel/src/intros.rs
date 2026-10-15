//! Age Intros overview + age editor controller (Tauri 1.1 ui/age.js / drawIntros): engine editor model in, IntroUi out.
use crate::{assets, view, Chip, CivRow, ImpAge, IntroUi, OvAge, Panel, PresetRow, RowChip, TrayChip};
use aoe4engine::{editor::{snap, Ctx, History, Song, DEFAULT_PRESET}, guides::{self, Shell, Win}, picker, presets, Engine};
use serde_json::{json, Value};
use slint::{Color, ComponentHandle, Image, ModelRc, SharedString, Timer, TimerMode, VecModel};
use std::{cell::RefCell, sync::Arc, time::{Duration, Instant}};

const ROMAN: [&str; 8] = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"];
const LT: f32 = 178.0; const RH: f32 = 40.0; const STEP: f32 = 44.0; const IW: f32 = 520.0;

#[derive(Clone)]
struct Press { kind: String, i: usize, j: usize, x: f32, y: f32, song: Song }

struct Ed {
    eng: Arc<Engine>, shell: Arc<dyn Shell>, ui: slint::Weak<Panel>,
    h: History, k: Option<String>, sc: f32,
    press: Option<Press>, drag: bool, drop: Option<usize>,
    song: Option<String>, busy: bool, glow_t0: Instant,
    pdel: Option<(String, Instant)>, imp: Option<Value>, ctx_idx: usize,
    toast_t: Option<Instant>, hint_t: Option<Instant>,
    strips: [Vec<Image>; 4],
}
thread_local! { static ED: RefCell<Option<Ed>> = const { RefCell::new(None) }; static TIMER: RefCell<Option<Timer>> = const { RefCell::new(None) }; }

fn with<R>(f: impl FnOnce(&mut Ed) -> R) -> Option<R> { ED.with(|e| e.borrow_mut().as_mut().map(f)) }
fn model<T: Clone + 'static>(v: Vec<T>) -> ModelRc<T> { ModelRc::new(VecModel::from(v)) }
fn col(s: &str) -> Color { let h = s.trim_start_matches('#'); let p = |i: usize| u8::from_str_radix(h.get(i..i + 2).unwrap_or("3a"), 16).unwrap_or(58); Color::from_rgb_u8(p(0), p(2), p(4)) }
fn state(e: &Engine) -> Value { e.static_state().1 }
fn ages(s: &Value) -> Vec<(String, String)> { s["ages"].as_array().cloned().unwrap_or_default().iter().map(|a| (a[0].as_str().unwrap_or("").into(), a[1].as_str().unwrap_or("").into())).collect() }
fn ctx(s: &Value) -> Ctx { Ctx::from_state(&s["agedata"], &ages(s)) }
fn ed_of(s: &Value) -> Value { if s["ed"].is_object() { s["ed"].clone() } else { json!({}) } }
/// Chip picture at `d` logical px: Octopath portrait, or your song's cached cover (grey until it is cached).
fn chip_img(e: &Engine, sg: &Song, d: f32) -> Image {
    if !sg.key.starts_with("c_") { return assets::portrait(&sg.key, d); }
    view::cover_path(&e.dir, &sg.uri).and_then(|p| assets::file(&p, d)).unwrap_or_default()
}
fn chip(e: &Engine, sg: &Song, d: f32) -> Chip { Chip { img: chip_img(e, sg, d), col: col(&sg.col) } }
fn tip(sg: &Song) -> SharedString { if sg.artist.is_empty() { sg.name.clone().into() } else { format!("{} \u{2014} {}", sg.name, sg.artist).into() } }
/// Client height of the intros pages.
fn page_h(ui: &Panel) -> f32 { ui.get_intros_page_h() }

pub fn init(ui: &Panel, eng: Arc<Engine>, shell: Arc<dyn Shell>) {
    assets::set_scale(ui.window().scale_factor());
    let strips = [assets::strip("glow19"), assets::strip("glow14"), assets::strip("eq19"), assets::strip("eq14")];
    ED.with(|e| *e.borrow_mut() = Some(Ed { eng, shell, ui: ui.as_weak(), h: History::default(), k: None, sc: 0.0, press: None, drag: false, drop: None,
        song: None, busy: false, glow_t0: Instant::now(), pdel: None, imp: None, ctx_idx: 0, toast_t: None, hint_t: None, strips }));
    let g = ui.global::<IntroUi>();
    g.on_back(|| { let p = page(); if p == "age" { with(|e| e.k = None); set_page("intros"); } else { set_page("main"); } });
    g.on_open_age(|k| { with(|e| { e.k = Some(k.to_string()); e.sc = 0.0; }); set_page("age"); });
    g.on_set_age_on(|k, on| edit(move |cx, u, e| { let k = if k.is_empty() { e.k.clone().unwrap_or_default() } else { k.to_string() }; aoe4engine::editor::set_age_on(cx, u, &k, on) }));
    g.on_reset_age(|| edit(|cx, u, e| { let Some(a) = e.k.clone() else { return false }; let def = a == cx.default_age;
        let p = cx.civs.iter().map(|(c, _)| (c.clone(), if def { cx.sorted(u, cx.defs.get(c).map(|v| &v[..]).unwrap_or(&[])) } else { vec![] })).collect(); cx.commit_pools(u, &a, &p); true }));
    g.on_civ_default(|i| edit(move |cx, u, e| { let Some(a) = e.k.clone() else { return false }; let Some((c, _)) = cx.civs.get(i as usize).cloned() else { return false };
        let mut p = cx.pools_of(u, &a); let d = cx.sorted(u, cx.defs.get(&c).map(|v| &v[..]).unwrap_or(&[])); p.insert(c, d); cx.commit_pools(u, &a, &p); true }));
    g.on_remove_at(|i, j| edit(move |cx, u, e| remove_at(cx, u, e, i as usize, j as usize)));
    g.on_press(|kind, i, j, x, y| { press(&kind, i as usize, j as usize, x - 1.0, y - 31.0); });
    g.on_drag_move(|x, y| drag_move(x - 1.0, y - 31.0));
    g.on_release(|x, y| release(x - 1.0, y - 31.0));
    g.on_scroll(|d| { with(|e| { let m = max_sc(e); e.sc = (e.sc + d * 46.0).clamp(0.0, m); }); refresh(); });
    g.on_undo(|back| undo(back));
    g.on_tray_ctx(|i, x, y| { with(|e| e.ctx_idx = i as usize); if let Some(ui) = ui_of() { let g = ui.global::<IntroUi>(); g.set_ctx_x(x - 1.0); g.set_ctx_y(y - 31.0); g.set_ctx_open(true); } });
    g.on_ctx_remove(|| edit(|cx, u, e| { let Some(sg) = cx.songs_of(u).get(e.ctx_idx).cloned() else { return false }; cx.remove_custom(u, &sg.uri); true }));
    g.on_pack(|open| { with(|e| { let mut u = ed_of(&state(&e.eng)); u["intro_pack_open"] = json!(open); presets::save_ed(&e.eng, u); }); refresh(); });
    g.on_open_add(|| { with(|e| e.shell.show(Win::Add)); });
    g.on_switch_preset(|name| { if let Some(ui) = ui_of() { ui.global::<IntroUi>().set_pmenu(false); }
        edit(move |cx, u, _| { let Some(p) = cx.presets(u).into_iter().find(|p| p["name"] == json!(name.as_str())) else { return false }; cx.apply_preset(u, &p); true }) });
    g.on_del_preset(|name| del_preset(name.to_string()));
    g.on_new_preset(|| { if let Some(ui) = ui_of() { let g = ui.global::<IntroUi>(); g.set_dlg_value("My preset".into()); g.set_dialog("name".into()); } });
    g.on_dlg_close(close_dialog);
    g.on_dlg_save(|| { let Some(ui) = ui_of() else { return }; let v = ui.global::<IntroUi>().get_dlg_value().trim().to_string(); if v.is_empty() { return; }
        close_dialog(); with(|e| { let s = state(&e.eng); let cx = ctx(&s); let mut u = ed_of(&s); let name = cx.unique_name(&u, &v);
            let mut ps: Vec<Value> = u["intro_presets"].as_array().cloned().unwrap_or_default().into_iter().filter(|p| p.is_object()).collect();
            ps.push(cx.preset_from_user(&u, &name)); u["intro_presets"] = json!(ps); u["intro_preset"] = json!(name); e.h.cur = Some(snap(&u)); presets::save_ed(&e.eng, u); }); refresh(); });
    g.on_share(|| { with(|e| { let s = state(&e.eng); let cx = ctx(&s); let u = ed_of(&s); let n = u["intro_preset"].as_str().unwrap_or("Shared").to_string();
        guides::set_clip_text(&presets::encode_preset(cx.preset_from_user(&u, &n))); }); toast("Code copied"); });
    g.on_import_open(|| { with(|e| e.imp = None); if let Some(ui) = ui_of() { let g = ui.global::<IntroUi>(); g.set_dlg_value("".into()); g.set_imp_ok(false); g.set_imp_err("".into()); g.set_dialog("import".into()); } });
    g.on_import_input(|t| import_input(t.to_string()));
    g.on_import_go(|| { let p = with(|e| e.imp.clone()).flatten(); let Some(mut p) = p else { return }; close_dialog();
        edit(move |cx, u, _| { p["name"] = json!(cx.unique_name(u, p["name"].as_str().unwrap_or("Shared"))); let mut ps = u["intro_presets"].as_array().cloned().unwrap_or_default();
            ps.push(p.clone()); u["intro_presets"] = json!(ps); cx.apply_preset(u, &p); true }); toast("Imported"); });
    // glow / equalizer frames (54 x 33 ms) while a song previews, fade-in 330 ms
    let t = Timer::default();
    t.start(TimerMode::Repeated, Duration::from_millis(33), || { with(|e| {
        let Some(ui) = e.ui.upgrade() else { return }; let g = ui.global::<IntroUi>();
        if e.toast_t.is_some_and(|t| t.elapsed() >= Duration::from_millis(1800)) { e.toast_t = None; g.set_toast("".into()); }
        if e.hint_t.is_some_and(|t| t.elapsed() >= Duration::from_millis(2600)) { e.hint_t = None; g.set_hint("".into()); }
        if e.pdel.as_ref().is_some_and(|(_, t)| t.elapsed() >= Duration::from_secs(3)) { e.pdel = None; g.set_pdel("".into()); }
        if e.song.is_none() || g.get_page() != "age" { return; }
        let el = e.glow_t0.elapsed().as_secs_f32(); let f = ((el / 0.033) as usize) % 54;
        let pick = |v: &Vec<Image>| v.get(f).cloned().unwrap_or_default();
        g.set_glow19(pick(&e.strips[0])); g.set_glow14(pick(&e.strips[1])); g.set_eq19(pick(&e.strips[2])); g.set_eq14(pick(&e.strips[3]));
        g.set_glow_op((el / 0.33).min(1.0));
    }); });
    TIMER.with(|x| *x.borrow_mut() = Some(t));
}

fn ui_of() -> Option<Panel> { with(|e| e.ui.upgrade()).flatten() }
fn page() -> String { ui_of().map(|u| u.global::<IntroUi>().get_page().to_string()).unwrap_or_default() }
pub fn set_page(p: &str) { if let Some(ui) = ui_of() { let g = ui.global::<IntroUi>(); crate::tips_hide(&ui); g.set_pmenu(false); g.set_ctx_open(false); g.set_page(p.into()); } refresh(); }
fn close_dialog() { if let Some(ui) = ui_of() { ui.global::<IntroUi>().set_dialog("".into()); ui.invoke_refocus(); } }
fn toast(m: &str) { with(|e| e.toast_t = Some(Instant::now())); if let Some(ui) = ui_of() { ui.global::<IntroUi>().set_toast(m.into()); } }
fn hint(m: &str, x: f32, y: f32) { with(|e| e.hint_t = Some(Instant::now())); if let Some(ui) = ui_of() { let g = ui.global::<IntroUi>(); g.set_hint(m.into()); g.set_hint_x(x); g.set_hint_y(y); } }
fn max_sc(e: &Ed) -> f32 {
    let Some(ui) = e.ui.upgrade() else { return 0.0 }; let n = state(&e.eng)["agedata"]["civs"].as_array().map_or(0, |a| a.len()) as f32;
    (n * STEP - 4.0 - (page_h(&ui) - 12.0 - LT)).max(0.0)
}

/// One editor step: run `f` on a copy of intros.json, then record (undo, auto-off, preset autosave) and save.
fn edit(f: impl FnOnce(&Ctx, &mut Value, &Ed) -> bool) {
    let np = with(|e| {
        let s = state(&e.eng); let cx = ctx(&s); let before = ed_of(&s); let mut u = before.clone();
        if !f(&cx, &mut u, e) { return None; }
        let (u, np) = e.h.record(&cx, &before, u); presets::save_ed(&e.eng, u); np
    }).flatten();
    if let Some(n) = np { toast(&format!("Saved as \u{201c}{n}\u{201d}")); }
    refresh();
}
fn undo(back: bool) {
    with(|e| { if e.drag { return; } let s = state(&e.eng); let cx = ctx(&s); if let Some(u) = e.h.step(&cx, &ed_of(&s), back) { presets::save_ed(&e.eng, u); } });
    refresh();
}
fn remove_at(cx: &Ctx, u: &mut Value, e: &Ed, i: usize, j: usize) -> bool {
    let Some(a) = e.k.clone() else { return false }; let Some((c, _)) = cx.civs.get(i).cloned() else { return false };
    let mut p = cx.pools_of(u, &a); let Some(l) = p.get_mut(&c) else { return false }; if j >= l.len() { return false; } l.remove(j); cx.commit_pools(u, &a, &p); true
}
fn del_preset(name: String) {
    let armed = with(|e| e.pdel.as_ref().is_some_and(|(n, _)| *n == name)).unwrap_or(false);
    if !armed { with(|e| e.pdel = Some((name.clone(), Instant::now()))); if let Some(ui) = ui_of() { ui.global::<IntroUi>().set_pdel(name.into()); } return; }
    with(|e| { e.pdel = None; let mut u = ed_of(&state(&e.eng));
        let ps: Vec<Value> = u["intro_presets"].as_array().cloned().unwrap_or_default().into_iter().filter(|p| p["name"] != json!(name)).collect();
        u["intro_presets"] = json!(ps); presets::save_ed(&e.eng, u); });
    if let Some(ui) = ui_of() { ui.global::<IntroUi>().set_pdel("".into()); }
    refresh();
}
fn import_input(t: String) {
    let r = with(|e| { if t.trim().is_empty() { return None; } Some(presets::decode_preset(&e.eng, t.trim().to_string())) }).flatten();
    let Some(ui) = ui_of() else { return }; let g = ui.global::<IntroUi>();
    match r {
        None => { with(|e| e.imp = None); g.set_imp_ok(false); g.set_imp_err("".into()); }
        Some(Err(m)) => { with(|e| e.imp = None); g.set_imp_ok(false); g.set_imp_err(m.into()); }
        Some(Ok(p)) => {
            let (chips, ags) = with(|e| { let s = state(&e.eng); let cx = ctx(&s); let mut u = ed_of(&s);
                let mut cs = u["custom_songs"].as_array().cloned().unwrap_or_default(); cs.extend(p["custom"].as_array().cloned().unwrap_or_default()); u["custom_songs"] = json!(cs);
                let by = cx.songs_of(&u);
                let chips: Vec<Chip> = cx.preset_songs(&u, &p).iter().take(3).filter_map(|x| by.iter().find(|s| s.uri == *x)).map(|sg| chip(&e.eng, sg, 30.0)).collect();
                let cnt = cx.preset_counts(&p);
                let ags: Vec<ImpAge> = cx.ages.iter().enumerate().map(|(k, a)| { let n = cnt[a]; ImpAge { roman: ROMAN[k.min(7)].into(), on: p["ages"][a].as_bool().unwrap_or(*a == cx.default_age) && n > 0, cnt: format!("{n}/{}", cx.civs.len()).into() } }).collect();
                (chips, ags) }).unwrap_or_default();
            g.set_imp_name(p["name"].as_str().unwrap_or("Shared").into()); g.set_imp_chips(model(chips)); g.set_imp_ages(model(ags)); g.set_imp_err("".into()); g.set_imp_ok(true);
            with(|e| e.imp = Some(p));
        }
    }
}

// ---- drag (age.js on_press / on_drag / on_release): tray chip -> civ row = add; row chip -> other row = move; out of its row = remove
fn press(kind: &str, i: usize, j: usize, x: f32, y: f32) {
    with(|e| { let s = state(&e.eng); let cx = ctx(&s); let u = ed_of(&s);
        let song = if kind == "tray" { cx.songs_of(&u).get(i).cloned() } else {
            let Some(a) = e.k.clone() else { return }; let p = cx.pools_of(&u, &a);
            cx.civs.get(i).and_then(|(c, _)| p[c].get(j).cloned()).and_then(|uri| cx.songs_of(&u).into_iter().find(|s| s.uri == uri)) };
        if let Some(song) = song { e.press = Some(Press { kind: kind.into(), i, j, x, y, song }); e.drag = false; e.drop = None; } });
}
fn drop_row(e: &Ed, n: usize, x: f32, y: f32) -> Option<usize> {
    let ui = e.ui.upgrade()?; let bot = page_h(&ui) - 12.0;
    if !(LT <= y && y <= bot && 20.0 <= x && x <= IW - 32.0) { return None; }
    let i = ((y - LT + e.sc) / STEP).floor(); if i < 0.0 || i as usize >= n { return None; }
    let ry = LT + i * STEP - e.sc; (ry <= y && y <= ry + RH).then_some(i as usize)
}
fn drag_move(x: f32, y: f32) {
    let changed = with(|e| {
        let Some(p) = e.press.clone() else { return false };
        if !e.drag && (x - p.x).abs() + (y - p.y).abs() < 4.0 { return false; }
        let first = !e.drag; e.drag = true;
        let s = state(&e.eng); let cx = ctx(&s); let u = ed_of(&s); let m = max_sc(e);
        let Some(ui) = e.ui.upgrade() else { return false }; let bot = page_h(&ui) - 12.0;
        if y > bot - 24.0 && e.sc < m { e.sc = (e.sc + 8.0).min(m); } else if LT < y && y < LT + 24.0 && e.sc > 0.0 { e.sc = (e.sc - 8.0).max(0.0); }
        let mut d = drop_row(e, cx.civs.len(), x, y);
        if d.is_some() && p.kind == "row" && d == Some(p.i) { d = None; }
        if let (Some(i), Some(a)) = (d, e.k.clone()) { if cx.pools_of(&u, &a)[&cx.civs[i].0].contains(&p.song.uri) { d = None; } }
        let g = ui.global::<IntroUi>();
        if first { crate::tips_hide(&ui); g.set_ghost_img(chip_img(&e.eng, &p.song, 38.0)); g.set_ghost_col(col(&p.song.col));
            g.set_mv_row(if p.kind == "row" { p.i as i32 } else { -1 }); g.set_mv_j(if p.kind == "row" { p.j as i32 } else { -1 }); g.set_drag_tray(if p.kind == "tray" { p.i as i32 } else { -1 }); g.set_drag_on(true); }
        g.set_ghost_x(x); g.set_ghost_y(y); g.set_drop(d.map_or(-1, |v| v as i32)); g.set_sc(e.sc);
        e.drop = d; true
    }).unwrap_or(false);
    let _ = changed;
}
fn release(x: f32, y: f32) {
    let Some((p, dragged, drop)) = with(|e| { let p = e.press.take()?; let r = (p, e.drag, e.drop); e.drag = false; e.drop = None; Some(r) }).flatten() else { return };
    if let Some(ui) = ui_of() { let g = ui.global::<IntroUi>(); g.set_drag_on(false); g.set_drop(-1); g.set_mv_row(-1); g.set_mv_j(-1); g.set_drag_tray(-1); }
    if !dragged { preview(p.song, x, y); return; }
    edit(move |cx, u, e| {
        let Some(a) = e.k.clone() else { return false }; let mut pools = cx.pools_of(u, &a); let uri = p.song.uri.clone();
        if let Some(d) = drop {
            let civ = cx.civs[d].0.clone(); let l = pools.get_mut(&civ).unwrap(); if !l.contains(&uri) { l.push(uri.clone()); }
            if p.kind == "row" { let sc = cx.civs[p.i].0.clone(); let l = pools.get_mut(&sc).unwrap(); if l.len() > 1 { l.retain(|x| *x != uri); } }
            cx.commit_pools(u, &a, &pools); true
        } else if p.kind == "row" && drop_row(e, cx.civs.len(), x, y) != Some(p.i) { remove_at(cx, u, e, p.i, p.j) } else { false }
    });
}
fn preview(sg: Song, x: f32, y: f32) {
    let go = with(|e| { if e.busy { return None; } let play = e.song.as_deref() != Some(&sg.key); let prev = e.song.clone();
        e.busy = true; e.song = play.then(|| sg.key.clone()); if play && prev.as_deref() != Some(&sg.key) { e.glow_t0 = Instant::now(); }
        Some((e.eng.clone(), play, prev)) }).flatten();
    let Some((eng, play, prev)) = go else { return };
    refresh();
    let uri = play.then(|| sg.uri.clone()); let key = sg.key.clone();
    std::thread::spawn(move || {
        let r = picker::preview(&eng, uri).unwrap_or_else(|_| "err".into());
        let _ = slint::invoke_from_event_loop(move || {
            with(|e| e.busy = false);
            if r == "login" { with(|e| e.song = prev); hint("Log in to Spotify in AoE4 Spotify to preview", x, y); }
            else if r != "ok" { with(|e| e.song = if play { if prev.as_deref() != Some(&key) { prev } else { None } } else { prev }); hint("Couldn't play - is Spotify (Premium) running?", x, y); }
            refresh();
        });
    });
}

/// Push the whole intros state to the UI (overview, preset menu, the open age page).
pub fn refresh() {
    with(|e| {
        let Some(ui) = e.ui.upgrade() else { return }; let g = ui.global::<IntroUi>();
        if g.get_page() == "main" { return; }
        let s = state(&e.eng); let cx = ctx(&s); let u = ed_of(&s); let all = cx.songs_of(&u);
        let by = |uri: &str| all.iter().find(|x| x.uri == uri);
        g.set_crown_lit(s["settings"]["enabled"].as_bool().unwrap_or(true) && s["settings"]["boss_on"].as_bool().unwrap_or(true));
        // overview
        let ov: Vec<OvAge> = ages(&s).iter().enumerate().map(|(i, (k, lab))| { let o = &s["intros"][k];
            let chips = o["chips"].as_array().cloned().unwrap_or_default().iter().map(|c| Chip { img: assets::portrait(c[0].as_str().unwrap_or(""), 26.0), col: col(c[1].as_str().unwrap_or("")) }).collect();
            OvAge { key: k.into(), label: lab.replace(" Age", "").into(), roman: ROMAN[i.min(7)].into(), on: o["on"].as_bool().unwrap_or(false), n: o["n"].as_i64().unwrap_or(0) as i32,
                civs: o["civs"].as_i64().unwrap_or(1).max(1) as i32, chips: model(chips), more: o["more"].as_i64().unwrap_or(0) as i32 } }).collect();
        g.set_ages(model(ov));
        let cur = u["intro_preset"].as_str().unwrap_or(DEFAULT_PRESET).to_string();
        g.set_preset_name(view::trunc(&cur, 30).into());
        let ps: Vec<PresetRow> = cx.presets(&u).iter().map(|p| { let name = p["name"].as_str().unwrap_or("").to_string(); let cnt = cx.preset_counts(p);
            let romans: Vec<&str> = cx.ages.iter().enumerate().filter(|(_, a)| cnt[*a] > 0 && p["ages"][*a].as_bool().unwrap_or(**a == cx.default_age)).map(|(k, _)| ROMAN[k.min(7)]).collect();
            PresetRow { cur: name == cur, builtin: p["builtin"] == json!(true), chips: model(cx.preset_songs(&u, p).iter().take(3).filter_map(|x| by(x)).map(|sg| chip(&e.eng, sg, 20.0)).collect()),
                romans: romans.join(" ").into(), name: name.into() } }).collect();
        g.set_presets(model(ps));
        // age page
        let Some(a) = e.k.clone() else { return };
        let al = ages(&s); let ai = al.iter().position(|x| x.0 == a).unwrap_or(0);
        let on = cx.ages_on(&u)[&a]; let empty = cx.age_empty(&u, &a); let def = a == cx.default_age;
        g.set_label(al.get(ai).map(|x| x.1.replace(" Age", "")).unwrap_or_default().into());
        g.set_badge(assets::age(&format!("badge{ai}_{}", if on { "on" } else { "off" }))); g.set_on(on); g.set_empty(empty);
        g.set_custom(u["intro_pools"].get(&a).is_some()); g.set_default_age(def);
        let pools = cx.pools_of(&u, &a);
        let first_empty = cx.civs.iter().position(|(c, _)| pools[c].is_empty());
        let rows: Vec<CivRow> = cx.civs.iter().enumerate().map(|(i, (c, name))| { let l = &pools[c];
            CivRow { name: name.into(), flag: assets::age(&format!("flag_{c}")), first_empty: first_empty == Some(i),
                undo: def && *l != cx.sorted(&u, cx.defs.get(c).map(|v| &v[..]).unwrap_or(&[])),
                chips: model(l.iter().filter_map(|x| by(x)).map(|sg| RowChip { img: chip_img(&e.eng, sg, 28.0), col: col(&sg.col), tip: tip(sg), key: sg.key.clone().into() }).collect()) } }).collect();
        g.set_rows(model(rows));
        let m = max_sc(e); e.sc = e.sc.clamp(0.0, m); g.set_sc(e.sc); g.set_max_sc(m);
        // tray (trayLayout)
        let nb = cx.builtin.len(); let un = all.len() - nb; let w = IW;
        let ysp = (100.0 / un.max(1) as f32).min(50.0); let yr = (ysp * 0.45).clamp(9.0, 19.0);
        let view = if un == 0 { "octo0" } else if u["intro_pack_open"].as_bool().unwrap_or(false) { "octo" } else { "yours" };
        let mut chips: Vec<(usize, f32, f32)> = vec![]; let (div, plus, plus_r, count, emblem);
        match view {
            "octo0" => { let bsp = (((w - 24.0) - (16.0 + 38.0 + 4.0) - 63.0 - 53.0) / (nb.max(2) - 1) as f32).clamp(22.0, 48.0);
                for i in 0..nb { chips.push((i, 53.0 + i as f32 * bsp, 19.0)); } div = 53.0 + (nb.max(1) - 1) as f32 * bsp + 19.0 + 16.0; plus = div + 16.0 + 19.0; plus_r = 19.0; count = None; emblem = false; }
            "yours" => { div = 57.0 + 23.0 + 16.0; for j in 0..un { chips.push((nb + j, div + 16.0 + yr + j as f32 * ysp, yr)); } plus = div + 16.0 + yr + un as f32 * ysp; plus_r = yr; count = None; emblem = true; }
            _ => { div = w - 213.0; let bsp = ((div - 12.0 - 19.0 - 53.0) / (nb.max(2) - 1) as f32).min(48.0);
                for i in 0..nb { chips.push((i, 53.0 + i as f32 * bsp, 19.0)); } count = Some(div + 16.0 + 19.0); plus = div + 16.0 + 19.0 + 44.0; plus_r = 19.0; emblem = false; }
        }
        let tray: Vec<TrayChip> = chips.iter().enumerate().map(|(n, &(i, cxx, r))| { let sg = &all[i];
            let right = chips.get(n + 1).map(|nx| nx.1 - nx.2).filter(|l| *l < cxx + r).unwrap_or(cxx + r);
            TrayChip { idx: i as i32, cx: cxx, r, hit_w: right - (cxx - r), img: chip_img(&e.eng, sg, 2.0 * r), col: col(&sg.col), tip: tip(sg), custom: sg.key.starts_with("c_"), key: sg.key.clone().into() } }).collect();
        g.set_tray(model(tray)); g.set_div(div); g.set_plus_cx(plus); g.set_plus_r(plus_r); g.set_emblem(emblem);
        g.set_count_n(if count.is_some() { un as i32 } else { -1 }); g.set_count_cx(count.unwrap_or(0.0));
        g.set_playing(e.song.clone().unwrap_or_default().into());
    });
}
/// Called from the main 250 ms tick: redraw when the engine state changed (another window, the game).
pub fn tick(changed: bool) { if changed && page() != "main" && !with(|e| e.drag).unwrap_or(false) { refresh(); } }

/// AOE4S_PAGE test renders: intros | pmenu | name | import | age:<key>[:drag|:tip|:menu]
pub fn test_state(spec: &str) {
    let mut it = spec.split(':'); let p = it.next().unwrap_or("");
    match p {
        "intros" | "pmenu" | "name" | "import" => { set_page("intros"); let Some(ui) = ui_of() else { return }; let g = ui.global::<IntroUi>();
            if p == "pmenu" { g.set_pmenu(true); }
            if p == "name" { g.invoke_new_preset(); }
            if p == "import" { g.invoke_import_open(); let code = with(|e| { let s = state(&e.eng); let cx = ctx(&s); presets::encode_preset(cx.preset_from_user(&ed_of(&s), "Capstar's intros")) }).unwrap_or_default();
                g.set_dlg_value(code.clone().into()); import_input(code); } }
        "age" => { let k = it.next().unwrap_or("castle").to_string(); with(|e| { e.k = Some(k); e.sc = 0.0; }); set_page("age");
            if it.next() == Some("drag") { let Some(ui) = ui_of() else { return }; let t = ui.global::<IntroUi>().get_tray();
                use slint::Model; if let Some(c) = t.row_data(2) { press("tray", c.idx as usize, 0, c.cx, 119.0); drag_move(262.0, LT + STEP + 26.0); } } }
        "selftest" => selftest(),
        _ => {}
    }
}

/// AOE4S_PAGE=selftest: drive the editor through the UI callbacks like a user; prints PASS/FAIL lines.
pub fn selftest() {
    let Some(ui) = ui_of() else { return }; let g = ui.global::<IntroUi>();
    let ed = || with(|e| ed_of(&state(&e.eng))).unwrap_or_default();
    let (cx, s) = with(|e| { let s = state(&e.eng); (ctx(&s), s) }).unwrap();
    let ok = |n: &str, c: bool| println!("{} {n}", if c { "PASS" } else { "FAIL" });
    let a = "castle"; let civ1 = cx.civs[1].0.clone(); let song = cx.builtin[2].uri.clone();
    g.invoke_open_age(a.into()); ok("age page open", g.get_page() == "age" && g.get_rows().row_count() == cx.civs.len());
    // drag tray chip 2 onto row 1
    use slint::Model; let t = g.get_tray().row_data(2).unwrap();
    g.invoke_press("tray".into(), t.idx, 0, t.cx + 1.0, 119.0 + 31.0); g.invoke_drag_move(262.0 + 1.0, LT + STEP + 26.0 + 31.0);
    ok("drag shows the drop row", g.get_drop() == 1 && g.get_drag_on());
    g.invoke_release(262.0 + 1.0, LT + STEP + 26.0 + 31.0);
    let u = ed(); ok("drop adds the song to the civ", cx.pools_of(&u, a)[&civ1] == vec![song.clone()]);
    ok("edit forks preset Custom", u["intro_preset"] == json!("Custom"));
    g.invoke_set_age_on("".into(), false); ok("age switched off", !cx.ages_on(&ed())[a] && !g.get_on());
    g.invoke_set_age_on("".into(), true); ok("age switched on", cx.ages_on(&ed())[a] && g.get_on());
    g.invoke_undo(true); ok("undo: age off again", !cx.ages_on(&ed())[a]);
    g.invoke_undo(false); ok("redo: age on", cx.ages_on(&ed())[a]);
    g.invoke_remove_at(1, 0); let u = ed(); ok("remove: empty age switches itself off", cx.age_empty(&u, a) && !cx.ages_on(&u)[a]);
    // drag out of a row = remove
    g.invoke_undo(true); let r = g.get_rows().row_data(1).unwrap(); ok("undo restores the chip", r.chips.row_count() == 1);
    g.invoke_press("row".into(), 1, 0, 205.0 + 1.0, LT + STEP + 20.0 + 31.0); g.invoke_drag_move(300.0, 140.0 + 31.0); g.invoke_release(300.0, 140.0 + 31.0);
    ok("dragged out of its row = removed", cx.pools_of(&ed(), a)[&civ1].is_empty());
    // presets
    g.invoke_new_preset(); g.set_dlg_value("Test preset".into()); g.invoke_dlg_save(); ok("new preset saved + current", ed()["intro_preset"] == json!("Test preset") && g.get_dialog() == "");
    g.invoke_switch_preset("Default".into()); ok("switch to Default", ed()["intro_preset"] == json!("Default"));
    g.invoke_switch_preset("Test preset".into()); ok("switch back", ed()["intro_preset"] == json!("Test preset"));
    let code = presets::encode_preset(cx.preset_from_user(&ed(), "Shared one"));
    g.invoke_import_open(); g.invoke_import_input(code.into()); ok("import preview", g.get_imp_ok() && g.get_imp_name() == "Shared one");
    g.invoke_import_go(); ok("import adds + applies", ed()["intro_preset"] == json!("Shared one") && g.get_toast() == "Imported");
    g.invoke_import_open(); g.invoke_import_input("AOE4S1:garbage".into()); ok("bad code rejected", !g.get_imp_ok() && g.get_imp_err().contains("damaged")); g.invoke_dlg_close();
    g.invoke_del_preset("Test preset".into()); ok("delete arms first", g.get_pdel() == "Test preset" && cx.presets(&ed()).len() == 4);
    g.invoke_del_preset("Test preset".into()); ok("second click deletes", !cx.presets(&ed()).iter().any(|p| p["name"] == json!("Test preset")));
    g.invoke_pack(false); ok("pack state saved", ed()["intro_pack_open"] == json!(false));
    g.invoke_back(); g.invoke_back(); ok("back twice -> main", g.get_page() == "main");
    let _ = s;
}

// ---- M3 Add a song: songs / links dropped on the age page or the Add a song window -> YOURS (one undo step per add)
/// Uris already in the song list (built-ins + YOURS).
pub fn have_uris() -> Vec<String> { with(|e| { let s = state(&e.eng); ctx(&s).songs_of(&ed_of(&s)).into_iter().map(|x| x.uri).collect() }).unwrap_or_default() }
/// Where messages show on the age page: just above the YOURS '+'.
fn plus_at() -> (f32, f32) { ui_of().filter(|u| u.global::<IntroUi>().get_page() == "age").map(|u| (u.global::<IntroUi>().get_plus_cx(), 119.0)).unwrap_or((IW / 2.0, 120.0)) }
fn tell(m: &str, err: bool) { if page() == "age" { let (x, y) = plus_at(); hint(m, x, y); } crate::add::say(m, err); }
pub fn add_songs(items: Vec<Value>) -> usize {
    let mut fresh: Vec<Value> = vec![];
    edit(|cx, u, _| { fresh = cx.add_songs(u, &items); !fresh.is_empty() });
    if fresh.is_empty() { tell(if items.is_empty() { "No songs found" } else if items.len() > 1 { "Already in YOURS" } else { "Already added" }, false); return 0; }
    // covers for the new chips: the picked items carry their artwork urls
    let urls: Vec<Value> = items.iter().filter(|i| fresh.iter().any(|f| f["uri"] == i["uri"])).cloned().collect();
    with(|e| picker::cache_covers(e.eng.clone(), urls));
    let m = if fresh.len() > 1 { format!("Added {} songs to YOURS", fresh.len()) } else { format!("Added \u{201c}{}\u{201d}", fresh[0]["name"].as_str().unwrap_or("Song")) };
    tell(&m, false); crate::add::paint(); fresh.len()
}
/// Text with Spotify song links: look up the songs we don't know (Spotify), then add them.
pub fn drop_text(t: String) {
    let ids = crate::add::track_ids(&t);
    if ids.is_empty() { tell("Drop a Spotify song or song link", true); return; }
    let have = have_uris(); let miss: Vec<String> = ids.iter().filter(|i| !have.contains(&format!("spotify:track:{i}"))).cloned().collect();
    if miss.is_empty() { add_songs(ids.iter().map(|i| json!({ "uri": format!("spotify:track:{i}") })).collect()); return; }
    let Some(eng) = with(|e| e.eng.clone()) else { return };
    std::thread::spawn(move || { let r = picker::sp(&eng, "tracks", &miss.join(","));
        let _ = slint::invoke_from_event_loop(move || match r {
            Ok(v) if v == "login" => { tell("Log in to Spotify in AoE4 Spotify to add songs", true); }
            r => { let got = r.ok().and_then(|v| v.as_array().cloned()).unwrap_or_default();
                let items: Vec<Value> = ids.iter().filter_map(|i| { let u = format!("spotify:track:{i}"); got.iter().find(|g| g["uri"] == json!(u)).cloned().or_else(|| have.contains(&u).then(|| json!({ "uri": u }))) }).collect();
                add_songs(items); }
        }); });
}
/// Something is dragged over the panel window: on the age page YOURS lights up ("DROP TO ADD").
pub fn drag_over(on: bool) { if let Some(ui) = ui_of() { let g = ui.global::<IntroUi>(); let on = on && g.get_page() == "age"; if g.get_drop_over() != on { crate::tips_hide(&ui); g.set_drop_over(on); } } }
/// Songs dragged out of the Add a song list (same process: no OLE drag source needed).
pub fn drop_on_page_items(items: Vec<Value>) { if page() == "age" { add_songs(items); } else { tell("Open an age to drop songs on it", true); } }
pub fn drop_on_page(t: String) { if page() == "age" { drop_text(t); } }
