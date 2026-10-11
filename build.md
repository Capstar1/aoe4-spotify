# Building AoE4 Spotify from source

Files: `aoe4_spotify.py` (the whole app, Python stdlib only), `config.json`
(public Client ID + playlist URIs, no secrets), `setup.iss` (Inno Setup installer), `build.bat`.

Requirements: Windows, Python 3.11+, Inno Setup 6 (`winget install JRSoftware.InnoSetup`).

1. Run it directly (optional): `python aoe4_spotify.py`
   Dry run against a saved log, no Spotify calls: `python aoe4_spotify.py --dry-run warnings.log`
2. Build the app exe with PyInstaller:
   `pyinstaller --noconfirm --onedir --windowed --name "AoE4 Spotify" --icon app.ico --add-data "app.ico;." --add-data "app.png;." --add-data "gtg_frames;gtg_frames" --add-data "assets;assets" aoe4_spotify.py`
   (needs `pip install pyinstaller pillow`; `python make_icon.py` makes `app.ico` + `app.png` (green circle with a dark "IV"); Pillow draws the panel's round shapes)
   -> `dist\AoE4 Spotify.exe`
3. Build the installer: `ISCC.exe setup.iss` -> `out\AoE4 Spotify Setup.exe`
   (it embeds `dist\AoE4 Spotify.exe`, `config.json` and this source folder).

Or just run `build.bat`, which does steps 2 and 3.

How it runs: the installer sets Age of Empires IV's Steam launch option (app id 1466860) to
`"<install dir>\AoE4 Spotify.exe" %command%` in every `Steam\userdata\<id>\config\localconfig.vdf`
(if Steam is running, Setup asks to close it (Continue/Cancel; silent installs just do it),
runs `steam.exe -shutdown`, waits up to 30 s, force-closes only as a last resort, and reopens
Steam afterwards; a `.aoe4spotify.bak` copy is made first, and existing options are kept after ours).
Steam then starts the app with the game command; the app starts the game, follows the log and exits
~10s after RelicCardinal.exe closes. Uninstall restores the previous launch option exactly.
App flags: `--panel` (control panel window; the Desktop and Start Menu shortcuts use it),
`--set-launch-option`, `--remove-launch-option`; no arguments = Spotify login only.
Panel settings are saved to `%APPDATA%\AoE4Spotify\config.json` and overlay the install `config.json`
(`default_playlists` there are what Revert restores).

To use your own Spotify app: create one at developer.spotify.com, add the redirect URI
`http://127.0.0.1:8888/callback`, and put its Client ID in `config.json`.
The login token is written to `%APPDATA%\AoE4Spotify\token.json` and must never be shared.

Testing the Steam close/reopen without touching real Steam: run Setup with
`/STEAMPROC=<dummy.exe> /STEAMEXE=<path to dummy>` and set `AOE4SPOTIFY_STEAM_PATH` to a fake Steam folder.

## Good-to-go window art

`gtg_frames\` holds the animation shown after login: every frame of the source GIF (cropped to the circle, watermark corner painted over, ~650 KB of JPEGs) plus `frames.json` with the original per-frame timing. It is bundled into the exe with `--add-data`. Regenerate with `python make_gtg_frames.py source.gif`.

## Test builds

`ISCC /DTEST setup.iss` builds *AoE4 Spotify TEST Setup.exe* with its own AppId, folder and shortcuts, so upgrade tests never touch a real install (it also skips deleting `%APPDATA%\AoE4Spotify` on uninstall).

## Editor art

`assets\portraits\` (8 OCTOPATH TRAVELER portraits, 96 px) and `assets\flags\` (23 AoE4 civ flags from aoe4world/overlay, 60x32 px, plus a neutral `_unknown.png`) are bundled into the exe with `--add-data "assets;assets"`. Regenerate with `python make_editor_assets.py <portrait dir> <flag dir>`.


## Folder build

The app is built with PyInstaller `--onedir` (`dist\AoE4 Spotify\AoE4 Spotify.exe` + `_internal\`), and the installer copies the whole folder. A one-file exe unpacks itself to `%TEMP%\_MEI*` on every start and can fail to clean it up when it starts other processes. Upgrading over an old one-file install replaces the exe and adds `_internal`. Child processes get a clean environment (`PYINSTALLER_RESET_ENVIRONMENT=1`, no `_MEI`/`_PYI` variables).

## Playlist covers and previews

The panel fetches each playlist's name, images and snapshot_id (`GET /playlists/{id}`), downloads the smallest image at least ~1.5x the 30 px thumbnail and caches it in `%APPDATA%\AoE4Spotify\covers\<playlist id>_<snapshot>.jpg` (older snapshots are deleted; offline uses the cache, else the age icon). In the editor a click (no drag, < 4 px movement) on a chip plays that track via the app's login (`Spotify.preview`/`pause`). Tests: `ctest.py` (covers, simulated API), `etest.py` (editor incl. preview), `ptest.py`, `utest.py`, `wtest.py`, `e2e.ps1` (installer with a fake Steam).

