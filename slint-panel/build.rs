fn main() {
    slint_build::compile("ui/app.slint").expect("Slint UI");
    // runtime-picked art (flags, age badges, portraits, glow strips): embedded, looked up by name
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../ui/img");
    let mut out = String::from("pub static ASSETS: &[(&str, &[u8])] = &[\n");
    for sub in ["age", "portraits"] {
        let mut names: Vec<_> = std::fs::read_dir(root.join(sub)).expect("ui/img").filter_map(|e| e.ok()).map(|e| e.file_name().to_string_lossy().to_string())
            .filter(|n| n.ends_with(".png") || n.ends_with(".jpg") || n.ends_with(".webp")).collect();
        names.sort();
        for n in names { let p = root.join(sub).join(&n); out += &format!("    ({:?}, include_bytes!({:?})),\n", format!("{sub}/{n}"), p.canonicalize().unwrap()); }
        println!("cargo:rerun-if-changed={}", root.join(sub).display());
    }
    out += "];\n";
    std::fs::write(std::path::Path::new(&std::env::var("OUT_DIR").unwrap()).join("assets.rs"), out).unwrap();
}
