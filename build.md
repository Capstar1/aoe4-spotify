# Building AoE4 Spotify from source

Files: `aoe4_spotify.py` (the whole app, Python stdlib only), `config.json`
(public Client ID + playlist URIs, no secrets), `setup.iss` (Inno Setup installer), `build.bat`.

Requirements: Windows, Python 3.11+, Inno Setup 6 (`winget install JRSoftware.InnoSetup`).

1. Run it directly (optional): `python aoe4_spotify.py`
   Dry run against a saved log, no Spotify calls: `python aoe4_spotify.py --dry-run warnings.log`
2. Build the app exe with PyInstaller:
   `pyinstaller --noconfirm --onefile --windowed --name "AoE4 Spotify" --icon app.ico aoe4_spotify.py`
   (needs `pip install pyinstaller pillow`; `python make_icon.py` makes `app.ico`; Pillow draws the panel's round shapes)
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

`gtg_frames\` holds the animated face shown after login (9 small JPEGs, bundled into the exe with `--add-data`). They were made with `make_gtg_frames.py source.gif`: only the opening face frames are kept, the face is cropped and the watermark corner painted over.

