# AoE4 Spotify 1.1 (Rust + Slint)

- `crates/core`: Spotify, game log, settings (no UI).
- `crates/engine`: app logic, UI-independent.
- `crates/winsys`: Windows-only pieces.
- `slint-panel`: Slint front end (views in `slint-panel/ui`, art in `ui/img`).
- `installer/setup11.iss`: Inno Setup (no WebView2; removes the old Tauri WebView2 profile on upgrade).

