use aoe4engine::{editor::{self, Ctx, History}, Engine};
use serde_json::json;

fn ctx() -> (Ctx, serde_json::Value, std::path::PathBuf) {
    std::env::set_var("APPDATA", std::env::temp_dir().join(format!("aoe4s_ed_appdata_{}", std::process::id())));   // keep log lines out of the real app log
    let d = std::env::temp_dir().join(format!("aoe4s_ed_{}", std::process::id())); let _ = std::fs::remove_dir_all(&d); std::fs::create_dir_all(&d).unwrap();
    std::fs::copy(concat!(env!("CARGO_MANIFEST_DIR"), "/../../installer/config.json"), d.join("base.json")).unwrap();
    let (e, _rx, _p) = Engine::new(d.clone()); let (_, s) = e.static_state();
    (Ctx::from_state(&s["agedata"], &e.ages), s["ed"].clone(), d)
}

#[test]
fn editor_flow_like_age_js() {
    let (cx, mut u, d) = ctx();
    if !u.is_object() { u = json!({}); }
    assert!(!cx.civs.is_empty() && !cx.builtin.is_empty() && !cx.default_age.is_empty());
    let da = cx.default_age.clone(); let other = cx.ages.iter().find(|a| **a != da).cloned().unwrap();
    let c0 = cx.civs[0].0.clone();
    // the default age starts on the default pools, other ages empty; an empty age can't be switched on
    assert_eq!(cx.pools_of(&u, &da)[&c0], cx.sorted(&u, &cx.defs[&c0]));
    assert!(cx.age_empty(&u, &other) && !editor::set_age_on(&cx, &mut u.clone(), &other, true));
    // add a built-in song to civ 0 of another age -> forks preset "Custom", one undo step
    let mut h = History::default();
    let s = cx.builtin[2].uri.clone();
    let mut v = u.clone(); let mut p = cx.pools_of(&v, &other); p.get_mut(&c0).unwrap().push(s.clone()); cx.commit_pools(&mut v, &other, &p);
    let (v, np) = h.record(&cx, &u, v);
    assert_eq!(np.as_deref(), Some("Custom")); assert_eq!(v["intro_preset"], json!("Custom"));
    assert_eq!(v["intro_pools"][&other][&c0], json!([s.clone()]));
    // switch it on, then move it to civ 1: the source list keeps its last song (age.js: only removed when > 1)
    let mut w = v.clone(); assert!(editor::set_age_on(&cx, &mut w, &other, true)); let (w, np) = h.record(&cx, &v, w); assert!(np.is_none());
    assert_eq!(cx.ages_on(&w)[&other], true);
    // remove the song: the age is empty again -> switched off automatically
    let mut x = w.clone(); let mut p = cx.pools_of(&x, &other); p.get_mut(&c0).unwrap().clear(); cx.commit_pools(&mut x, &other, &p);
    let (x, _) = h.record(&cx, &w, x);
    assert!(cx.age_empty(&x, &other) && !cx.ages_on(&x)[&other] && x["intro_pools"].get(&other).is_none());
    // default age: equal to the defaults stores nothing; a change stores just that civ
    let cd = cx.civs.iter().map(|c| c.0.clone()).find(|c| !cx.defs[c].is_empty()).expect("a civ with default songs");
    let mut y = x.clone(); let mut p = cx.pools_of(&y, &da); p.get_mut(&cd).unwrap().clear(); cx.commit_pools(&mut y, &da, &p);
    assert_eq!(y["intro_pools"][&da].as_object().unwrap().len(), 1);
    // undo x3 then redo
    let y = h.record(&cx, &x, y).0;
    let z = h.step(&cx, &y, true).unwrap(); assert!(z["intro_pools"][&da].is_null());
    let z = h.step(&cx, &z, true).unwrap(); assert_eq!(cx.ages_on(&z)[&other], true);
    let z = h.step(&cx, &z, false).unwrap(); assert!(!cx.ages_on(&z)[&other]);
    // presets: Default resets; the auto "Custom" fork is removed once the edit matches Default again
    let ps = cx.presets(&z); assert_eq!(ps.len(), 1); assert_eq!(ps[0]["name"], json!("Default"));
    let mut q = z.clone(); cx.apply_preset(&mut q, &ps[0]); assert_eq!(q["intro_preset"], json!("Default")); assert!(q.get("intro_pools").is_none());
    assert_eq!(cx.unique_name(&z, "custom"), "custom"); assert_eq!(cx.unique_name(&z, "  "), "Preset");
    // your songs: add (no duplicates, bad uris ignored), then remove everywhere
    let t = format!("spotify:track:{}", "a".repeat(22));
    let mut r = q.clone(); let fresh = cx.add_songs(&mut r, &[json!({ "uri": t, "name": "X" }), json!({ "uri": t }), json!({ "uri": "spotify:album:1" })]);
    assert_eq!(fresh.len(), 1); assert_eq!(cx.songs_of(&r).last().unwrap().key, format!("c_{}", "a".repeat(22))); assert_eq!(r["intro_pack_open"], json!(false));
    let mut p = cx.pools_of(&r, &other); p.get_mut(&c0).unwrap().push(t.clone()); cx.commit_pools(&mut r, &other, &p);
    cx.remove_custom(&mut r, &t); assert!(cx.songs_of(&r).iter().all(|s| s.uri != t) && r["intro_pools"].get(&other).map_or(true, |o| o.get(&c0).is_none()));
    let _ = std::fs::remove_dir_all(&d);
}
