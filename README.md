# AoE4 Spotify 1.1 (Rust + Tauri)

Rewrite of the Python app (which stays the daily driver until 1.1 reaches parity). See rust_plan.md.

- `crates/core`: game adapter trait, AoE4 log adapter, log tail, switcher state machine, settings (reads the 1.0.x files read-only). No UI, no game names outside `aoe4.rs`.
- `app`: Tauri shell (WebView2), fixed-size window, pages in `ui/`.

    cargo test -p aoe4core        # log-replay tests
    cargo run -p aoe4spotify      # M1 app (dry run: logs what it would play, never touches Spotify)