"""Spotify library helpers, covers, songs, civs and the shared Art painter.

Split out of core/gui.py in 1.0.9; behaviour unchanged.
"""

import json, os, re, time, urllib.error, urllib.parse, urllib.request, webbrowser
from aoe4spotify.core.runtime import ASSETS, DATA, atomic_write, log
from aoe4spotify.games.registry import active as game
from aoe4spotify.core.spotify import Spotify
from aoe4spotify.core.ui.glow import chip_px, even_px, ink_centre

from aoe4spotify.core.branding import RELEASES_URL
from aoe4spotify.core.catalog import _G, AGES, BUILTIN_SONGS, CIV_LIST, COVERS, SONGS, SONG_BY_URI, _pl_total, custom_key, default_pool, load_custom_songs, normalize_pools, playlist_total, song_sorted, track_cover   # (moved to core; re-exported)
NAMES_CACHE = os.path.join(DATA, "playlist_names.json")
def http_get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r: return r.read()
def pick_image(images, need):
    """Smallest Spotify image that is at least `need` px wide (else the largest one)."""
    imgs = [i for i in (images or []) if isinstance(i, dict) and i.get("url")]
    if not imgs: return None
    sized = sorted(imgs, key=lambda i: i.get("width") or 10 ** 6)
    for i in sized:
        if (i.get("width") or 10 ** 6) >= need: return i["url"]
    return sized[-1]["url"]
def cover_file(pid):
    """Cached cover for a playlist (newest snapshot), or None."""
    try: fs = [f for f in os.listdir(COVERS) if f.startswith(pid + "_")]
    except OSError: return None
    if not fs: return None
    return max((os.path.join(COVERS, f) for f in fs), key=os.path.getmtime)
def update_cover(sp, pid, need=96):
    """GET name + images + snapshot; download the cover if this snapshot isn't cached. Returns (name, path)."""
    c, r = sp._api("GET", "/playlists/%s?fields=name,images,snapshot_id" % pid)
    if c != 200 or not isinstance(r, dict): return None, cover_file(pid)
    snap = re.sub(r"[^A-Za-z0-9]", "", str(r.get("snapshot_id") or "0"))[:16] or "0"
    path = os.path.join(COVERS, "%s_%s.jpg" % (pid, snap))
    url = pick_image(r.get("images"), need)
    if url and not os.path.exists(path):
        try:
            data = http_get(url); os.makedirs(COVERS, exist_ok=True)
            atomic_write(path, data, "wb")
            for f in os.listdir(COVERS):                          # drop older snapshots of this playlist
                if f.startswith(pid + "_") and os.path.join(COVERS, f) != path:
                    try: os.remove(os.path.join(COVERS, f))
                    except OSError: pass
        except Exception as e: log("Cover download failed: %r" % e)
    return r.get("name"), (path if os.path.exists(path) else cover_file(pid))
def open_playlist(pid):
    """Open a playlist in the Spotify app; fall back to the web player."""
    try: os.startfile("spotify:playlist:" + pid); return "app"
    except Exception:
        webbrowser.open("https://open.spotify.com/playlist/" + pid); return "web"
ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII")
RE_PLAYLIST = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z]+/)?playlist/|spotify:playlist:)([A-Za-z0-9]{22})")
def fetch_track(sp, uri, need=96):
    """(name, artist) of a Spotify track; caches its album cover for the chip. None if not found."""
    c, r = sp._api("GET", "/tracks/" + uri.split(":")[-1])
    if c != 200 or not isinstance(r, dict) or not r.get("name"): return None
    url = pick_image((r.get("album") or {}).get("images"), need)
    if url:
        try:
            os.makedirs(COVERS, exist_ok=True); data = http_get(url); p = track_cover(uri)
            atomic_write(p, data, "wb")
        except Exception as e: log("Track cover download failed: %r" % e)
    return r["name"], ", ".join(a_.get("name", "") for a_ in (r.get("artists") or [])[:2])
def store_track(r, need=96):
    """(uri, name, artist) from a Spotify track object; caches its album cover for the chip."""
    uri = r.get("uri") or ("spotify:track:" + r.get("id", ""))
    url = pick_image((r.get("album") or {}).get("images"), need)
    if url and not os.path.exists(track_cover(uri)):
        try:
            os.makedirs(COVERS, exist_ok=True); data = http_get(url); p = track_cover(uri)
            atomic_write(p, data, "wb")
        except Exception as e: log("Track cover download failed: %r" % e)
    return uri, r.get("name") or "Song", ", ".join(a_.get("name", "") for a_ in (r.get("artists") or [])[:2])
LIB_SCOPES = ("playlist-read-private", "playlist-read-collaborative", "user-library-read")
from aoe4spotify.core.branding import LIKED_URI
LIKED_ID = "liked"
_MYLIB = {}                                         # last good list, so a reopened picker shows it instantly
def lib_scopes_ok(sp):
    t = getattr(sp, "tok", None) or Spotify._disk_tok() or {}
    have = set(str(t.get("scope") or "").split())
    return all(x in have for x in LIB_SCOPES)
def _next_path(r):
    n = r.get("next") if isinstance(r, dict) else None
    return n.split("/v1", 1)[1] if isinstance(n, str) and "/v1/" in n else None
def my_library(sp, cap=1000):
    """('ok', items) | ('scope', []) needs Reconnect | ('login', []) | ('off', []). Liked Songs first, then every page of /me/playlists."""
    if not (getattr(sp, "tok", None) or Spotify._disk_tok()): return "login", []
    if not lib_scopes_ok(sp): return "scope", []
    c, r = sp._api("GET", "/me/tracks?limit=1")
    if c in (401, 403): return "scope", []
    if c != 200 or not isinstance(r, dict): return "off", []
    try: n = int(r.get("total") or 0)
    except (TypeError, ValueError): n = 0
    out = [{"uri": LIKED_URI, "name": "Liked Songs", "n": n, "liked": True}]
    path = "/me/playlists?limit=50"; seen = set()
    while path and len(out) < cap:
        c, r = sp._api("GET", path)
        if c in (401, 403): return "scope", []
        if c != 200 or not isinstance(r, dict): break
        for p in r.get("items") or []:
            if not isinstance(p, dict) or not p.get("id") or p["id"] in seen: continue
            seen.add(p["id"])
            snap = re.sub(r"[^A-Za-z0-9]", "", str(p.get("snapshot_id") or "0"))[:16] or "0"
            out.append({"uri": "spotify:playlist:" + p["id"], "pid": p["id"], "name": str(p.get("name") or "Playlist"),
                        "n": _pl_total(p), "snap": snap, "url": pick_image(p.get("images"), 192)})
        path = _next_path(r)
    _MYLIB.update(t=time.time(), items=out); return "ok", out
def lib_cover(it, fetch=True):
    """Cover for a library playlist, in the panel's <pid>_<snapshot>.jpg cache (downloaded once per snapshot)."""
    pid = it.get("pid")
    if not pid: return None
    path = os.path.join(COVERS, "%s_%s.jpg" % (pid, it.get("snap") or "0"))
    if os.path.exists(path): return path
    if not fetch or not it.get("url"): return cover_file(pid)
    try:
        data = http_get(it["url"]); os.makedirs(COVERS, exist_ok=True); atomic_write(path, data, "wb")
        for f in os.listdir(COVERS):
            if f.startswith(pid + "_") and os.path.join(COVERS, f) != path:
                try: os.remove(os.path.join(COVERS, f))
                except OSError: pass
        return path
    except Exception as e: log("Library cover download failed: %r" % e); return cover_file(pid)
def liked_tracks(sp, cap=100):
    """Your newest liked songs (Liked Songs can't be played as a context, so it becomes a song list)."""
    out = []; path = "/me/tracks?limit=50"
    while path and len(out) < cap:
        c, r = sp._api("GET", path)
        if c != 200 or not isinstance(r, dict): break
        for x in r.get("items") or []:
            t = (x or {}).get("track") or (x or {}).get("item") if isinstance(x, dict) else None
            if isinstance(t, dict) and str(t.get("uri", "")).startswith("spotify:track:"): out.append(t)
        path = _next_path(r)
    return out[:cap]
def parse_tracks(text):
    """Every Spotify track in a text (links, URIs, one per line as the Spotify app drags them), in order."""
    ids = re.findall(r"(?:spotify:track:|open\.spotify\.com/(?:intl-[a-z]+/)?track/)([A-Za-z0-9]{22})", text or "")
    return ["spotify:track:" + i for i in dict.fromkeys(ids)]
def fetch_tracks(sp, uris):
    """Look up several tracks in one call -> [(uri, name, artist)]."""
    out = []
    for k in range(0, len(uris), 50):
        c, r = sp._api("GET", "/tracks?ids=" + ",".join(u.split(":")[-1] for u in uris[k:k + 50]))
        if c == 200 and isinstance(r, dict):
            out += [store_track(t) for t in (r.get("tracks") or []) if isinstance(t, dict) and t.get("name")]
    return out
def search_tracks(sp, q, limit=8):
    from urllib.parse import quote
    c, r = sp._api("GET", "/search?type=track&limit=%d&q=%s" % (limit, quote(q)))
    if c != 200 or not isinstance(r, dict): return None
    return [t for t in ((r.get("tracks") or {}).get("items") or []) if isinstance(t, dict) and t.get("uri")]
def now_playing(sp):
    c, r = sp._api("GET", "/me/player/currently-playing")
    if c == 200 and isinstance(r, dict) and isinstance(r.get("item"), dict) and str(r["item"].get("uri", "")).startswith("spotify:track:"):
        return r["item"]
    return None
def parse_track(text):
    m = re.search(r"(?:spotify:track:|open\.spotify\.com/(?:intl-[a-z]+/)?track/)([A-Za-z0-9]{22})", text or "")
    return "spotify:track:" + m.group(1) if m else None
class Art:
    """Anti-aliased portrait chips and flag icons (Pillow, cached PhotoImages)."""
    def __init__(self, master, S):
        self.m, self.S, self.cache = master, S, {}
    def chip(self, key, r, dim=False):
        k = ("chip", key, r, dim)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageTk
        song = next((s for s in SONGS if s[0] == key), ("plus", "", "", "", "#3a3a3a"))
        D = chip_px(r, self.S); Q = 4; big = D * Q
        im = Image.new("RGBA", (big, big), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.ellipse([0, 0, big - 1, big - 1], fill=song[4])          # PIL boxes are inclusive: 0..big-1 is centred
        inner = big - 2 * int(round(2 * self.S * Q))                     # even margin: portrait exactly centred
        src = track_cover(song[3]) if key.startswith("c_") else game().portrait_path(key)
        try: p = Image.open(src).convert("RGB").resize((inner, inner), Image.LANCZOS)
        except Exception:
            p = Image.new("RGB", (inner, inner), "#262626")
            if key == "plus" or key.startswith("c_"):                      # '+' chip / custom song without cover
                dd = ImageDraw.Draw(p); w_ = max(2, inner // 14); c_ = inner / 2; a_ = inner * 0.22
                if key == "plus":
                    dd.line([(c_ - a_, c_), (c_ + a_, c_)], fill="#1DB954", width=w_); dd.line([(c_, c_ - a_), (c_, c_ + a_)], fill="#1DB954", width=w_)
                else: dd.ellipse([c_ - a_, c_ - a_, c_ + a_, c_ + a_], outline="#1DB954", width=w_)
        if dim: p = Image.blend(p, Image.new("RGB", p.size, "#121212"), 0.6)
        m = Image.new("L", (inner, inner), 0); ImageDraw.Draw(m).ellipse([0, 0, inner - 1, inner - 1], fill=255)
        off = (big - inner) // 2; im.paste(p, (off, off), m)
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def emblem(self, pack, r, hover=False):
        """A built-in song pack's emblem (game adapter supplies image / frame / colour): the pack image on a
        dark disc inside an anti-aliased frame ('spiked8': ring with eight points, 'ring': double ring).
        Even-sized like a chip, so it centres exactly at any DPI."""
        k = ("emblem", pack.get("emblem"), round(r, 2), hover)
        if k in self.cache: return self.cache[k]
        import math
        from PIL import Image, ImageDraw, ImageTk, ImageColor
        D = chip_px(r, self.S); Q = 4; N = D * Q; c = N / 2
        im = Image.new("RGBA", (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        g = ImageColor.getrgb(pack.get("color") or "#d6b062")
        if hover: g = tuple(min(255, int(v * 1.15) + 18) for v in g)
        g = g + (255,); R = r * self.S * Q; fill = (34, 28, 18, 255)
        if pack.get("frame") == "ring":
            d.ellipse((c - R, c - R, c + R, c + R), fill=g); r2 = R * 0.90; d.ellipse((c - r2, c - r2, c + r2, c + r2), fill=fill)
            inner = R * 0.76
        else:                                           # spiked8
            for n in range(8):
                a = n * math.pi / 4 - math.pi / 2
                pts = [(c + R * math.cos(a), c + R * math.sin(a))] + [(c + R * 0.78 * math.cos(a + s), c + R * 0.78 * math.sin(a + s)) for s in (-0.17, 0.17)]
                d.polygon(pts, fill=g)
            r1 = R * 0.84; d.ellipse((c - r1, c - r1, c + r1, c + r1), fill=g)
            r2 = R * 0.75; d.ellipse((c - r2, c - r2, c + r2, c + r2), fill=fill)
            inner = R * 0.70
        try:
            src = Image.open(game().pack_emblem_path()).convert("RGBA"); s = int(inner * 2 * 0.86)
            src = src.resize((s, s), Image.LANCZOS); im.alpha_composite(src, (int(c - s / 2), int(c - s / 2)))
        except Exception as e: log("Pack emblem: %r" % e)
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def ring(self, R, color, w=1.5):
        """Anti-aliased ring (4x supersampled, LANCZOS down) of logical radius R (centre of the stroke) and
        stroke width w, in an EVEN-sized image so it centres on the same pixel as a chip at the same coords."""
        k = ("ring", round(R, 3), color, w)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageTk, ImageColor
        D = even_px(2 * R + w + 4, self.S); Q = 4; B = D * Q; C_ = B // 2
        im = Image.new("RGBA", (B, B), (0, 0, 0, 0))
        ro = int(round((R + w / 2) * self.S * Q)); lw = max(Q, int(round(w * self.S * Q)))
        ImageDraw.Draw(im).ellipse([C_ - ro, C_ - ro, C_ + ro - 1, C_ + ro - 1], outline=ImageColor.getrgb(color) + (255,), width=lw)
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def plus(self, r, hover=False):
        """The YOURS '+' button: same image size/parity as a song chip (so it centres exactly like one), one
        thin ring and a '+' made of two centred strokes (no font glyph). Hover = slightly brighter + faint fill."""
        k = ("plus", r, hover)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageTk
        D = chip_px(r, self.S); Q = 4; B = D * Q; d_ = None
        im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
        g = (64, 222, 120) if hover else (29, 185, 84)
        def box(rad):
            R = int(round(rad)); C_ = B // 2; return [C_ - R, C_ - R, C_ + R - 1, C_ + R - 1]
        ring = (r + 0.5) * self.S * Q; lw = max(Q, int(round(1.6 * self.S * Q)))
        if hover: d_.ellipse(box(ring), fill=g + (38,))
        d_.ellipse(box(ring), outline=g + (255,), width=lw)
        arm = int(round(r * 0.42 * self.S * Q)); sw = max(Q, int(round(2.0 * self.S * Q))); sw += sw % 2
        C_ = B // 2
        d_.rectangle([C_ - arm, C_ - sw // 2, C_ + arm - 1, C_ + sw // 2 - 1], fill=g + (255,))
        d_.rectangle([C_ - sw // 2, C_ - arm, C_ + sw // 2 - 1, C_ + arm - 1], fill=g + (255,))
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def chevron(self, size, color, back=False, fill=None, w=7.0, h=14.0, lw=2.0):
        """Supersampled chevron (optionally on a round button of logical diameter `size`). The two arms are
        placed so their visual mass (centroid = midpoint between tip and arm ends) sits on the exact centre."""
        k = ("chev", size, color, back, fill, w, h, lw)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageTk
        D = even_px(size, self.S); Q = 4; B = D * Q
        im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im); c = (B - 1) / 2; k_ = self.S * Q
        if fill: d_.ellipse([0, 0, B - 1, B - 1], fill=fill)
        disc_im = im; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
        sgn = -1 if back else 1
        tip = (c + sgn * w / 2 * k_, c); a1 = (c - sgn * w / 2 * k_, c - h / 2 * k_); a2 = (c - sgn * w / 2 * k_, c + h / 2 * k_)
        L = max(Q, int(round(lw * k_)))
        d_.line([a1, tip, a2], fill=color, width=L, joint="curve")
        for p_ in (a1, a2, tip):                                       # round caps
            d_.ellipse([p_[0] - L / 2, p_[1] - L / 2, p_[0] + L / 2, p_[1] + L / 2], fill=color)
        im = Image.alpha_composite(disc_im, ink_centre(im))             # optical centre = ink centroid
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def disc(self, diam, fill, text=None, fg=None, tsize=None, cross=None, outline=None, ow=0.0):
        """Round badge as an even-sized supersampled image (exact centre at any DPI, unlike canvas ovals),
        with an optional glyph whose INK (not font metrics) is centred, or a cross drawn as two strokes."""
        k = ("disc", diam, fill, text, fg, tsize, cross, outline, ow)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        D = even_px(diam, self.S); Q = 4; B = D * Q; k_ = self.S * Q
        im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
        o = int(round(ow * k_)) if outline else 0
        d_.ellipse([0, 0, B - 1, B - 1], fill=outline or fill)
        if o: d_.ellipse([o, o, B - 1 - o, B - 1 - o], fill=fill)
        c = (B - 1) / 2
        if text:
            try: f = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeuib.ttf"), int(round(tsize * k_)))
            except Exception: f = ImageFont.load_default()
            tl = Image.new("RGBA", (B, B), (0, 0, 0, 0)); ImageDraw.Draw(tl).text((c, c), text, font=f, fill=fg, anchor="mm")
            im = Image.alpha_composite(im, ink_centre(tl)); d_ = ImageDraw.Draw(im)      # centre the glyph INK
        if cross:
            base_im = im; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
            a_ = cross * k_; L = max(Q, int(round(1.6 * k_)))
            for p_, q_ in (((c - a_, c - a_), (c + a_, c + a_)), ((c - a_, c + a_), (c + a_, c - a_))):
                d_.line([p_, q_], fill=fg, width=L)
                for e_ in (p_, q_): d_.ellipse([e_[0] - L / 2, e_[1] - L / 2, e_[0] + L / 2, e_[1] + L / 2], fill=fg)
            im = Image.alpha_composite(base_im, ink_centre(im))
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def flag(self, civ, h=16):
        k = ("flag", civ, h)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageTk, ImageDraw
        H = int(round(h * self.S)); W = int(round(H * 60 / 32))
        p = game().flag_path(civ)
        try: im = Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)
        except Exception:
            im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(im).rounded_rectangle([0, 0, W - 1, H - 1], 3, fill="#555555")
        ph = ImageTk.PhotoImage(im, master=self.m); self.cache[k] = ph; return ph
SW_W, SW_H = 44, 24                                   # one switch size app-wide (panel toggle default)
