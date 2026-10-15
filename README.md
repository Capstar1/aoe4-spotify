# AoE4 Spotify 1.1 (Rust + Slint)

- `crates/core`: Spotify, game log, settings (no UI).
- `crates/engine`: app logic, UI-independent.
- `crates/winsys`: Windows-only pieces.
- `slint-panel`: Slint front end (views in `slint-panel/ui`, art in `ui/img`).
- `installer/setup11.iss`: Inno Setup (no WebView2; removes the old Tauri WebView2 profile on upgrade).

## Build

- Fast dev build (own crates opt-level 0, deps at 2; ~4 s incremental vs ~130 s release, incremental): `cargo build -p aoe4spotify-slint --profile dev-fast` -> `target\dev-fast\aoe4spotify-slint.exe`
- Release (size-optimised, LTO, stripped): `cargo build -p aoe4spotify-slint --release`
- Installer: `ISCC installer\setup11.iss` (add `/DTEST` for the sandbox test build)
- Benchmark vs 1.0.9: `powershell -File tools\bench.ps1 -Tag after`
