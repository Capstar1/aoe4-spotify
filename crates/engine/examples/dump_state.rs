//! Writes the full UI state (as Tauri get_state returns it) to a file, for the HTML reference harness. Usage: dump_state <data dir> <out.js>
fn main() {
    let a: Vec<String> = std::env::args().collect();
    let (e, _rx, _p) = aoe4engine::Engine::new(a[1].clone().into());
    let (_, s) = e.static_state();
    let mut st = e.state(None); if let (Some(o), Some(m)) = (st.as_object_mut(), s.as_object()) { for (k, v) in m { o.insert(k.clone(), v.clone()); } }
    std::fs::write(&a[2], format!("window.ST2 = {};", st)).unwrap();
}
