# AoE4 Spotify 1.1: Rust + Tauri rewrite (plan)

Release **1.1** is the Rust app (there will be no 2.0). The Python app (1.0.x) stays the daily driver until 1.1 does everything it does. 1.1 lives in its own folder `C:\Users\Capstar\Tools\aoe4-spotify-rs\` (next to the Python source), on branch `rust-1.1`.

## Architecture
- **Rust core** (a workspace of crates; no UI code in it):
  - `game`: a `GameAdapter` trait covering:
    - detection: process name, Steam app id, launch option
    - a log/event stream that produces events (MatchStart, AgeUp(n), Victory/Defeat, Replay, Lobby, MatchEnd)
    - labels, icons and assets
    - the intro pack (emblem, frame, colour)
    - Adapters: `aoe4` first; more games plug in the same way. No game names in core.
  - `logtail`: one shared, rotation-safe file follower (a notify watcher with a polling fallback). The adapters parse its lines.
  - `spotify`: PKCE auth with the token kept in Windows Credential Manager; Web API client with retry and rate limiting; playback; fades (volume ramps); restoring what was playing before; a pause watcher; the intros picker.
  - `settings`: typed (serde) and versioned, with a one-time migration from the current `%APPDATA%\AoE4Spotify\*.json`. Settings keys stay the same; presets, custom songs and intros pools carry over.
  - `switcher`: the state machine (age → playlist/intro, after-match, replays, lobby) driven by game events.
  - `updater`: GitHub releases. It installs only between matches (asks the game adapter first), with a signature check.
  - `steam`: sets/removes the launch option, cleans up the Steam environment, safe close/restart of Steam.
- **Web UI** (WebView2 via Tauri, plain TypeScript + a small component kit; no heavy framework):
  - **Window sizes as in 1.0.9** (main ~416×453; Age Intros widens to 520, centred, title bar stays put, extra height goes downward). The resize must show zero blank or stale frames, verified by frame capture on his screen (50+ switches). If WebView2 can't do that cleanly, use the smallest workaround that keeps the look identical.
  - Page router: Main, Intros overview, Age page, Add song, gear menu, dialogs (as overlays inside the window).
  - Kit: smooth vector drawing through SVG/CSS (crown, chips, emblem, glow, fire via a canvas or WebGL shader), tooltips, toggles, sliders, drag-and-drop with a native file/URL drop zone.
  - The UI talks to the core only through typed Tauri commands and events.
- **Installer:** Tauri bundler (NSIS), per-user install. It keeps today's behaviour: close the panel and reopen it, never install while the game runs, `/FROMSWITCHER`.

## Feature parity checklist (all must pass before 1.1)
- [ ] Steam launch-option hook, attach while the game is running, single instance, mutex
- [ ] Age switching with fades, intro song per age and civ (pools, Default), boss/age intros on/off
- [ ] After-match behaviour (Resume / playlist), music in replays, pause watcher, restoring the previous playback
- [ ] Panel: Enabled toggle + animation, status pills (Spotify/Game), fade slider, Playlists card (collapsible, per age, covers, Change hover), Age Intros row with pips and crown, After match
- [ ] Row fire animation for the playing age, crown colours
- [ ] Age Intros: overview + age pages, chips, tray, playing glow (overlap-correct), undo/redo, right-click remove, wheel scroll
- [ ] Presets with autosave, import/share, rename
- [ ] Custom songs (links, now playing, search), playlist picker, mosaics
- [ ] Octopath emblem: spiked frame, animation, tooltips, glow
- [ ] Good-to-go / login flow, own Spotify app (hidden option), access/BYO dialogs
- [ ] Auto-update between matches, "Updated to x.y" notice, game-running guard
- [ ] Steam env cleanup, uninstall removes the launch option, keep on screen, DPI 100–200%
- [ ] Logs + diagnostics (`--selftest`)

## Design rules (already decided)
- **Looks the same as 1.0.9:** same layout, sizes, colours, fonts (Segoe UI, same px sizes), cards, chips, emblem, buttons and cog menu as the Python app. The only differences allowed are already approved ones (either/or tray, chip stacking rule, Add a song). Every page built gets a side-by-side screenshot comparison against 1.0.9 at 100% and 150% scale before it counts as done.
- **Squeezed chips** (tray and list): the normal stacking order stays, so the right neighbour is on top. The playing or hovered chip is never raised. The green highlight (playing glow and hover ring) stays under the right neighbour. The audio/play icon is always drawn on top of everything.
- **Either/or Octopath tray:** with no songs of your own, Octopath is shown normally with no emblem. With 1 or more of your own songs, Octopath folds into the spiked emblem automatically and only one group is visible at a time; a compact "Yours (n)" count chip switches back.
- **Add a song** (requested 3 times):
  - open one of your own Spotify playlists and tick songs to include
  - a clear one-line drag-and-drop hint
  - a dashed drop zone that lights up while you drag a song or link over the window

## Backlog, folded in
- **M2:** either/or tray + squeezed-chip stacking rule (see Design rules).
- **M3 (explicit, requested 3×):** Add a song: pick songs from your own Spotify playlists, a drag-drop hint line, and a dashed drop zone that lights up while dragging.
- **M4:** lobby playlists (a new adapter event).

## Milestones (rough effort, one dev with an agent)
| M | Content | Effort |
|---|---|---|
| M1 vertical slice | core skeleton, settings migration (read-only), log tail + AoE4 adapter, Spotify auth + age switching with fades, UI: panel + Age Intros switch using 1.0.9's sizes (main ~416×453, intros 520 wide, centred widen, title bar fixed, extra height downward). The earlier "fixed 520×640 window" idea was never approved by Capstar and is dropped. If WebView2 can't resize without blank frames, use the smallest workaround that keeps the look identical. Done when a real match switches music and it's logged. | 1.5–2 wk |
| M2 | Intros complete (presets, autosave, glow with the stacking rule, emblem, either/or tray), fire/crown | 2 wk |
| M3 | **Add a song**: pick from your Spotify playlists, hint line, dashed drop zone that lights up while dragging; plus search/links, playlist picker, covers/mosaics | 1.5 wk |
| M4 | After-match, replays, pause watcher, lobby playlists, Steam hook/env, updater + installer | 1.5–2 wk |
| M5 | Parity pass, beta next to 1.0.9, migration from 1.0.x, release 1.1 | 1 wk |
Total: about 8–9 weeks part-time.

## Testing
- **Log replay:** recorded AoE4 logs (start, age-ups, victory, replay, lobby, crash/rotation) are fed into `logtail`/adapter/switcher with a fake clock and a fake Spotify. Asserts cover the exact Spotify calls and fades. No real matches needed.
- Spotify client tested against a mock HTTP server; settings migration tested with snapshots of real old JSON files.
- UI: Playwright on the WebView2 build (pages, hover, drag-drop) plus screenshot comparisons. A short real-screen frame capture is used for page switching only to confirm 0 bad frames.
- CI: `cargo test` + UI tests on Windows runners; the installer is smoke-tested silently.

## Build, size, memory
- `cargo tauri build`. Targets: installer under 8 MB (vs ~35 MB now), idle RAM about 40–60 MB with the panel open (WebView2 shared runtime), about 10 MB with only the switcher running (the window is fully closed when hidden), CPU about 0% between events.
- WebView2 comes with Windows 11; the bootstrapper is included for Windows 10.

## Risks
- Spotify API changes / quota on the dev app: keep the same app id and scopes; use the mock for tests.
- WebView2 memory and first start (~300 ms): open the window on demand; the switcher stays headless.
- AoE4 log format changes: the adapter is isolated and replay fixtures catch it.
- Settings migration bugs: one-way copy (1.x files untouched); 1.1 can be removed without harm.
- Parity creep: nothing new before M5 except the listed backlog.

## 1.0.9 -> 1.1 public upgrade (done, not published)
- 1.0.9 updater: GitHub releases/latest, tag > 1.0.9, first .exe asset (size + sha256 digest), runs it /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /FROMSWITCHER=1 (manual: /RELAUNCH=1), only between matches.
- installer/setup11.iss: SAME AppId/name/folder as 1.0.x -> in-place upgrade (removes _internal/source, ARP -> 1.1.0, launch option + user args untouched, avoids 1.0.9 uninstaller unmuting/removing option).
- Post-install: --migrate-109 --cleanup (config, intros/presets, playlists, covers, refresh token, saved music level; verified counts -> import.json; then deletes 1.0.9 data; leftovers finished on first start).
- Waits while AoE4 runs (silent) / refuses (interactive). Bundled WebView2 bootstrapper (/silent /install) if runtime missing.
- Release asset name: AoE4.Spotify.Setup-1.1.0.exe (build: out\AoE4 Spotify Setup 1.1.0.exe).
- E2E: tools/e2e_upgrade.ps1 (sandbox profile, local release server, 1.0.9's own auto_update) 23/23 PASS.
