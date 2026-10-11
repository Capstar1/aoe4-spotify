# AoE4 Spotify

**Version 0.1 (early release).** Age-based music for **Age of Empires IV** on Windows.

## Features

- **Age playlists:** a Dark Age playlist plays when your match starts, and Spotify switches to your
  Feudal, Castle and Imperial playlists the moment **you** age up (it works out which player you are,
  so other players' age-ups don't count).
- **Fade:** switches fade out and back in smoothly (0-5 s, default 2 s, 0 = off).
- **Shuffle / repeat:** each playlist starts on a random track, shuffles, and loops.
- **Age 4 Intro theme:** when you reach Imperial Age, one civ-themed theme from the OCTOPATH TRAVELER
  soundtrack plays first (one of the 8 *For ...* themes, e.g. *For Light* for French, *For Master* for
  Japanese), then your Imperial playlist continues. Each civ has its own theme plus 1-2 related ones and
  never gets the same one twice in a row.
- **Spotify auto-launch:** if Spotify isn't running, it is started minimized and playback goes to
  this PC automatically.
- **Steam launch option:** runs only alongside the game. Steam starts AoE4 through AoE4 Spotify, which
  exits about 10 seconds after the game closes. Nothing runs when you're not playing.
- **Control panel** (Desktop / Start Menu shortcut *AoE4 Spotify*): on/off switch, Spotify and game
  status, change or revert each age's playlist, Age 4 Intro theme toggle, fade slider, Log in, Updates,
  Open log, Uninstall. Your settings are saved in `%APPDATA%\AoE4Spotify\config.json`.

## Requirements

- Windows 10/11 and Age of Empires IV on **Steam**.
- **Spotify Premium.** The Spotify Web API only lets Premium accounts control playback.
- The Spotify desktop app installed.
- **Spotify app access.** The bundled Client ID belongs to a Spotify app in Development Mode, so the
  app owner must add your Spotify account email under *User Management* in the Spotify developer
  dashboard before your login works. To avoid that, use your own Spotify app (see below).

## Install

1. Download `AoE4 Spotify Setup.exe` from the [Releases](../../releases) page.
2. Run it. It's unsigned, so Windows SmartScreen may warn: *More info -> Run anyway*.
   No admin rights needed; it installs to `%LOCALAPPDATA%\Programs\AoE4 Spotify`.
3. **If Steam is running, Setup closes it** (after you click Continue), adds itself to
   Age of Empires IV's Steam launch options, and reopens Steam. Existing launch options are kept.
4. At the end your browser opens Spotify: log in and click Agree.

Then start AoE4 from Steam as usual.

Uninstall from the control panel or *Settings -> Apps -> Installed apps*. Steam is closed and reopened
the same way, and your original launch options are restored.

## How it works

- Reads `Documents\My Games\Age of Empires IV\warnings.log`, where the game writes
  `Age up started ... for player id N` lines; your player id comes from the match's player list.
- Spotify Web API with PKCE login (no client secret). The login token is stored only on your PC
  in `%APPDATA%\AoE4Spotify\token.json`.
- Steam launch option for app 1466860 in `Steam\userdata\<id>\config\localconfig.vdf`:
  `"<install dir>\AoE4 Spotify.exe" %command%` (a backup is made before editing).

## Configuration

`config.json` next to the exe holds the defaults: `client_id`, `playlists` / `default_playlists`
(`dark`, `feudal`, `castle`, `imperial` as `spotify:playlist:...` URIs), `fade_seconds`, `shuffle`,
`repeat`, optional `device_id` / `log_path`, and `boss_intro` (the Age 4 Intro theme): `enabled`,
`ages` (default `["imperial"]`), `pools` (internal civ id -> list of `spotify:track:` URIs) and
`default` (for civs not listed). The control panel's settings are layered on top and never change
this file.

## Build from source

See [build.md](build.md). In short: Python 3.11+, Inno Setup 6, then `build.bat`
(PyInstaller + Pillow -> `dist\AoE4 Spotify.exe`, Inno Setup -> `out\AoE4 Spotify Setup.exe`).

To use your own Spotify app, create one at developer.spotify.com, add the redirect URI
`http://127.0.0.1:8888/callback`, and put its Client ID in `config.json`.

## Credits

Made by Capstar, built with Grok Bot.

## License

MIT, see [LICENSE](LICENSE).
