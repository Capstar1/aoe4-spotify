# AoE4 Spotify

**Version 0.4.3 (early release).** Age-based music for **Age of Empires IV** on Windows.

## Features

- **Age playlists:** a Dark Age playlist plays when your match starts, and Spotify switches to your
  Feudal, Castle and Imperial playlists the moment **you** age up (it works out which player you are,
  so other players' age-ups don't count).
- **Fade:** switches fade out and back in smoothly (0-5 s, default 2 s, 0 = off).
- **Shuffle / repeat:** each playlist starts on a random track, shuffles, and loops.
- **Age Intros:** when you enter an age, a short civ-themed intro can play before that age's playlist.
  Imperial is on by default with one of the 8 OCTOPATH TRAVELER *For ...* themes per civ (e.g. *For Light*
  for French, *For Master* for Japanese); a civ never gets the same theme twice in a row. Dark (match start),
  Feudal and Castle start empty: turn them on and give civs songs if you want intros there too. A civ with
  no songs simply plays the playlist.
- **Add your own intro songs easily:** drag songs straight from the Spotify app onto the Age Intros window, or press + to search Spotify, add what's playing, or paste a link. Any civ can be left empty (no intro, its playlist just plays).
- **Smooth fades:** when Spotify plays on this PC, switches fade Spotify's own Windows app volume (smooth, no network lag) down to a quiet point, start the new music there, and fade back in; otherwise the Spotify volume is used, paced so it never lags. Your volume is always put back exactly.
- **Intro presets & sharing:** keep several intro setups as presets (a built-in Default plus your own), switch between them from the bar at the top of the Age Intros editor (undo works), and share one with a friend: Share copies a short code, Import pastes one, previews it and adds it as a new preset, including any of your own songs it uses.
- **Age Intros editor:** opens on an overview of the four ages (on/off switch, how many civs have songs,
  a peek at the songs). Click an age to edit its list: drag songs from the tray (OCTOPATH themes, plus
  *Yours*: add any Spotify song with the green +, right-click to remove) onto a civ; drag out, right-click
  or click x to remove. Every civ shows its flag. Click a chip to hear the song (a soft green glow marks it;
  click again to pause). Ctrl+Z / Ctrl+Y undo and redo across all ages. Changes apply from the next match.
- **App window** (Desktop / Start Menu shortcut *AoE4 Spotify*): on/off switch,
  Spotify chip (click to log in) and game status, change or revert each age's playlist (each row shows the playlist's cover; click it to open the playlist in Spotify), Age Intros
  row (opens the editor), fade slider. The gear menu has *Open log* and *Uninstall*. Settings are saved
  in `%APPDATA%\AoE4Spotify\config.json`.
- **One-click updates:** when a newer release exists, the gear gets a green dot and a green
  *Update x.y* pill appears in the header. One click downloads the Setup (size and checksum verified),
  upgrades silently and reopens the panel. Login, settings, shortcuts and the Steam launch option are kept.
- **You're good to go:** after the Spotify login a small window confirms Spotify is connected and AoE4
  starts with the game (with a Fix button if the Steam launch option is missing).
- **Spotify auto-launch:** if Spotify isn't running, it is started minimized and playback goes to
  this PC automatically.
- **Steam launch option:** runs only alongside the game. Steam starts AoE4 through AoE4 Spotify, which
  exits about 10 seconds after the game closes. Nothing runs when you're not playing.
- **New icon:** a green "IV" badge for the app, installer, shortcuts and windows.

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
   (Upgrades skip this when the launch option is already set.)
4. At the end your browser opens Spotify: log in and click Agree.

Then start AoE4 from Steam as usual. Later versions can be installed from the app's Update pill.

Uninstall from the app's gear menu or *Settings -> Apps -> Installed apps*. Steam is closed and
reopened the same way, and your original launch options are restored.

## How it works

- Reads `Documents\My Games\Age of Empires IV\warnings.log`, where the game writes
  `Age up started ... for player id N` lines; your player id comes from the match's player list.
- Spotify Web API with PKCE login (no client secret). The login token is stored only on your PC
  in `%APPDATA%\AoE4Spotify\token.json`.
- Steam launch option for app 1466860 in `Steam\userdata\<id>\config\localconfig.vdf`:
  `"<install dir>\AoE4 Spotify.exe" %command%` (a backup is made before editing).
- Update check: GitHub's `releases/latest` API for this repo, compared with the installed version.

## Configuration

`config.json` next to the exe holds the defaults: `client_id`, `playlists` / `default_playlists`
(`dark`, `feudal`, `castle`, `imperial` as `spotify:playlist:...` URIs), `fade_seconds`, `shuffle`,
`repeat`, optional `device_id` / `log_path`, and `boss_intro` (the Age Intros): `enabled`,
`ages` (default `["imperial"]`), `pools` (internal civ id -> list of `spotify:track:` URIs) and
`default` (for civs not listed). The app and editor settings are layered on top
(`%APPDATA%\AoE4Spotify\config.json`, editor lists per age as `intro_pools`) and never change this file.

## Build from source

See [build.md](build.md). In short: Python 3.11+, Inno Setup 6, then `build.bat`
(PyInstaller folder build + Pillow -> `dist\AoE4 Spotify\`, Inno Setup -> `out\AoE4 Spotify Setup.exe`).

To use your own Spotify app, create one at developer.spotify.com, add the redirect URI
`http://127.0.0.1:8888/callback`, and put its Client ID in `config.json`.

## Credits

Made by Capstar, built with Grok Bot.

- Civ flag icons from [aoe4world/overlay](https://github.com/aoe4world/overlay) (`src/assets/flags`).
- Character portraits and the *For ...* themes are from OCTOPATH TRAVELER (music is played through
  Spotify, not included).
- The good-to-go animation is a PixVerse-generated GIF (watermark removed).

Age of Empires IV and its assets are trademarks/copyright of Microsoft / World's Edge. OCTOPATH TRAVELER
is a trademark of Square Enix. This is an unofficial, non-commercial fan project, not affiliated with or
endorsed by Microsoft, World's Edge or Square Enix.

## License

MIT for the code, see [LICENSE](LICENSE). Third-party game assets (flags, portraits) remain the property
of their owners.
