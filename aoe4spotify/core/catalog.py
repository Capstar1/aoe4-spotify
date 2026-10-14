"""Game catalogue: phases, factions and intro songs from the active game adapter, plus the song-list helpers the
core needs (canonical chip order, default pools, playlist size). No UI imports: settings, Spotify and the switcher
use this directly; the UI re-exports it."""

import os
from aoe4spotify.core.runtime import DATA
from aoe4spotify.games.registry import active as game

COVERS = os.path.join(DATA, "covers")              # cover thumbnails: playlists <id>_<snapshot>.jpg, tracks track_<id>.jpg
_G = game()                                        # the active game supplies phases, factions and intro songs
AGES = list(_G.phases)
CIV_LIST = list(_G.factions)                       # (faction key, label)
SONGS = list(_G.intro_songs)                       # key, song, character (portrait), Spotify track, ring colour; + your songs
BUILTIN_SONGS = list(SONGS)
SONG_BY_URI = {s[3]: s for s in SONGS}

def custom_key(uri): return "c_" + uri.split(":")[-1]
def load_custom_songs(u):
    """Your own intro songs (user settings "custom_songs": [{uri, name, artist}]) appended to SONGS."""
    SONGS[:] = BUILTIN_SONGS + [(custom_key(c["uri"]), c.get("name") or "Song", c.get("artist") or "", c["uri"], "#1DB954")
                                for c in (u.get("custom_songs") or []) if isinstance(c, dict) and str(c.get("uri", "")).startswith("spotify:track:")]
    SONG_BY_URI.clear(); SONG_BY_URI.update({s[3]: s for s in SONGS})
def song_sorted(lst):
    """One canonical chip order everywhere: tray order (built-ins, then your songs in add order); unknowns last."""
    idx = {x[3]: i for i, x in enumerate(SONGS)}; lst = list(dict.fromkeys(lst or []))
    return sorted(lst, key=lambda u: (idx.get(u, len(idx)), lst.index(u)))
def normalize_pools(u):
    """Sort every stored intro pool canonically (returns True if anything changed)."""
    ip = u.get("intro_pools"); ch = False
    if isinstance(ip, dict):
        for age in ip.values():
            if isinstance(age, dict):
                for civ, lst in age.items():
                    if isinstance(lst, list) and song_sorted(lst) != lst: age[civ] = song_sorted(lst); ch = True
    return ch
def default_pool(base_cfg, civ):
    bi = base_cfg.get("boss_intro") or {}
    return list((bi.get("pools") or {}).get(civ) or bi.get("default") or [])
def track_cover(uri): return os.path.join(COVERS, "track_%s.jpg" % uri.split(":")[-1])
def _pl_total(p):
    for k in ("items", "tracks"):                   # Feb 2026 API renamed playlist "tracks" to "items"
        v = p.get(k)
        if isinstance(v, dict) and v.get("total") is not None:
            try: return int(v["total"])
            except (TypeError, ValueError): pass
    return 0
def playlist_total(sp, pid):
    """Song count of a playlist for the shuffle start: old (tracks) or new (items) field, then the items endpoint; 0 if unknown."""
    c, pl = sp._api("GET", "/playlists/%s?fields=items.total,tracks.total" % pid)
    n = _pl_total(pl) if c == 200 and isinstance(pl, dict) else 0
    if n <= 0:
        c, r = sp._api("GET", "/playlists/%s/items?limit=1&fields=total" % pid)
        try: n = int(r.get("total") or 0) if c == 200 and isinstance(r, dict) else 0
        except (TypeError, ValueError): n = 0
    return max(0, n)
