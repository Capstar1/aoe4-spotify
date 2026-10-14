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

if sys.argv[1:2] == ["--fire-preview"]:            # dev preview: run on a throwaway copy of your settings (never saved back)
    import shutil, tempfile
    _real = os.path.join(os.environ.get("APPDATA") or "", "AoE4Spotify"); _tmp = tempfile.mkdtemp(prefix="aoe4fire_")
    os.makedirs(os.path.join(_tmp, "AoE4Spotify"))
    for _n in ("config.json", "playlist_names.json"):
        try: shutil.copy(os.path.join(_real, _n), os.path.join(_tmp, "AoE4Spotify", _n))
        except Exception: pass
    try: shutil.copytree(os.path.join(_real, "covers"), os.path.join(_tmp, "AoE4Spotify", "covers"))
    except Exception: pass
    os.environ["APPDATA"] = _tmp
    os.environ["AOE4SPOTIFY_MUTEX_SUFFIX"] = os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX", "") + "_firepreview"

from aoe4spotify.core import runtime as _runtime
from aoe4spotify.core import settings as _settings
from aoe4spotify.core import spotify as _spotify
from aoe4spotify.core import playback as _playback
from aoe4spotify.core import access as _access
from aoe4spotify.core import updater as _updater
from aoe4spotify.core import byo as _byo
from aoe4spotify.core import app as _app
from aoe4spotify.games import registry as _registry
from aoe4spotify.games import aoe4 as _aoe4          # the games this build ships register themselves on import
from aoe4spotify.games import aoe4_setup as _aoe4_setup
from aoe4spotify.games import base as _base

def _publish(mod):
    g = globals()
    for key, value in vars(mod).items():
        if key.startswith("__"):
            continue
        g[key] = value

for _mod in (_runtime, _settings, _spotify, _playback, _aoe4, _aoe4_setup, _base, _registry, _access, _updater, _byo, _app):
    _publish(_mod)

def __getattr__(name):                             # UI names (panel widgets, editor, ...) load on first use only
    from aoe4spotify.core import gui as _gui
    try: return getattr(_gui, name)
    except AttributeError: raise AttributeError(name) from None

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("FATAL: %r" % exc)
        raise
