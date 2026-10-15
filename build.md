# Building AoE4 Spotify from source

Windows. The app is the Rust crate `aoe4spotify-slint`.

- Fast dev build: `cargo build -p aoe4spotify-slint --profile dev-fast` produces `target\dev-fast\aoe4spotify-slint.exe`
- Release: `cargo build -p aoe4spotify-slint --release` produces `target\release\aoe4spotify-slint.exe`
- Installer: Inno Setup 6, `ISCC installer\setup11.iss` (add `/DTEST` for the sandbox test build)
- Benchmark against 1.0.9: `powershell -File tools\bench.ps1 -Tag after`
