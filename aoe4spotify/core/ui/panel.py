"""The main settings window (panel).

Split out of core/gui.py in 1.0.9; behaviour unchanged.
"""

import json, os, re, sys, threading, time, webbrowser
from aoe4spotify.core.access import access_dialog, access_status
from aoe4spotify.core.byo import byo_dialog
from aoe4spotify.core.runtime import DATA, GITHUB_URL, HERE, ImageColor_rgb, LOGFILE, TOKEN, VERSION, child_env, dark_window, keep_on_screen, swap_pages, cover, log, note_window, reveal, set_canvas_height, single_window, win_hidden
from aoe4spotify.core.branding import APP_NAME
from aoe4spotify.core.settings import INTRO_AGES, _LIVE_USER, after_match_cfg, apply_user, custom_cover, custom_get, is_custom, load_config, load_user, load_user_settings, merge_user, save_user, using_own_app
from aoe4spotify.core.spotify import Spotify
from aoe4spotify.core.updater import check_update, download_update, run_update
from aoe4spotify.games.registry import active as game
from aoe4spotify.core.ui.library import ROMAN, AGES, Art, NAMES_CACHE, RE_PLAYLIST, SW_H, SW_W, cover_file, fetch_track, open_playlist, parse_track, track_cover, update_cover
from aoe4spotify.core.ui.widgets import after_mouse_up, app_badge, canvas_rect, get_tip, install_edit_menu, set_app_icon
from aoe4spotify.core.ui.gtg import good_to_go
from aoe4spotify.core.ui.picker import list_picker
from aoe4spotify.core.ui.intros import pool_editor
from aoe4spotify.core.ui.fire import FRAME_MS, Fire, glow_layer
from aoe4spotify.core.playback import read_now_playing

def _g_app():
    import aoe4spotify.core.app as _m
    return _m

def panel(preview=False):
    """preview=True (--fire-preview): dev view of the row fire with a fake playing age; keys 1-4 / P / Esc."""
    if not single_window("fire_preview" if preview else "panel", APP_NAME): return
    import tkinter as tk, subprocess, webbrowser as wb
    try: import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", off="#3a3a3a", line="#2a2a2a",
             ib="#2a2a2a", idle="#8a8a8a", red="#e5484d", acc="#1DB954", dis="#555555", org="#f0a030")
    root = tk.Tk(); dark_window(root, C["bg"]); root.title((APP_NAME + " - Fire preview (1-%d age, P pause, Esc close)") % min(9, len(AGES)) if preview else APP_NAME); root.resizable(False, False)
    install_edit_menu(root)
    S = root.winfo_fpixels("1i") / 96.0
    W, H = 430, 420
    M = 16; R_ = W - M                              # content left / right edge
    cv = tk.Canvas(root, width=int(W * S), height=int(H * S), bg=C["bg"], highlightthickness=0); cv.pack()
    FONT = "Segoe UI"
    def F(sz, b=False): return (FONT, -int(sz * S), "bold" if b else "normal")
    def P(*v): return [x * S for x in v]
    # Shapes are drawn with Pillow at 4x and downscaled, so corners and circles are anti-aliased.
    from PIL import Image, ImageDraw, ImageTk
    from aoe4spotify.core.ui import aa
    from aoe4spotify.core.ui.crown import GREEN, GREY_ACC, crown_color, crown_image
    imgs = {}
    def _img(key, w, h, paint):
        k = (key, w, h)
        if k not in imgs:
            Q = 4; im = Image.new("RGBA", (max(1, w) * Q, max(1, h) * Q), (0, 0, 0, 0))
            paint(ImageDraw.Draw(im), Q)
            imgs[k] = ImageTk.PhotoImage(im.resize((max(1, w), max(1, h)), Image.LANCZOS))
        return imgs[k]
    def rr(x0, y0, x1, y1, r, fill, outline="", tag=None, width=1):
        X0, Y0, X1, Y1 = [int(round(v)) for v in P(x0, y0, x1, y1)]
        w, h = X1 - X0, Y1 - Y0; rad = min(r * S, w / 2, h / 2)
        def paint(d, Q):
            d.rounded_rectangle([0, 0, w * Q - 1, h * Q - 1], radius=rad * Q, fill=fill or None,
                                outline=outline or None, width=int(width * S * Q) if outline else 0)
        return cv.create_image(X0, Y0, image=_img(("rr", r, fill, outline, width), w, h, paint), anchor="nw", tags=tag)
    def oval_(box, fill="", outline="", width=0, tags=None):
        X0, Y0, X1, Y1 = [int(round(v)) for v in box]
        w, h = X1 - X0, Y1 - Y0
        def paint(d, Q):
            d.ellipse([0, 0, w * Q - 1, h * Q - 1], fill=fill or None, outline=outline or None, width=int(width * Q) if outline else 0)
        return cv.create_image(X0, Y0, image=_img(("ov", fill, outline, width), w, h, paint), anchor="nw", tags=tags)
    def undo_icon(cx, cy, c, tag):
        sz = int(18 * S)
        def paint(d, Q):
            m = sz * Q; lw = max(2, int(2.2 * S * Q))
            d.arc([m*0.18, m*0.2, m*0.86, m*0.88], start=200, end=470, fill=c, width=lw)
            d.polygon([(m*0.04, m*0.42), (m*0.36, m*0.42), (m*0.18, m*0.66)], fill=c)
        return cv.create_image(int(cx * S), int(cy * S), image=_img(("undo", c), sz, sz, paint), anchor="center", tags=tag)
    badge = app_badge
    logo = ImageTk.PhotoImage(badge(int(32 * S)))
    def _icon(px, paint):
        px += px % 2                                       # even size: centre-anchored icons land exactly on their point
        Q = 4; im = Image.new("RGBA", (px * Q, px * Q), (0, 0, 0, 0)); paint(ImageDraw.Draw(im), px * Q, Q)
        return ImageTk.PhotoImage(im.resize((px, px), Image.LANCZOS))
    def _power(d, m, Q):
        lw = int(3 * S * Q); d.arc([m*0.12, m*0.16, m*0.88, m*0.92], start=-60, end=240, fill=C["acc"], width=lw)
        d.rounded_rectangle([m/2 - lw/2, m*0.04, m/2 + lw/2, m*0.5], radius=lw/2, fill=C["acc"])
    def _fade(d, m, Q):
        lw = int(2 * S * Q)
        for k in range(3):     # ink spans x 0.25..0.76 of the box, i.e. centred like the other row icons
            d.arc([m*(-0.2+k*0.18), m*0.12, m*(0.4+k*0.18), m*0.88], start=-60, end=60, fill=C["acc"], width=lw)
    def _chev(up):
        def p(d, m, Q):
            lw = int(2.4 * S * Q); a, b = (0.62, 0.36) if up else (0.38, 0.64)
            d.line([(m*0.22, m*a), (m*0.5, m*b), (m*0.78, m*a)], fill=C["mu"], width=lw, joint="curve")
            for x, yy in ((0.22, a), (0.5, b), (0.78, a)): d.ellipse([m*x - lw/2, m*yy - lw/2, m*x + lw/2, m*yy + lw/2], fill=C["mu"])
        return p
    chev_up = _icon(int(18 * S), _chev(True)); chev_down = _icon(int(18 * S), _chev(False))
    _chevr = {}
    def chev_right(cx, cy, col, tag, size=14):
        """Anti-aliased '>' centred exactly on (cx, cy) - no font baseline involved."""
        k = (col, size)
        if k not in _chevr:
            def p(d, m, Q):
                lw = int(2.2 * S * Q)
                pts = [(m*0.38, m*0.2), (m*0.64, m*0.5), (m*0.38, m*0.8)]
                d.line(pts, fill=col, width=lw, joint="curve")
                for x, yy in pts: d.ellipse([x - lw/2, yy - lw/2, x + lw/2, yy + lw/2], fill=col)
            _chevr[k] = _icon(int(size * S), p)
        cv.create_image(*P(cx, cy), image=_chevr[k], anchor="center", tags=tag)
    ui = {"open": os.environ.get("AOE4SPOTIFY_PANEL_OPEN") == "1",   # env vars: screenshots/testing only
          "am": os.environ.get("AOE4SPOTIFY_AM_OPEN") == "1"}
    class _V:                                          # After match icons: drawn in 22-unit space around the centre
        def __init__(s_, d, m): s_.d = d; s_.k = m / 22.0; s_.c = m / 2.0
        def p(s_, x, y): return (s_.c + x * s_.k, s_.c + y * s_.k)
        def rr(s_, x0, y0, x1, y1, r, fill): s_.d.rounded_rectangle([*s_.p(x0, y0), *s_.p(x1, y1)], radius=r * s_.k, fill=fill)
        def circ(s_, x, y, r, fill): s_.d.ellipse([*s_.p(x - r, y - r), *s_.p(x + r, y + r)], fill=fill)
        def poly(s_, pts, fill): s_.d.polygon([s_.p(x, y) for x, y in pts], fill=fill)
        def arc(s_, box, a0, a1, col, w): s_.d.arc([*s_.p(box[0], box[1]), *s_.p(box[2], box[3])], a0, a1, fill=col, width=max(1, int(w * s_.k)))
        def pie(s_, box, a0, a1, col): s_.d.pieslice([*s_.p(box[0], box[1]), *s_.p(box[2], box[3])], a0, a1, fill=col)
        def line(s_, pts, col, w):
            P_ = [s_.p(x, y) for x, y in pts]; s_.d.line(P_, fill=col, width=max(1, int(w * s_.k)), joint="curve"); r = w * s_.k / 2
            for x, y in (P_[0], P_[-1]): s_.d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    def _am_icon(name, col, bg):
        def paint(d, m, Q):
            v = _V(d, m)
            if name == "flag":
                v.line([(-6, -8), (-6, 8)], col, 2); v.rr(-5, -8, 7, 1, 1.5, col)
                for i in range(3):
                    for j in range(2):
                        if (i + j) % 2: d.rectangle([*v.p(-5 + i * 4, -8 + j * 4.5), *v.p(-1 + i * 4, -3.5 + j * 4.5)], fill=bg)
            elif name == "keep": v.poly([(-4, -6), (-4, 6), (6, 0)], col)
            elif name == "fade":
                for i, h in enumerate((10, 7, 4)): v.rr(-8 + i * 3.6, 5 - h, -5.8 + i * 3.6, 5, 1.1, col)
                v.rr(2.5, -5, 4.7, 5, 1.1, col); v.rr(6.5, -5, 8.7, 5, 1.1, col)
            elif name == "stop": v.rr(-5, -5, 5, 5, 2, col)
            elif name == "playlist":
                for i in range(3): v.line([(-8, -5 + i * 5), (1 if i < 2 else -3, -5 + i * 5)], col, 2)
                v.circ(4.5, 5, 2.6, col); v.line([(6.6, 5), (6.6, -4), (9, -5.5)], col, 1.8)
            elif name == "dark":
                import math
                v.arc((-7, -7, 7, 7), -60, 220, col, 1.9); a = math.radians(-60); px_, py_ = 7 * math.cos(a), 7 * math.sin(a)
                v.poly([(px_ + 3.5, py_ - 1.5), (px_ - 2.5, py_ - 3.5), (px_ + 0.5, py_ + 3)], col)
            elif name in ("winloss", "trophy"):
                v.pie((-6, -12, 6, 3), 0, 180, col); v.rr(-6, -6, 6, -4.5, 0.5, col)
                v.arc((-10, -6, -3, 1), 90, 270, col, 1.8); v.arc((3, -6, 10, 1), 270, 90, col, 1.8)
                v.rr(-1.2, 2, 1.2, 6, 0.6, col); v.rr(-5, 5.5, 5, 7.5, 1, col)
            elif name == "skull":
                v.circ(0, -1, 6, col); v.rr(-3.5, 2, 3.5, 7, 1.5, col); v.circ(-2.3, -1, 1.6, bg); v.circ(2.3, -1, 1.6, bg)
            elif name == "resume":
                v.arc((-8, -8, 8, 8), 140, 420, col, 1.8); v.poly([(-9.5, -6.5), (-4, -7.5), (-7.5, -2.5)], col)
                v.poly([(-2, -4), (-2, 4), (4.5, 0)], col)
            elif name == "then": v.line([(-5, 0), (4, 0)], col, 1.8); v.line([(1, -3.5), (4.5, 0), (1, 3.5)], col, 1.8)
            elif name == "plus": v.line([(-4.5, 0), (4.5, 0)], col, 1.8); v.line([(0, -4.5), (0, 4.5)], col, 1.8)
        return _icon(int(22 * S), paint)
    _amic = {}
    def vic(name, col, bg):
        k = (name, col, bg)
        if k not in _amic: _amic[k] = _am_icon(name, col, bg)
        return _amic[k]
    power_img = _icon(int(30 * S), _power); fade_img = _icon(int(24 * S), _fade)
    REP_ROW = 38                                            # cog menu: 'Music in replays' row + divider
    G0, CORAL, CORAL_TX = GREEN, "#e5675f", "#f0d6d4"
    _ghi = {}
    def gh_icon():
        """Small GitHub mark (light circle, cat head cut out), anti-aliased, matching the menu text colour."""
        if not _ghi:
            def p(d, m, Q):
                bg = (0, 0, 0, 0); d.ellipse([0, 0, m - 1, m - 1], fill=C["tx"]); c = m / 2; k = m / 14.0
                d.ellipse([c - 3.6 * k, c - 3.2 * k, c + 3.6 * k, c + 2.6 * k], fill=bg)
                d.polygon([(c - 3.6 * k, c - 1 * k), (c - 3.2 * k, c - 4.8 * k), (c - 1.2 * k, c - 3 * k)], fill=bg)
                d.polygon([(c + 3.6 * k, c - 1 * k), (c + 3.2 * k, c - 4.8 * k), (c + 1.2 * k, c - 3 * k)], fill=bg)
                d.rectangle([c - 1.5 * k, c + 2 * k, c + 1.5 * k, m], fill=bg)
            _ghi[0] = _icon(int(14 * S), p)
        return _ghi[0]
    _repi = {}
    def rep_icon():
        """Small 'replay' mark for the cog menu: open circular arrow + play triangle, menu text colour, like the GitHub mark."""
        if not _repi:
            def p(d, m, Q):
                lw = max(2, int(1.6 * S * Q)); c = m / 2; r = m * 0.40
                d.arc([c - r, c - r, c + r, c + r], start=-70, end=230, fill=C["tx"], width=lw)
                import math
                a = math.radians(-70); hx, hy = c + r * math.cos(a), c + r * math.sin(a); k = m / 14.0
                d.polygon([(hx - 2.6 * k, hy - 2.4 * k), (hx + 2.2 * k, hy - 0.2 * k), (hx - 1.6 * k, hy + 2.6 * k)], fill=C["tx"])
                d.polygon([(c - 1.8 * k, c - 2.6 * k), (c - 1.8 * k, c + 2.6 * k), (c + 2.6 * k, c)], fill=C["tx"])
            _repi[0] = _icon(int(14 * S), p)
        return _repi[0]
    def open_github():
        try: webbrowser.open(GITHUB_URL)
        except Exception as e: log("Open GitHub: %r" % e)
    _plic = {}
    def pl_icon(col):
        """Playlists card icon: three list lines + an eighth note (2px strokes like Fade, solid like the crown)."""
        if col not in _plic:
            def p(d, m, Q):
                lw = 2 * S * Q
                for i, x1 in enumerate((0.62, 0.62, 0.40)):
                    y = m * (0.24 + i * 0.22); d.rounded_rectangle([m * 0.10, y - lw / 2, m * x1, y + lw / 2], lw / 2, fill=col)
                cx, cy, r = m * 0.66, m * 0.74, m * 0.12
                d.ellipse([cx - r * 1.15, cy - r * 0.85, cx + r * 1.15, cy + r * 0.85], fill=col)
                sx = cx + r * 1.15 - lw / 2
                d.rectangle([sx - lw / 2, m * 0.30, sx + lw / 2, cy], fill=col)
                d.polygon([(sx, m * 0.30), (sx + m * 0.20, m * 0.42), (sx + m * 0.20, m * 0.50), (sx, m * 0.40)], fill=col)
            _plic[col] = _icon(int(24 * S), p)
        return _plic[col]
    _fadec = {}
    def fade_icon(col):
        if col not in _fadec:
            def p(d, m, Q):
                lw = int(2 * S * Q)
                for k in range(3): d.arc([m*(-0.2+k*0.18), m*0.12, m*(0.4+k*0.18), m*0.88], start=-60, end=60, fill=col, width=lw)
            _fadec[col] = _icon(int(24 * S), p)
        return _fadec[col]
    def _mix(a, b, t):
        A_, B_ = ImageColor_rgb(a), ImageColor_rgb(b)
        return "#%02x%02x%02x" % tuple(int(round(A_[i] + (B_[i] - A_[i]) * t)) for i in range(3))
    _pwr = {}; _pwr_pil = {}; PSTEP = 3                # one frame per 3 degrees (120 frames per turn)
    def pwr_t(a):
        """Colour position for rotation angle a: 0 = on (green, upright), 180 = off (coral), 360 = on again."""
        a %= 360.0; return 1.0 - abs(a - 180.0) / 180.0
    def _pwr_frame(k):
        """PIL frame for angle k*PSTEP: drawn upright at 4x, rotated about the ring's exact centre, then downsampled."""
        px = int(30 * S); px += px % 2; Q = 4; m = px * Q; col = _mix(G0, CORAL, pwr_t(k * PSTEP))
        im = Image.new("RGBA", (m, m), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        lw = int(3 * S * Q); d.arc([m*0.12, m*0.16, m*0.88, m*0.92], start=-60, end=240, fill=col, width=lw)
        d.rounded_rectangle([m/2 - lw/2, m*0.04, m/2 + lw/2, m*0.5], radius=lw/2, fill=col)
        if k % (360 // PSTEP): im = im.rotate(-(k * PSTEP), resample=Image.BICUBIC, center=(m / 2, m * 0.54))
        return im.resize((px, px), Image.LANCZOS)
    def _pwr_prerender():                              # background thread: PIL only (PhotoImages are made on the Tk thread)
        for k in range(360 // PSTEP):
            if k not in _pwr_pil:
                try: _pwr_pil[k] = _pwr_frame(k)
                except Exception: return
    def power_icon(a):
        """Power icon at rotation angle a (degrees, any value; 0 = on, 180 = off)."""
        k = int(round((a % 360.0) / PSTEP)) % (360 // PSTEP)
        if k not in _pwr:
            im = _pwr_pil.get(k) or _pwr_frame(k)
            _pwr[k] = ImageTk.PhotoImage(im)
        return _pwr[k]
    def red_glow():
        k = ("glow",)
        if k not in imgs:
            from PIL import ImageFilter
            w, h = int((R_ - M + 24) * S), int((48 + 24) * S)
            im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(im).rounded_rectangle([8 * S, 8 * S, w - 8 * S, h - 8 * S], radius=16 * S, fill=(229, 103, 95, 70))
            imgs[k] = ImageTk.PhotoImage(im.filter(ImageFilter.GaussianBlur(5 * S)))
        return imgs[k]
    en_anim = {"a": None, "job": None, "pos": 0.0}   # a = angle while animating (None = settled); pos = last angle
    PWR_DUR = 0.45                                     # seconds per half turn
    def anim_enabled(to_off):
        """Spin the power icon forward to the next upside-down (off) or upright (on) position; never reverses, also
        when toggled again mid-spin. Colour follows the angle, so it stays in sync. ~120 fps only while spinning."""
        if en_anim["job"]:
            try: root.after_cancel(en_anim["job"])
            except Exception: pass
            en_anim["job"] = None
        a0 = en_anim["a"] if en_anim["a"] is not None else (0.0 if to_off else 180.0)
        goal = 180.0 if to_off else 0.0
        b = a0 + ((goal - a0) % 360.0 or 360.0)           # next goal strictly ahead (forward only)
        if en_anim["a"] is not None and (goal - a0) % 360.0 == 0: b = a0  # already there mid-spin
        dur = PWR_DUR * max(0.35, (b - a0) / 180.0); t0 = time.perf_counter()
        def step():
            u = min(1.0, (time.perf_counter() - t0) / dur) if dur else 1.0
            e = 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2      # ease-in-out cubic
            a = a0 + (b - a0) * e; en_anim["a"] = a; en_anim["pos"] = a % 360.0
            try:
                cv.itemconfigure("pwr", image=power_icon(a)); cv.itemconfigure("entx", fill=_mix(C["tx"], CORAL_TX, pwr_t(a)))
            except tk.TclError: return
            if u < 1.0: en_anim["job"] = root.after(8, step)
            else: en_anim.update(a=None, job=None, pos=b % 360.0)          # normalise: 360 -> 0
        step()
    root._en_anim = en_anim; root._pwr_t = lambda a: pwr_t(a); root._anim_enabled = lambda off: anim_enabled(off)   # (tests)
    def _gear(col):
        def p(d, m, Q):
            import math
            c = m / 2
            for k in range(8):
                a = k * math.pi / 4; d.line([(c, c), (c + m*0.42*math.cos(a), c + m*0.42*math.sin(a))], fill=col, width=int(m * 0.18))
            d.ellipse([c - m*0.32, c - m*0.32, c + m*0.32, c + m*0.32], fill=col)
            d.ellipse([c - m*0.13, c - m*0.13, c + m*0.13, c + m*0.13], fill="#2a2a2a")
        return p
    gear_img = {False: _icon(int(20 * S), _gear(C["tx"])), True: _icon(int(20 * S), _gear(C["acc"]))}
    import tkinter.font as tkfont
    root.iconphoto(True, ImageTk.PhotoImage(badge(64)), ImageTk.PhotoImage(badge(32)))
    set_app_icon(root)
    def text(x, y, s, sz, c=None, b=False, anchor="w", tag=None):
        return cv.create_text(*P(x, y), text=s, font=F(sz, b), fill=c or C["tx"], anchor=anchor, tags=tag)
    # Each tag is bound once; draw() only updates the handler table. (Re-binding inside a click
    # would free the running Tcl callback and crash Tk.) Handlers run after the event finishes.
    handlers, bound = {}, set()
    def hover_hl(i): pass                           # (row highlight is handled by on_pointer)
    hov = {"cursor": "", "row": None, "hl": None, "tip": None, "n": 0}   # what the pointer is over right now
    def on_pointer(e=None, force=False):
        """Single hover handler: everything is derived from the pointer position, and the cursor / Change
        button / highlight / tooltip are only touched when they actually change (no Enter/Leave ping-pong)."""
        if e is not None:
            px, py = e.x, e.y
            if str(e.type) in ("Motion", "6") and not (int(getattr(e, "state", 0) or 0) & 0x100): hov["down"] = False
            hov["xy"] = None if str(e.type) in ("Leave", "8") else (px, py)
        elif hov.get("xy"): px, py = hov["xy"]                # redraw: re-apply hover at the last known pointer spot
        else:
            try: px, py = cv.winfo_pointerx() - cv.winfo_rootx(), cv.winfo_pointery() - cv.winfo_rooty()
            except Exception: return
        inside = 0 <= px < cv.winfo_width() and 0 <= py < cv.winfo_height()
        tags = set()
        if inside:
            for it in cv.find_overlapping(px, py, px, py):
                if cv.itemcget(it, "state") != "hidden": tags.update(cv.gettags(it))
        x, y = px / S, py / S; row = None
        if inside and ui.get("open") and not ui.get("menu") and M + 16 <= x <= R_ - 16:
            for i in range(len(AGES)):
                if PL_Y(i) <= y <= PL_Y(i) + 42: row = i
        if force: hov.update(row="?", hl="?")                 # (cursor/tooltip kept unless they really change)
        if row != hov["row"]:                       # Change button: hover-only, its space is always reserved
            cv.itemconfigure("chgx", state="hidden"); cv.itemconfigure("rowhlx", state="hidden")
            for j_ in range(len(AGES)): cv.itemconfigure("rowhl%d" % j_, state="hidden")
            if row is not None: cv.itemconfigure("chg%d" % row, state="normal"); cv.itemconfigure("rowhl%d" % row, state="normal")
            hov["row"] = row; hov["chg"] = "?"
        ch = row if (row is not None and "chg%d" % row in tags) else None     # pointer on the Change button itself: green tint
        if ch != hov.get("chg"):
            cv.itemconfigure("chghx", state="hidden")
            if ch is not None: cv.itemconfigure("chgh%d" % ch, state="normal")
            hov["chg"] = ch
        hov["hl"] = None                               # (no grey hover box on the row text)
        cur = "hand2" if any(t in handlers for t in tags) else ""
        if cur != cv.cget("cursor"): cv.config(cursor=cur); hov["n"] += 1
        ctrl = any(t.startswith(CTRL_TAGS) for t in tags)     # switches, slider, buttons, gear, menu
        tg = None if (ctrl or hov.get("down")) else next((t for t in sorted(tags) if tips.get(t)), None)
        if tg != hov["tip"]:
            hov["tip"] = tg
            if tg: show_tip_later(tg)                 # neighbour -> instant switch; nothing -> fade out
            else: hide_tip()
    root._hov = hov                                   # (tests)
    PL_H = 36 + 6 + len(AGES) * 46 + 4                   # open Playlists card height
    FADE_Y = 172                                         # card order: Enabled, pills, Fade, Playlists, Age Intros, After match
    PL_TOP = FADE_Y + 46 + 10                            # Playlists card top (header 36, rows below when open)
    def PL_Y(i): return PL_TOP + 42 + i * 46               # age row top
    CTRL_TAGS = ("rev", "chg", "fade", "en", "boss", "gear", "upd", "m_", "plh", "menubg", "spot", "am")
    def _down(e, v): hov["down"] = v; on_pointer(e)
    cv.bind("<Motion>", on_pointer, add="+"); cv.bind("<Leave>", lambda e: (on_pointer(e), hov.update(tip=None), hide_tip()), add="+")
    cv.bind("<ButtonPress-1>", lambda e: _down(e, True), add="+"); cv.bind("<ButtonRelease-1>", lambda e: _down(e, False), add="+")
    cv.bind("<B1-Motion>", on_pointer, add="+")
    def click(tag, fn):
        handlers[tag] = fn
        if tag in bound: return
        bound.add(tag)
        cv.tag_bind(tag, "<Button-1>", lambda e, t=tag: root.after_idle(lambda: handlers[t]() if t in handlers else None), add="+")

    base = load_config(user=False); user = load_user(); _LIVE_USER[:] = [user]
    defaults = base.get("default_playlists") or base.get("playlists", {})
    try: names = json.load(open(NAMES_CACHE, encoding="utf-8"))
    except Exception: names = {}
    state = {"spotify": None, "game": None, "active": None}
    fx = {"fire": None, "photo": None, "glow": None, "key": None, "job": None, "size": None, "ticks": 0}   # glow pool fire
    def fire_wanted():
        """Animate only while the window is visible, the Playlists card is open and an age row is playing."""
        return bool(ui.get("open") and state.get("active") and state["active"] in [k for k, _ in AGES] and not win_hidden(root) and cv.winfo_ismapped())   # Age Intros page shown: panel hidden
    def fire_tick():
        fx["job"] = None
        if not fire_wanted() or fx["fire"] is None: return            # stopped: no timer left behind
        try:
            fx["photo"].paste(fx["fire"].tick()); fx["ticks"] += 1
        except Exception as e: log("Row fire failed: %r" % e); return
        fx["job"] = root.after(FRAME_MS, fire_tick)
    def fire_start():
        if fx["job"] is None and fx["fire"] is not None and fire_wanted(): fx["job"] = root.after(FRAME_MS, fire_tick)
    def fire_row(x0, y0, x1, y1, r):
        """Glow + fire images for the playing row (drawn under its text). Built once per size, reused every frame."""
        w, h, rp = int(round((x1 - x0) * S)), int(round((y1 - y0) * S)), int(round(r * S))
        if fx["size"] != (w, h, rp):
            fx["fire"] = Fire(w, h, rp, S); fx["photo"] = ImageTk.PhotoImage(fx["fire"].frame())
            g, pad = glow_layer(w, h, rp, S); fx["glow"] = (ImageTk.PhotoImage(g), pad); fx["size"] = (w, h, rp)
        gimg, pad = fx["glow"]
        X0, Y0 = int(round(x0 * S)), int(round(y0 * S))                # whole pixels: crisp cells, aligned edges
        cv.create_image(X0 - pad, Y0 - pad, image=gimg, anchor="nw", tags="fire")
        cv.create_image(X0, Y0, image=fx["photo"], anchor="nw", tags="fire")
    root._fire = fx; root._fire_wanted = fire_wanted                # (tests)
    root.bind("<Map>", lambda e: fire_start() if e.widget is root else None, add="+")
    def fire_stop(e=None):                                            # minimized / withdrawn: cancel the pending frame now
        if (e is None or e.widget is root) and fx["job"] is not None:
            try: root.after_cancel(fx["job"])
            except Exception: pass
            fx["job"] = None
    root.bind("<Unmap>", fire_stop, add="+")
    upd = {"info": None, "phase": "idle", "pct": 0, "msg": ""}   # update pill state
    if "--updated" in sys.argv:                                  # just relaunched by the silent upgrade
        upd.update(phase="done", msg="Updated to %s" % VERSION)
    ui_q = []
    def post(fn): ui_q.append(fn)                 # called from worker threads

    def cur(): return apply_user(load_config(user=False), user)
    def set_user(k, v): user[k] = v; save_user(user); draw()

    def toggle(x, y, on, tag, w=SW_W, h=SW_H):
        rr(x, y, x + w, y + h, h / 2, C["acc"] if on else C["off"], tag=tag)   # follows the accent: grey while the app is Disabled
        cx = x + w - h / 2 if on else x + h / 2
        oval_(P(cx - h/2 + 3, y + 3, cx + h/2 - 3, y + h - 3), fill="white", outline="", tags=tag)

    _crowns = {}
    def crown_photo(c):
        if c not in _crowns: _crowns[c] = ImageTk.PhotoImage(crown_image(18, S, c))
        return _crowns[c]

    def icon(i, cx, cy, c, tag=None):
        if i == 0:
            oval_(P(cx-8, cy-8, cx+8, cy+8), fill=c, outline=""); oval_(P(cx-3, cy-11, cx+11, cy+3), fill=C["ib"], outline="")
        elif i == 1:
            aa.polygon(cv, P(cx-9, cy-1, cx, cy-9, cx+9, cy-1), c); cv.create_rectangle(*P(cx-6, cy-1, cx+6, cy+8), fill=c, outline="")
        elif i == 2:
            cv.create_rectangle(*P(cx-8, cy-3, cx+8, cy+9), fill=c, outline="")
            for k in (-8, -2, 4): cv.create_rectangle(*P(cx+k, cy-8, cx+k+4, cy-3), fill=c, outline="")
        else:
            cv.create_image(*P(cx, cy), image=crown_photo(c), anchor="center", tags=tag or "crown")   # shared symmetric crown

    def pl_name(uri):
        if is_custom(uri): return (custom_get(uri, user) or {}).get("name") or "My list"
        pid = uri.split(":")[-1]
        return names.get(pid) or "Playlist"

    covers = {}; cover_cache = {}
    def cover_img(path, size=30):
        """Rounded, anti-aliased thumbnail (30 px default) of a cached cover file (None if missing/broken)."""
        if not path or not os.path.exists(path): return None
        k = (path, os.path.getmtime(path), size)
        if k not in cover_cache:
            try:
                px = int(round(size * S)); Q = 4
                im = Image.open(path).convert("RGB").resize((px, px), Image.LANCZOS)
                m = Image.new("L", (px * Q, px * Q), 0)
                ImageDraw.Draw(m).rounded_rectangle([0, 0, px * Q - 1, px * Q - 1], (6 if size >= 30 else 5) * S * Q, fill=255)
                im.putalpha(m.resize((px, px), Image.LANCZOS)); cover_cache[k] = ImageTk.PhotoImage(im)
            except Exception as e:
                log("Cover image: %r" % e); cover_cache[k] = None
        return cover_cache[k]
    tips, tipbound = {}, set()
    tipst = {"tag": None, "shown": False}
    def hide_tip(_=None):
        tipst["tag"] = None; get_tip(cv).hide()
    def tip(tag, msg): tips[tag] = msg              # shown by on_pointer (shared GlassTip: delay, anchoring, fades)
    def show_tip_later(tag):
        tipst["tag"] = tag; bb = cv.bbox(tag)
        if not bb or not tips.get(tag): return
        get_tip(cv).request(("panel", tag), tips[tag], canvas_rect(cv, bb), S, cv)

    def draw():
        cv.delete("all"); handlers.clear(); cfg = cur(); en = bool(cfg.get("enabled", True))
        C["acc"] = G0 if en else GREY_ACC                  # disabled: the other rows' green accents go grey
        # header: logo, title + subtitle, version pill, update pill, gear
        cv.create_image(*P(M, 14), image=logo, anchor="nw")
        text(M + 44, 30, APP_NAME, 19, b=True)
        tw = tkfont.Font(font=F(19, True)).measure(APP_NAME) / S
        px = M + 44 + tw + 8
        rr(px, 21, px + 44, 39, 9, C["card"]); text(px + 22, 30, "v" + VERSION, 10, C["mu"], anchor="center")
        px += 4
        px += 48
        ph = upd["phase"]
        if ph != "idle":
            col = C["red"] if ph == "error" else G0
            lab = {"avail": "\u2193 Update %s" % (upd["info"] or {}).get("version", ""), "dl": "Downloading %d%%" % upd["pct"],
                   "run": "InstallingÃ¢â‚¬Â¦", "error": upd["msg"] or "Update failed", "done": upd["msg"]}[ph]
            pw = tkfont.Font(font=F(10, True)).measure(lab) / S + 20
            rr(px, 21, px + pw, 39, 9, "#183d26" if col == G0 else "#3d1a1a", col, "upd")
            text(px + pw / 2, 30, lab, 10, col, True, "center", "upd")
            if ph in ("avail", "error") and upd["info"]: click("upd", start_update)
        gx = R_ - 32
        rr(gx, 14, R_, 46, 10, "#2a2a2a", tag="gear"); cv.create_image(*P(gx + 16, 30), image=gear_img[ui.get("menu", False)], anchor="center", tags="gear")
        if upd["info"] and ph in ("avail", "error"): oval_(P(R_ - 8, 10, R_ + 2, 20), fill=G0, outline=C["bg"], width=2 * S, tags="gear")
        click("gear", lambda: (ui.update(menu=not ui.get("menu")), draw()))
        cv.create_line(*P(M, 62, R_, 62), fill=C["line"])

        # enabled (power icon vertically centered on the card)
        if en: rr(M, 72, R_, 120, 12, C["card"], tag="encard")
        else:                                               # disabled: soft red tint, thin red edge, soft glow
            cv.create_image(*P(M - 12, 72 - 12), image=red_glow(), anchor="nw")
            rr(M, 72, R_, 120, 12, "#2a1c1c", "#5a3330", tag="encard")
        cy = 96; pa = en_anim["a"] if en_anim["a"] is not None else (0.0 if en else 180.0); pt = pwr_t(pa)
        cv.create_image(*P(M + 24, cy), image=power_icon(pa), anchor="center", tags=("encard", "pwr"))
        text(M + 50, cy, "Enabled" if en else "Disabled", 16, _mix(C["tx"], CORAL_TX, pt), b=True, tag=("encard", "entx")); toggle(R_ - 12 - 52, cy - 14, en, "en", 52, 28)
        click("en", lambda: (set_user("enabled", not en), editor_redraw(), anim_enabled(en), threading.Thread(target=game().music_sync, args=(not en,), daemon=True).start()))
        tip("encard", ("Runs automatically when you launch %s%s and mutes" % (game().label, " from " + game().launcher if game().launcher else "")) + " the game's own music. You don't need this window open." if en else "Off: music won't switch when you play, and the game's music is back on.")
        # status chips: Spotify (clickable -> log in) and Game
        cw = (W - 2 * M - 10) / 2; x = M; sp_ok = state["spotify"]
        rr(x, 130, x + cw, 162, 16, "#242424", "#3a3a3a", "spot")
        oval_(P(x+14, 141, x+24, 151), fill=G0 if sp_ok else (C["org"] if sp_ok is False else C["idle"]), outline="", tags="spot")
        text(x + 32, 146, "Spotify", 12, C["mu"], tag="spot")
        if sp_ok:
            text(x + cw - 26, 146, "Connected", 12, G0, True, "e", "spot"); chev_right(x + cw - 16, 146, C["mu"], "spot", 12)
        elif sp_ok is False:
            rr(x + cw - 86, 136, x + cw - 8, 156, 10, "#4a3216", C["org"], "spot"); text(x + cw - 52, 146, "Log in", 11, C["org"], True, "center", "spot"); chev_right(x + cw - 22, 146, C["org"], "spot", 11)
        else: text(x + cw - 14, 146, "...", 12, C["mu"], True, "e", "spot")
        click("spot", login); tip("spot", "Log in to Spotify" if not sp_ok else "Log in again")
        x = M + cw + 10; gv = state["game"]; gc = G0 if gv else C["idle"]
        rr(x, 130, x + cw, 162, 16, C["card"])
        oval_(P(x+14, 141, x+24, 151), fill=gc, outline=""); text(x + 32, 146, "Game", 12, C["mu"])
        text(x + cw - 14, 146, "..." if gv is None else ("Running" if gv else "Not running"), 12, gc, True, "e")
        # collapsible Playlists section (collapsed by default)
        if ui["open"]:                                      # one card: header + age rows, symmetric insets
            rr(M, PL_TOP, R_, PL_TOP + PL_H, 10, C["card"]); cv.create_line(*P(M + 12, PL_TOP + 36, R_ - 12, PL_TOP + 36), fill=C["line"])
        rr(M, PL_TOP, R_, PL_TOP + 36, 10, C["card"], tag="plh")
        cv.create_image(*P(M + 24, PL_TOP + 18), image=pl_icon(C["acc"]), anchor="center", tags=("plh", "plicon"))   # accent: grey when Disabled
        text(M + 46, PL_TOP + 18, "Playlists", 13, b=True, tag="plh")                 # title column of Fade / Age Intros
        cv.create_image(*P(R_ - 18, PL_TOP + 18), image=chev_up if ui["open"] else chev_down, anchor="center", tags="plh")
        click("plh", lambda: (ui.update(open=not ui["open"], am=False), draw()))
        X = M + 22; XR = R_ - 22                           # age rows: same inset left and right
        for i, (k, lab) in enumerate(AGES if ui["open"] else []):
            rx = XR - 6 - 30; y = PL_Y(i); uri = cfg["playlists"].get(k, ""); is_def = uri == defaults.get(k)
            if i < len(AGES) - 1: cv.create_line(*P(X + 48, y + 44, XR, y + 44), fill="#2a2a2a", tags="pldiv")
            rr(X - 6, y, XR + 6, y + 42, 9, "#262626", tag="rowhl%d" % i); cv.itemconfigure("rowhl%d" % i, state="normal" if hov.get("row") == i else "hidden")
            if k == state.get("active"): fire_row(X - 6, y, XR + 6, y + 42, 9)
            pid = uri.split(":")[-1]
            cimg = cover_img(custom_cover(uri) if is_custom(uri) else (covers.get(pid) or (cover_file(pid) if pid else None)))
            if cimg:                                       # playlist cover: same zone as the name text (opn%d)
                cv.create_image(*P(X + 24, y + 21), image=cimg, anchor="center", tags=("opn%d" % i, "cov%d" % i))
            else:                                          # fallback age icon: also part of the name zone
                last = (cv.find_all() or (0,))[-1]
                rr(X + 9, y + 6, X + 39, y + 36, 6, C["ib"]); icon(i, X + 24, y + 21, GREY_ACC)   # stock age icons: always the quiet grey (less green); real covers unchanged
                for it_ in cv.find_all():
                    if it_ > last: cv.addtag_withtag("opn%d" % i, it_)
            rr(X + 38, y + 7, rx - 76, y + 35, 8, "", tag="opn%d" % i)          # transparent hit area (gaps between texts)
            text(X + 48, y + 21, lab, 13, b=True, tag="opn%d" % i)
            oval_(P(X+118, y+17, X+126, y+25), fill=C["acc"] if uri else C["idle"], outline="", tags="opn%d" % i)
            nm = pl_name(uri); nm = nm if len(nm) <= 15 else nm[:14] + "\u2026"
            text(X + 132, y + 21, nm, 12, C["mu"], tag="opn%d" % i)
            if pid:
                click("opn%d" % i, lambda pid=pid, uri=uri, k=k, lab=lab: change(k, lab) if is_custom(uri) else open_playlist(pid))
                tip("opn%d" % i, "Edit list" if is_custom(uri) else "Open in Spotify"); hover_hl(i)
            rr(rx - 70, y + 9, rx - 8, y + 33, 12, C["card"], C["acc"], ("chg%d" % i, "chgx")); text(rx - 39, y + 21, "Change", 10, C["acc"], True, "center", ("chg%d" % i, "chgx"))
            ht = ("chg%d" % i, "chgx", "chgh%d" % i, "chghx"); hb, hf = ("#1ed760", "#1f3b29") if en else ("#8a8a8a", "#2a2a2a")   # hovered look, on top
            rr(rx - 70, y + 9, rx - 8, y + 33, 12, hf, hb, ht); text(rx - 39, y + 21, "Change", 10, hb, True, "center", ht)
            cv.itemconfigure("chg%d" % i, state="normal" if hov.get("row") == i else "hidden"); cv.itemconfigure("chgh%d" % i, state="hidden")   # hover-only: hidden before first paint
            rc = C["dis"] if is_def else C["mu"]
            rr(rx, y + 9, rx + 30, y + 33, 12, C["card"], rc, "rev%d" % i); undo_icon(rx + 15, y + 21, rc, "rev%d" % i)
            click("chg%d" % i, lambda k=k, lab=lab: change(k, lab))
            if not is_def: click("rev%d" % i, lambda k=k: revert(k))
            tip("rev%d" % i, "Revert" if not is_def else "Revert (already default)")
        fire_start()
        # Age 4 Intro theme
        base = PL_TOP + (PL_H if ui["open"] else 36) + 10              # Age Intros card top
        Hn = base + 56 + (AM_H if ui.get("am") else 46) + M
        ui["H"] = Hn                                       # applied after the whole frame is drawn (see draw wrapper)
        y = base; bon = bool((cfg.get("boss_intro") or {}).get("enabled", True))
        rr(M, y, R_, y + 46, 10, C["card"], tag="intro"); icon(3, M + 24, y + 23, crown_color(bon, en), "crown_intro")
        text(M + 46, y + 23, "Age Intros", 13, b=True, tag="intro")
        sx = M + 46 + tkfont.Font(font=F(13, True)).measure("Age Intros") / S + 14
        ion = cfg.get("intros") or {}
        for j, (a_, rn) in enumerate(zip(INTRO_AGES, ROMAN)):   # one pip per age, lit when its intro is on
            lit = bool((ion.get(a_) or {}).get("enabled")) and bon; px_ = sx + 11 + j * 25
            oval_(P(px_ - 10, y + 13, px_ + 10, y + 33), fill=C["acc"] if lit else "#2a2a2a", outline="" if lit else "#3a3a3a", tags="intro")
            text(px_, y + 23, rn, 9, "#121212" if lit else C["mu"], True, "center", "intro")
        toggle(R_ - 30 - 44, y + 11, bon, "boss")
        chev_right(R_ - 15, y + 23, C["mu"], "intro", 16)
        click("intro", open_editor); tip("intro", "Intro song per age and civ")
        click("boss", lambda: (set_user("boss_intro_enabled", not bon), editor_redraw()))
        # fade
        y = FADE_Y; fv = float(cfg.get("fade_seconds", 2)); fcol = C["acc"] if fv else GREY_ACC   # Fade off: the disabled grey (never dimmer)
        rr(M, y, R_, y + 46, 10, C["card"])
        cv.create_image(*P(M + 24, y + 23), image=fade_icon(fcol), anchor="center", tags="fadeicon")
        text(M + 46, y + 23, "Fade", 13, b=True)
        x0, x1 = FX0, FX1; xv = x0 + (x1 - x0) * fv / 5
        rr(x0, y + 20, x1, y + 26, 3, C["off"], tag="fade"); rr(x0, y + 20, max(xv, x0 + 6), y + 26, 3, fcol, tag="fade")
        oval_(P(xv-9, y+14, xv+9, y+32), fill="white", outline=fcol, width=2*S, tags="fade")
        text(R_ - 12 - 30 - 10, y + 23, ("%.1fs" % fv) if fv else "Off", 12, fcol, True, "e")
        fdef = float(base_cfg.get("fade_seconds", 2)); f_is_def = abs(fv - fdef) < 1e-6
        rc = C["dis"] if f_is_def else C["mu"]          # revert to default fade, right-aligned like playlist rows
        rx = R_ - 12 - 30
        rr(rx, y + 11, rx + 30, y + 35, 12, C["card"], rc, "revf"); undo_icon(rx + 15, y + 23, rc, "revf")
        if not f_is_def: click("revf", lambda: (user.pop("fade_seconds", None), save_user(user), draw()))
        tip("revf", "Revert" if not f_is_def else "Revert (already default)")
        # After match: expandable radio list (what the music does when a match ends)
        y = base + 56; am = after_match_cfg(cfg); mode = am["mode"]; aopen = bool(ui.get("am"))
        if aopen: rr(M, y, R_, y + AM_H, 10, C["card"])
        rr(M, y, R_, y + 46, 10, C["card"], tag="amh")
        cv.create_image(*P(M + 24, y + 23), image=vic("flag", C["acc"], C["card"]), anchor="center", tags="amh")
        text(M + 46, y + 23, "After match", 13, b=True, tag="amh")
        cv.create_image(*P(R_ - 18, y + 23), image=chev_up if aopen else chev_down, anchor="center", tags="amh")
        click("amh", lambda: (ui.update(am=not ui.get("am"), open=False), draw()))
        suri = am["playlist"] if mode == "playlist" else ""
        lab = am_trunc(am_name(suri), 14) if suri else dict(AM_ROWS)[mode]
        text(R_ - 36, y + 23, lab, 12, C["acc"], True, "e", "amh")
        tw = tkfont.Font(font=F(12, True)).measure(lab) / S; hx = R_ - 36 - tw - 8
        cim = am_cover(suri, 22) if suri else None
        if cim: cv.create_image(*P(hx - 11, y + 23), image=cim, anchor="center", tags="amh"); hx -= 22 + 8
        if am["wl"]:                                      # Win / Loss on: trophy hint, then an arrow to the choice
            cv.create_image(*P(hx - 8, y + 23), image=vic("then", C["mu"], C["card"]), anchor="center", tags="amh")
            cv.create_image(*P(hx - 30, y + 23), image=vic("trophy", "#e0b040", C["card"]), anchor="center", tags="amh")
        if aopen:
            cv.create_line(*P(M + 12, y + 46, R_ - 12, y + 46), fill=C["line"])
            XL, XR = M + 22, R_ - 22; CC = XR - 72               # same insets as Playlists; cover column
            wl = am["wl"]; wy = y + 52 + 20; wbg = "#232a25" if wl else C["card"]   # Win / Loss toggle line
            rr(XL - 6, wy - 20, XR + 6, wy + 20, 9, wbg, tag="amwl")
            cv.create_image(*P(XL + 8, wy), image=vic("trophy", C["acc"] if wl else C["mu"], wbg), anchor="center", tags="amwl")
            text(XL + 28, wy, "Win / Loss", 12, C["tx"] if wl else C["mu"], True, tag="amwl")
            if wl:
                cv.create_image(*P(CC - 76, wy), image=vic("trophy", "#e0b040", wbg), anchor="center", tags="amw")
                am_slot(CC - 50, wy, am["win"], "amw")
                cv.create_image(*P(CC - 24, wy), image=vic("skull", C["red"], wbg), anchor="center", tags="aml")
                am_slot(CC, wy, am["loss"], "aml")
                click("amw", lambda: am_pick("win")); click("aml", lambda: am_pick("loss"))
                tip("amw", "Victory: click or drop a song / playlist"); tip("aml", "Defeat: click or drop a song / playlist")
            toggle(XR - 44, wy - 12, wl, "amtg")
            click("amtg", lambda wl=wl: am_wl(not wl)); click("amwl", lambda wl=wl: am_wl(not wl))
            ty = wy + 20 + 13
            text(XL + 48, ty, "Then", 10.5, C["mu"], True)
            lx = XL + 48 + tkfont.Font(font=F(10.5, True)).measure("Then") / S + 10
            cv.create_line(*P(lx, ty, XR, ty), fill=C["line"])
            for i, (k, lab) in enumerate(AM_ROWS):
                ry = ty + 13 + i * 42 + 21; on = k == mode; tg = "amr%d" % i; bgc = "#262a27" if on else C["card"]
                if i < len(AM_ROWS) - 1 and not on and AM_ROWS[i + 1][0] != mode:
                    cv.create_line(*P(XL + 54, ry + 21, XR, ry + 21), fill="#2a2a2a")
                rr(XL - 6, ry - 19, XR + 6, ry + 19, 9, bgc, tag=tg)
                oval_(P(XL + 1, ry - 7, XL + 15, ry + 7), outline=C["acc"] if on else "#5a5a5a", width=1.6 * S, tags=tg)
                if on: oval_(P(XL + 4.5, ry - 3.5, XL + 11.5, ry + 3.5), fill=C["acc"], tags=tg)
                cv.create_image(*P(XL + 34, ry), image=vic(k, C["acc"] if on else C["mu"], bgc), anchor="center", tags=tg)
                text(XL + 54, ry, lab, 12, C["tx"] if on else C["mu"], on, tag=tg)
                click(tg, lambda k=k: am_select(k))
                if k == "resume": text(XR, ry, "Pre-match", 11, C["mu"], False, "e", tg)
                elif k == "playlist":
                    am_slot(CC, ry, am["playlist"], "amp")
                    text(CC + 16, ry, am_trunc(am_name(am["playlist"]), 10) if am["playlist"] else "Pick", 11.5, C["tx"] if on else C["mu"], on, tag="amp")
                    chev_right(XR - 2, ry, C["mu"], "amp", 14); click("amp", lambda: am_pick("playlist")); tip("amp", "Pick a playlist")
        # gear menu (drawn on top, with a dim layer that closes it)
        if ui.get("menu"):
            cv.create_image(0, 0, anchor="nw", tags="menubg", image=_img(("dim", Hn), int(W * S), int(Hn * S),
                            lambda d, Q: d.rectangle([0, 0, W * S * Q, Hn * S * Q], fill=(0, 0, 0, 90))))
            click("menubg", lambda: (ui.update(menu=False), draw()))
            rr(gx, 14, R_, 46, 10, "#2a2a2a", tag="gear"); cv.create_image(*P(gx + 16, 30), image=gear_img[True], anchor="center", tags="gear")
            mx0, my0 = R_ - 158, 52
            mx0 = R_ - 190
            import aoe4spotify.core.settings as _s; own = _s.OWN_APP_ENABLED; dy = 0 if own else -32
            rr(mx0, my0, R_, my0 + 180 + REP_ROW + dy, 10, "#262626", "#3a3a3a")
            gw = tkfont.Font(font=F(12)).measure("\u2630  ") / S                 # label column of the other items
            rep_on = bool(cfg.get("music_in_replays", False))                  # 'Music in replays' (off by default): its own settings group on top
            rr(mx0 + 6, my0 + 6, R_ - 6, my0 + 38, 7, "#262626", tag="m_rep")
            cv.create_image(*P(mx0 + 20 + (gw - 8) / 2, my0 + 22), image=rep_icon(), anchor="center", tags="m_rep")
            text(mx0 + 20 + gw, my0 + 22, "Music in replays", 12, C["tx"], tag="m_rep")
            toggle(R_ - 14 - 30, my0 + 22 - 8, rep_on, "m_rep", 30, 16)
            cv.create_line(*P(mx0 + 10, my0 + 41, R_ - 10, my0 + 41), fill="#3a3a3a"); my0 += REP_ROW
            rr(mx0 + 6, my0 + 6, R_ - 6, my0 + 38, 7, "#262626", tag="m_chk"); text(mx0 + 20, my0 + 22, "\u21bb  Check for updates", 12, C["tx"], tag="m_chk")
            rr(mx0 + 6, my0 + 38, R_ - 6, my0 + 70, 7, "#262626", tag="m_log"); text(mx0 + 20, my0 + 54, "\u2630  Open log", 12, C["tx"], tag="m_log")
            gw = tkfont.Font(font=F(12)).measure("\u2630  ") / S                 # label column of the other items
            rr(mx0 + 6, my0 + 70, R_ - 6, my0 + 102, 7, "#262626", tag="m_gh")
            cv.create_image(*P(mx0 + 20 + (gw - 8) / 2, my0 + 86), image=gh_icon(), anchor="center", tags="m_gh")
            text(mx0 + 20 + gw, my0 + 86, "GitHub", 12, C["tx"], tag="m_gh")
            if own: rr(mx0 + 6, my0 + 102, R_ - 6, my0 + 134, 7, "#262626", tag="m_own"); text(mx0 + 20, my0 + 118, "\u25ce  Your Spotify app", 12, C["tx"], tag="m_own")
            cv.create_line(*P(mx0 + 10, my0 + 140 + dy, R_ - 10, my0 + 140 + dy), fill="#3a3a3a")
            rr(mx0 + 6, my0 + 144 + dy, R_ - 6, my0 + 174 + dy, 7, "#262626", tag="m_un"); text(mx0 + 20, my0 + 159 + dy, "\u2715  Uninstall", 12, C["red"], True, tag="m_un")
            click("m_rep", lambda: set_user("music_in_replays", not rep_on))      # stays open: you see it flip
            click("m_gh", lambda: (ui.update(menu=False), draw(), open_github()))
            click("m_chk", lambda: (ui.update(menu=False), draw(), check_now()))
            click("m_log", lambda: (ui.update(menu=False), draw(), open_log()))
            if own: click("m_own", lambda: (ui.update(menu=False), draw(), byo_dialog(root, on_saved=login, on_shared=login)))
            click("m_un", lambda: (ui.update(menu=False), draw(), uninstall()))

    FX0, FX1 = M + 94, W - M - 12 - 30 - 62          # fade slider track (leaves room for value + revert)
    base_cfg = load_config(user=False)
    drag = {"on": False}
    def slide(e, save=False):
        if not drag["on"]: return
        v = round(max(0, min(5, (e.x / S - FX0) / (FX1 - FX0) * 5)) * 2) / 2
        if save: drag["on"] = False; set_user("fade_seconds", v)
        elif v != user.get("fade_seconds"): user["fade_seconds"] = v; draw()
    cv.tag_bind("fade", "<ButtonPress-1>", lambda e: (drag.update(on=True), root.after_idle(lambda: slide(e))))
    cv.bind("<B1-Motion>", lambda e: root.after_idle(lambda: slide(e)))
    cv.bind("<ButtonRelease-1>", lambda e: root.after_idle(lambda: slide(e, True)))

    def dialog(title, prompt, tracks=None):          # tracks=None: playlist id; else full uri (songs too if True)
        d = tk.Toplevel(root); dark_window(d, C["card"]); d.title(APP_NAME); d.transient(root); d.resizable(False, False)
        tk.Label(d, text=prompt, bg=C["card"], fg=C["tx"], font=F(12, True), justify="left").pack(padx=16, pady=(14, 6), anchor="w")
        e = tk.Entry(d, width=52, bg=C["ib"], fg=C["tx"], insertbackground=C["tx"], relief="flat", font=F(12)); e.pack(padx=16, ipady=5)
        err = tk.Label(d, text="", bg=C["card"], fg=C["red"], font=F(10)); err.pack(padx=16, anchor="w")
        res = {}
        def ok(_=None):
            m = RE_PLAYLIST.search(e.get().strip())
            if tracks is not None:
                tm = parse_track(e.get().strip()) if tracks else None
                if m or tm: res["id"] = ("spotify:playlist:" + m.group(1)) if m else tm; d.destroy(); return
                err.config(text="Paste a Spotify %s link" % ("song or playlist" if tracks else "playlist")); return
            if not m: err.config(text="That's not a Spotify playlist link (open.spotify.com/playlist/...)"); return
            res["id"] = m.group(1); d.destroy()
        row = tk.Frame(d, bg=C["card"]); row.pack(padx=16, pady=(4, 14), anchor="e")
        tk.Button(row, text="Cancel", command=d.destroy, bg=C["ib"], fg=C["tx"], relief="flat", font=F(11), padx=12).pack(side="left", padx=6)
        tk.Button(row, text="Save", command=ok, bg=G0, fg="black", relief="flat", font=F(11, True), padx=14).pack(side="left")
        reveal(d, fade=False, over=root); after_mouse_up(d, lambda: d.grab_set()); e.bind("<Return>", ok); e.focus_set(); root.wait_window(d)
        return res.get("id")

    def change(k, lab):
        old = (cur()["playlists"] or {}).get(k, "")
        uri = list_picker(root, "%s Age" % lab, old, False, user, save_user, start_builder=is_custom(old))
        if not uri: draw(); return
        pls = dict(user.get("playlists") or {}); pls[k] = uri
        set_user("playlists", pls); fetch_names()

    AM_ROWS = [("resume", "Resume"), ("playlist", "Playlist"), ("stop", "Stop")]
    AM_H = 46 + 6 + 40 + 26 + len(AM_ROWS) * 42 + 8
    def am_trunc(t_, n): return t_ if len(t_) <= n else t_[:n - 1] + "\u2026"
    def am_name(uri):
        if not uri: return ""
        if is_custom(uri): return (custom_get(uri, user) or {}).get("name") or "My list"
        return names.get(uri.split(":")[-1]) or ("Song" if uri.startswith("spotify:track:") else "Playlist")
    def am_cover(uri, size):
        if not uri: return None
        i_ = uri.split(":")[-1]
        if is_custom(uri): pth = custom_cover(uri)
        elif uri.startswith("spotify:track:"): pth = covers.get(i_) or track_cover(uri)
        else: pth = covers.get(i_) or cover_file(i_)
        return cover_img(pth, size)
    def am_slot(cx, cy, uri, tag):                     # 24 px cover, or an empty '+' slot
        ci = am_cover(uri, 24)
        if ci: cv.create_image(*P(cx, cy), image=ci, anchor="center", tags=tag)
        else:
            rr(cx - 12, cy - 12, cx + 12, cy + 12, 5, C["ib"], tag=tag)
            cv.create_image(*P(cx, cy), image=vic("plus", C["mu"], C["ib"]), anchor="center", tags=tag)
    def am_select(k):
        a = dict(user.get("after_match") or {}); a["mode"] = k; set_user("after_match", a)
        if k == "playlist" and not after_match_cfg(cur())["playlist"]: root.after_idle(lambda: am_pick("playlist"))
    def am_wl(on):
        a = dict(user.get("after_match") or {}); a["winloss_on"] = on
        if a.get("mode") == "winloss": a["mode"] = "stop"
        set_user("after_match", a)
    def am_set(which, uri):
        a = dict(user.get("after_match") or {}); a[which] = uri; a["winloss_on"] = True
        if a.get("mode") == "winloss": a["mode"] = "stop"
        set_user("after_match", a); fetch_names()
    def am_drop(e):
        """Spotify song/playlist dropped on the panel: lands in the Victory or Defeat slot under the pointer."""
        try:
            px, py = int(e.x_root) - cv.winfo_rootx(), int(e.y_root) - cv.winfo_rooty()
            tags = set()
            for it in cv.find_overlapping(px - 2, py - 2, px + 2, py + 2): tags.update(cv.gettags(it))
            which = "win" if "amw" in tags else "loss" if "aml" in tags else None
            if not which: return
            m = RE_PLAYLIST.search(e.data or ""); tr = parse_track(e.data or "")
            uri = ("spotify:playlist:" + m.group(1)) if m else tr
            if uri: log("After match: dropped %s on %s" % (uri, which)); am_set(which, uri)
        except Exception as ex: log("After match drop: %r" % ex)
    def am_pick(which):
        a0 = after_match_cfg(cur()); old = a0.get(which, "")
        uri = list_picker(root, {"playlist": "After match playlist", "win": "Victory", "loss": "Defeat"}[which], old,
                          which != "playlist", user, save_user, start_builder=is_custom(old))
        if not uri: draw(); return
        a = dict(user.get("after_match") or {}); a[which] = uri
        if which == "playlist": a["mode"] = "playlist"
        else:
            a["winloss_on"] = True
            if a.get("mode") == "winloss": a["mode"] = "stop"
        set_user("after_match", a); fetch_names()
    def revert(k):
        pls = dict(user.get("playlists") or {}); pls.pop(k, None); set_user("playlists", pls); fetch_names()

    def show_gtg():                                    # access just started working: no new login needed
        def go():
            st = _g_app().setup_status(Spotify(load_config())); refresh_now(); fetch_names()
            post(lambda: good_to_go(st, parent=root, on_open_panel=lambda: None, on_retry=login,
                                    fix=lambda: game().fix_launch_option()))
        threading.Thread(target=go, daemon=True).start()
    def pending_access():                              # asked for access earlier: check once on start
        if not load_user_settings().get("access_pending"): return
        def go():
            r = access_status(Spotify(load_config()))
            if r == "ok":
                merge_user(remove=("access_pending",)); show_gtg()
            elif r == "blocked":
                if using_own_app():
                    post(lambda: byo_dialog(root, problem=True, on_saved=login, on_shared=login))
                else:
                    post(lambda: access_dialog(root, on_allowed=show_gtg, on_own=login))
        threading.Thread(target=go, daemon=True).start()
    def login():
        def go():
            sp = Spotify(load_config())
            try: sp.login()
            except BaseException as e: log("Login failed: %r" % e); sp.tok = None
            if access_status(sp) == "blocked":
                if using_own_app():
                    post(lambda: byo_dialog(root, problem=True, on_saved=login, on_shared=login))
                else:
                    post(lambda: access_dialog(root, on_allowed=lambda: show_gtg(), on_own=login))
                return
            st = _g_app().setup_status(sp)
            refresh_now(); fetch_names()
            post(lambda: good_to_go(st, parent=root, on_open_panel=lambda: None, on_retry=login,
                                    fix=lambda: game().fix_launch_option()))
        threading.Thread(target=go, daemon=True).start()

    art = Art(root, S)
    try:                                               # drag songs / playlists from Spotify onto Victory / Defeat
        from tkinterdnd2 import TkinterDnD, DND_TEXT
        TkinterDnD._require(root); cv.drop_target_register(DND_TEXT)
        cv.dnd_bind("<<DropPosition>>", lambda e: "copy")
        cv.dnd_bind("<<Drop>>", lambda e: (root.after_idle(lambda d=e: am_drop(d)), "copy")[1])
    except Exception as ex: log("Panel drag-in unavailable: %r" % ex)
    _ed_win = [None]; _ed_shift = [(0, 0)]
    def open_editor():                                # Age Intros: a page of this window, grown evenly around its centre
        w = _ed_win[0]
        if w is not None and w.winfo_exists(): return
        hide_tip(); fire_stop(); root.update_idletasks()
        x0, y0, w0 = root.winfo_x(), root.winfo_y(), root.winfo_width()
        page = pool_editor(root, user, lambda: (save_user(user), draw()), on_close=close_editor, height=int(cv.cget("height")) / S)
        _ed_win[0] = page; page.update_idletasks()      # built and drawn BEFORE the panel is hidden
        nw, nh = page.winfo_reqwidth(), page.winfo_reqheight()
        dx = -((nw - w0) // 2)                          # wider evenly left/right; taller only downward (title bar stays)
        def go():
            swap_pages(root, cv, page, nw, nh, x0 + dx, y0)
            try: page._ed["cv"].focus_set()
            except Exception: pass
            kx, ky = keep_on_screen(root); _ed_shift[0] = (dx + kx, ky)
        _ed_shift[0] = (dx, 0)
        cover(root, (-dx, 0, -dx, max(0, nh - root.winfo_height())), go)
    def close_editor():                               # back to the panel: same size and spot as before
        page = _ed_win[0]; _ed_win[0] = None; dx, dy = _ed_shift[0]; _ed_shift[0] = (0, 0)
        hov.update(xy=None); draw()                     # panel drawn BEFORE the page is hidden
        x, y = root.winfo_x() - dx, root.winfo_y() - dy
        if page is not None and page.winfo_exists() and page.winfo_manager():
            def go():
                try: swap_pages(root, page, cv, cv.winfo_reqwidth(), cv.winfo_reqheight(), x, y)
                finally:
                    try: page.destroy()
                    except Exception: pass
                cv.focus_set(); fire_start()
            return "later" if cover(root, (0, 0, 0, 0), go) else None
        cv.pack()
        if dx or dy: root.geometry("+%d+%d" % (x, y))
        cv.focus_set(); fire_start()
    def editor_redraw():                              # Age Intros window open: its crown follows the toggles live
        w = _ed_win[0]
        try:
            if w is not None and w.winfo_exists(): w._ed["draw"]()
        except Exception: pass
    pending_access()

    def start_update():
        info = upd["info"]
        if not info or upd["phase"] in ("dl", "run"): return
        if game().running(): upd.update(phase="error", msg="Close %s to update" % game().label); draw(); return   # setup won't install mid-game
        upd.update(phase="dl", pct=0); draw()
        dest = os.path.join(os.environ.get("TEMP") or DATA, SETUP_FILE_MANUAL % info["version"])
        def go():
            try:
                download_update(info, dest, lambda f: (upd.update(pct=int(f * 100)), post(draw)) if int(f * 100) != upd["pct"] else None)
                upd.update(phase="run"); post(draw)
                post(lambda: (run_update(dest), root.after(400, root.destroy)))   # Setup closes us anyway
            except Exception as e:
                log("Update failed: %r" % e); upd.update(phase="error", msg="Update failed \u2013 retry"); post(draw)
        threading.Thread(target=go, daemon=True).start()

    def check_updates():
        def go():
            info = check_update()
            if info and upd["phase"] in ("idle", "done"):
                upd.update(info=info, phase="avail"); post(draw)
                if os.environ.get("AOE4SPOTIFY_TEST_AUTOUPDATE") == "1": post(start_update)   # testing only
        threading.Thread(target=go, daemon=True).start()

    def check_now():
        """Gear menu 'Check for updates': pill shows the result; 'Up to date' / 'Couldn't check' fade after ~2s."""
        if upd["phase"] in ("dl", "run"): return
        upd.update(phase="done", msg="Checking\u2026"); draw()
        def go():
            try: info = check_update(report=True); res = ("avail", "", info) if info else ("done", "Up to date", None)
            except Exception: res = ("error", "Couldn't check", None)
            def show():
                if res[0] == "avail": upd.update(phase="avail", msg="", info=res[2])
                else: upd.update(phase=res[0], msg=res[1], info=None)
                draw()
                if res[0] != "avail":
                    root.after(2000, lambda: upd["phase"] in ("done", "error") and not upd["info"] and (upd.update(phase="idle", msg=""), draw()))
            post(show)
        threading.Thread(target=go, daemon=True).start()

    def open_log():
        if not os.path.exists(LOGFILE): open(LOGFILE, "a").close()
        os.startfile(LOGFILE)

    def uninstall():
        from tkinter import messagebox
        un = os.path.join(HERE, "unins000.exe")
        if not os.path.exists(un): messagebox.showinfo("Uninstall", "Uninstaller not found (not installed?)."); return
        steam = " Steam will close for a moment and reopen by itself." if game().launcher_running() else ""
        if messagebox.askyesno(("Uninstall " + APP_NAME + "?"), "Removes the app, its shortcuts and settings, and puts the game's launch options and music volume back." + steam):
            subprocess.Popen([un, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], env=child_env()); root.destroy()   # one click: no further boxes

    def fetch_names():
        def go():
            try:
                cfg = load_config(); sp = Spotify(cfg)
                if not sp.tok: return
                changed = False
                am = after_match_cfg(cfg)
                for uri in set(cfg["playlists"].values()) | set(defaults.values()) | ({am["playlist"], am["win"], am["loss"]} - {""}):
                    pid = uri.split(":")[-1]
                    if is_custom(uri): continue
                    if uri.startswith("spotify:track:"):              # After match: Victory / Defeat song
                        if pid not in names or not os.path.exists(track_cover(uri)):
                            r_ = fetch_track(sp, uri, int(round(30 * S * 1.5)))
                            if r_ and names.get(pid) != r_[0]: names[pid] = r_[0]; changed = True
                        if os.path.exists(track_cover(uri)) and covers.get(pid) != track_cover(uri): covers[pid] = track_cover(uri); changed = True
                        continue
                    if not pid: continue
                    nm, path = update_cover(sp, pid, int(round(30 * S * 1.5)))
                    if nm and names.get(pid) != nm: names[pid] = nm; changed = True
                    if path and covers.get(pid) != path: covers[pid] = path; changed = True
                if changed:
                    os.makedirs(DATA, exist_ok=True)
                    json.dump(names, open(NAMES_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                    post(draw)
            except Exception as e: log("Playlist names: %r" % e)
        threading.Thread(target=go, daemon=True).start()

    _draw = draw
    def draw():                                    # full redraw (state changes only, never on hover)
        t0 = time.perf_counter(); _draw(); ui["dt"] = time.perf_counter() - t0
        if ui.get("H"): set_canvas_height(cv, int(ui["H"] * S))
        tg = hov["tip"]; on_pointer(force=True)      # re-apply hover state to the new items
        if tg and hov["tip"] == tg and not tipst["shown"]: pass
    def refresh_now():
        def go():
            gr = game().running()
            s = {"spotify": os.path.exists(TOKEN), "game": gr, "active": read_now_playing() if gr else None}
            if preview: s.update(game=True, active=None if pv["paused"] else pv["key"])
            if s != state: state.update(s); post(draw)
        threading.Thread(target=go, daemon=True).start()
    def tick():
        if not win_hidden(root): refresh_now()        # minimized: nothing to show, no polling
        fire_start()                                  # restored / card reopened: resume the row fire
        root.after(3000, tick)
    pq = {"idle": 0}
    def pump():                                   # run UI updates queued by worker threads (Tk isn't thread-safe)
        busy = bool(ui_q)
        while ui_q:
            try: ui_q.pop(0)()
            except Exception as e: log("Panel update failed: %r" % e)
        pq["idle"] = 0 if busy else pq["idle"] + 1
        root.after(60 if pq["idle"] < 10 else (1000 if win_hidden(root) else 150), pump)   # fast only while work flows

    if upd["phase"] == "done": root.after(6000, lambda: (upd.update(phase="idle") if upd["phase"] == "done" else None, draw()))
    def warm_panel():                              # build both expandable cards once (fonts, images, covers)
        keep = dict(ui)
        for st_ in ({"open": True, "am": False}, {"open": False, "am": True}):
            ui.update(st_); draw(); root.update_idletasks()
        ui.clear(); ui.update(keep); draw()
        threading.Thread(target=_pwr_prerender, daemon=True).start()
    root._set_user = set_user
    root._press = lambda t: handlers[t](); root._editor = _ed_win; root._cv = cv   # (tests)
    root._ui = ui                                      # (tests)
    pv = {"key": AGES[0][0] if AGES else None, "paused": False}      # --fire-preview: fake playing state
    if preview:
        ui["open"] = True
        def pv_set(**k):
            pv.update(k); state.update(game=True, active=None if pv["paused"] else pv["key"]); draw()
        for i_, (k_, _l) in enumerate(AGES[:9]):
            root.bind(str(i_ + 1), lambda e, k_=k_: pv_set(key=k_, paused=False))
        root.bind("p", lambda e: pv_set(paused=not pv["paused"])); root.bind("P", lambda e: pv_set(paused=not pv["paused"]))
        root.bind("<Escape>", lambda e: (fx["job"] and root.after_cancel(fx["job"]), fx.update(job=None), root.destroy()))
        state.update(game=True, active=pv["key"])
    root._pv = pv                                      # (tests)
    draw(); reveal(root, warm=warm_panel); note_window("panel", root); pump(); tick()
    if not preview: fetch_names(); check_updates()
    root.mainloop()
