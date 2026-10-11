# AoE4 Spotify

Age-based music for **Age of Empires IV**: a Dark Age playlist plays when your match starts,
and Spotify switches to your Feudal, Castle and Imperial playlists the moment **you** age up
(it detects which player you are, so other players' age-ups don't count).
Switches fade out/in smoothly, start on a random track, shuffle, and loop the playlist.

**Boss intro:** when you reach Imperial Age, one civ-themed boss intro from the OCTOPATH TRAVELER
soundtrack plays first (one of the 8 short *For ...* themes, e.g. *For Light* for French, *For Master* for Japanese,
*For Freedom* only for desert civs), then your Imperial playlist continues. Each civ has its own theme plus 1-2 related ones,
and never gets the same one twice in a row.

Windows only. Python standard library only. MIT licensed.

## Requirements

- **Spotify Premium.** The Spotify Web API only lets Premium accounts control playback.
- **Spotify app access.** The bundled Client ID belongs to a Spotify app in Development Mode,
  so the app owner must add your Spotify account email under *User Management* in the
  Spotify developer dashboard before your login works. To avoid that, use your own app (see below).
- The Spotify desktop app open while you play.
- Age of Empires IV on Steam.

## Install

1. Download `AoE4 Spotify Setup.exe` from the [Releases](../../releases) page.
2. Run it. It's unsigned, so Windows SmartScreen may warn: *More info -> Run anyway*.
   No admin rights needed; it installs to `%LOCALAPPDATA%\Programs\AoE4 Spotify`.
3. **If Steam is running, Setup closes it** (after you click Continue), adds itself to
   Age of Empires IV's Steam launch options, and reopens Steam. Your existing launch options are kept.
4. At the end your browser opens Spotify: log in and click Agree.

Then just start AoE4 from Steam. Steam launches the game through AoE4 Spotify, which follows the
game's log and exits about 10 seconds after the game closes. Nothing runs when you're not playing.

Uninstall from *Settings -> Apps -> Installed apps*. Steam is closed and reopened the same way, and
your original launch options are restored exactly.

## How it works

- Reads `Documents\My Games\Age of Empires IV\warnings.log`, where the game writes
  `Age up started/complete ... for player id N` lines; your player id comes from the match's
  `LogFiles\DataCRC*.txt` player map.
- Spotify Web API with PKCE login (no client secret). The login token is stored only on your PC
  in `%APPDATA%\AoE4Spotify\token.json`.
- Steam launch option for app 1466860 in `Steam\userdata\<id>\config\localconfig.vdf`:
  `"<install dir>\AoE4 Spotify.exe" %command%` (a backup copy is made before editing).

## Configuration

`config.json` next to the exe: `client_id`, `playlists` (`dark`, `feudal`, `castle`, `imperial`
as `spotify:playlist:...` URIs), `fade_seconds` (0 = no fade), `shuffle`, `repeat`,
`device_id` and `log_path` (optional), and `boss_intro`: `enabled`, `ages` (default
`["imperial"]`), `pools` (internal civ id such as `japanese`, `mongol_ha_gol`, `french_ha_01` ->
list of `spotify:track:` URIs) and `default` (for civs not listed).

## Build from source

See [build.md](build.md). In short: Python 3.11+, Inno Setup 6, then `build.bat`
(PyInstaller -> `dist\AoE4 Spotify.exe`, Inno Setup -> `out\AoE4 Spotify Setup.exe`).

To use your own Spotify app, create one at developer.spotify.com, add the redirect URI
`http://127.0.0.1:8888/callback`, and put its Client ID in `config.json`.

## License

MIT, see [LICENSE](LICENSE).
