"""AoE4 -> Spotify age playlist switcher. Python stdlib + Pillow (panel). MIT licensed (see LICENSE).

How it works, in short:
- AoE4: while RelicCardinal.exe runs, it reads Documents/My Games/Age of Empires IV/warnings.log,
  where the game writes "Age up started/complete ... for player id N" lines.
- Spotify: Web API with PKCE login (no client secret; the Client ID in config.json is public).
  Needs Spotify Premium. Calls: /me/player/play, /volume, /shuffle, /repeat, /playlists/{id}.
- Token: your Spotify login token is stored ONLY on your PC in %APPDATA%/AoE4Spotify/token.json.
- Steam: the installer sets AoE4's Steam launch option to `"<install dir>/AoE4 Spotify.exe" %command%`,
  so Steam starts this app with the game; it exits ~10s after the game closes.

Tails AoE4's warnings.log and switches Spotify playlists when YOU age up.
Run:  python aoe4_spotify.py            (normal)
      python aoe4_spotify.py --login    (just do Spotify login)
      python aoe4_spotify.py --dry-run warnings.log [DataCRC files in match order]  (no Spotify calls)
"""
import os, sys, time, webbrowser

from aoe4spotify.core import runtime as _runtime
from aoe4spotify.core import settings as _settings
from aoe4spotify.core import spotify as _spotify
from aoe4spotify.core import playback as _playback
from aoe4spotify.core import access as _access
from aoe4spotify.core import updater as _updater
from aoe4spotify.core import gui as _gui
from aoe4spotify.core import byo as _byo
from aoe4spotify.core import app as _app
from aoe4spotify.games import aoe4 as _aoe4
from aoe4spotify.games import aoe4_setup as _aoe4_setup
from aoe4spotify.games import base as _base

def _publish(mod):
    g = globals()
    for key, value in vars(mod).items():
        if key.startswith("__"):
            continue
        g[key] = value

for _mod in (_runtime, _settings, _spotify, _playback, _aoe4, _aoe4_setup, _base, _access, _updater, _gui, _byo, _app):
    _publish(_mod)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FATAL: %r" % exc)
        raise
