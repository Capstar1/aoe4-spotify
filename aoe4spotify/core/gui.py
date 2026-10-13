"""The settings window, playlist picker, age-intro editor, and good-to-go screen.
"""

import json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request, webbrowser
from aoe4spotify.core.access import access_dialog, access_status
from aoe4spotify.core.byo import byo_dialog
from aoe4spotify.core.runtime import ASSETS, DATA, GITHUB_URL, HERE, ImageColor_rgb, LOGFILE, TOKEN, VERSION, atomic_write, child_env, dark_window, focus_window, log, note_window, release_window, reveal, set_canvas_height, single_window, win_hidden
from aoe4spotify.core.settings import CUSTOM_MAX, CUSTOM_PREFIX, DEFAULT_PRESET_NAME, INTRO_AGES, _LIVE_USER, after_match_cfg, apply_preset, apply_user, build_intros, custom_cover, custom_get, decode_preset, encode_preset, is_custom, load_config, load_user, load_user_settings, merge_user, migrate_intros_v2, preset_counts, preset_from_user, preset_key, preset_songs, save_user, unique_preset_name, user_presets, using_own_app
from aoe4spotify.core.spotify import Spotify
from aoe4spotify.core.updater import check_update, download_update, run_update
from aoe4spotify.games.aoe4_setup import aoe_running, launch_option_is_set, music_sync, set_launch_option, steam_running, with_steam_closed

def _g_app():
    import aoe4spotify.core.app as _m
    return _m

def good_to_go(status, parent=None, on_open_panel=None, on_retry=None, fix=None):
    """Panel-style result window after Spotify login. status from setup_status().
    parent: an existing Tk root (from the panel) or None (own window, blocks until closed)."""
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk
    try: import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", red="#e5484d", warn="#f5a524")
    if not single_window("gtg", "AoE4 Spotify"): return None
    win = tk.Toplevel(parent) if parent else tk.Tk()
    dark_window(win, C["bg"])
    win.bind("<Destroy>", lambda e: release_window("gtg") if e.widget is win else None, add="+")
    win.title("AoE4 Spotify"); win.configure(bg=C["bg"]); win.resizable(False, False)
    S = win.winfo_fpixels("1i") / 96.0
    W = 400
    cv = tk.Canvas(win, width=int(W * S), height=10, bg=C["bg"], highlightthickness=0); cv.pack()
    imgs = []
    def F(sz, b=False): return ("Segoe UI", -int(sz * S), "bold" if b else "normal")
    def pil(w, h, paint):                         # 4x supersampled, anti-aliased
        m = 4; im = Image.new("RGBA", (int(w * S * m), int(h * S * m)), (0, 0, 0, 0)); paint(ImageDraw.Draw(im), S * m)
        ph = ImageTk.PhotoImage(im.resize((max(1, int(w * S)), max(1, int(h * S))), Image.LANCZOS), master=win)
        imgs.append(ph); return ph
    def rr(x0, y0, x1, y1, r, fill, outline=None, tag=None):
        ph = pil(x1 - x0, y1 - y0, lambda d, k: d.rounded_rectangle([0, 0, (x1-x0)*k - 1, (y1-y0)*k - 1], r * k, fill=fill,
                                                                   outline=outline, width=int(2 * k) if outline else 0))
        cv.create_image(x0 * S, y0 * S, image=ph, anchor="nw", tags=tag or ())
    def mark(cx, cy, size, kind, tag=None):       # filled circle with a check / cross / !
        col = {"ok": C["acc"], "bad": C["red"], "warn": C["warn"]}[kind]
        def paint(d, k):
            z = size * k; d.ellipse([0, 0, z - 1, z - 1], fill=col); w = max(2, int(z * 0.11))
            if kind == "ok": d.line([(z*.28, z*.52), (z*.44, z*.68), (z*.73, z*.36)], fill="#121212", width=w, joint="curve")
            elif kind == "bad":
                d.line([(z*.32, z*.32), (z*.68, z*.68)], fill="#121212", width=w); d.line([(z*.68, z*.32), (z*.32, z*.68)], fill="#121212", width=w)
            else:
                d.line([(z*.5, z*.24), (z*.5, z*.58)], fill="#121212", width=w); d.ellipse([z*.44, z*.68, z*.56, z*.80], fill="#121212")
        cv.create_image(cx * S, cy * S, image=pil(size, size, paint), anchor="center", tags=tag or ())
    def text(x, y, s, sz, c=None, b=False, anchor="w", tag=None):
        cv.create_text(x * S, y * S, text=s, font=F(sz, b), fill=c or C["tx"], anchor=anchor, tags=tag or ())
    actions = {}
    def button(x0, y0, x1, y1, label, primary, fn, tag):
        rr(x0, y0, x1, y1, (y1 - y0) / 2, C["acc"] if primary else C["card"], None if primary else C["mu"], tag)
        text((x0 + x1) / 2, (y0 + y1) / 2, label, 12, "#121212" if primary else C["tx"], True, "center", tag)
        actions[tag] = fn
        cv.tag_bind(tag, "<Button-1>", lambda e, t=tag: win.after_idle(actions[t]))
        if not getattr(cv, "_ptr", False):
            cv._ptr = True
            def ptr(e):
                tags = set()
                for it in cv.find_overlapping(e.x, e.y, e.x, e.y): tags.update(cv.gettags(it))
                c_ = "hand2" if any(t in actions for t in tags) else ""
                if cv.cget("cursor") != c_: cv.config(cursor=c_)
            cv.bind("<Motion>", ptr, add="+"); cv.bind("<Leave>", lambda e: cv.cget("cursor") and cv.config(cursor=""), add="+")
    def close():
        try: win.destroy()
        except tk.TclError: pass
    # Animated avatar: bundled face sprite (assets/gtg_face.jpg + .json), soft round mask, thin green ring, check badge.
    try: meta = json.load(open(os.path.join(ASSETS, "assets", "gtg_face.json")))
    except Exception: meta = {}
    R = 62                                        # avatar radius
    faces = []
    def load_faces():
        from PIL import ImageFilter, ImageChops
        D = int(2 * R * S)
        m = Image.new("L", (D * 4, D * 4), 0); ImageDraw.Draw(m).ellipse([0, 0, D * 4 - 1, D * 4 - 1], fill=255)
        m = m.resize((D, D), Image.LANCZOS)
        fade = Image.new("L", (D, D), 0); e = max(2, int(5 * S)); ImageDraw.Draw(fade).ellipse([e, e, D - e, D - e], fill=255)
        mask = ImageChops.multiply(m, fade.filter(ImageFilter.GaussianBlur(4.5 * S)))
        frames = []
        try:                                       # one sprite sheet (assets/gtg_face.jpg), cut into frames here
            sheet = Image.open(os.path.join(ASSETS, "assets", "gtg_face.jpg")).convert("RGB"); z, cols, n = meta["size"], meta["cols"], meta["count"]
        except Exception as ex: log("Face sprite: %r" % ex); return frames
        for i in range(n):
            f = sheet.crop(((i % cols) * z, (i // cols) * z, (i % cols + 1) * z, (i // cols + 1) * z)).resize((D, D), Image.LANCZOS)
            im = Image.new("RGB", (D, D), C["bg"]); im.paste(f, (0, 0), mask)
            frames.append(ImageTk.PhotoImage(im, master=win))
        return frames                              # played straight through, then loops
    anim = {"i": 0}
    durs = meta.get("durations_ms") or []
    def animate():                                 # original per-frame timing of the source GIF
        if not win.winfo_exists(): return
        it = cv.find_withtag("avatar")
        if it and faces:
            anim["i"] = (anim["i"] + 1) % len(faces); cv.itemconfig(it[0], image=faces[anim["i"]])
        win.after(int(durs[anim["i"]]) if anim["i"] < len(durs) else 70, animate)
    def draw():
        cv.delete("all"); imgs.clear(); actions.clear()
        ok = status["ok"]
        if ok:
            CY = 22 + R
            if faces: cv.create_image(W / 2 * S, CY * S, image=faces[anim["i"] % len(faces)], anchor="center", tags="avatar")
            else: mark(W / 2, CY, 2 * R, "ok")
            rg = R + 3
            cv.create_image(W / 2 * S, CY * S, anchor="center", image=pil(2 * rg + 2, 2 * rg + 2,
                lambda d, k: d.ellipse([k, k, (2 * rg + 1) * k, (2 * rg + 1) * k], outline=C["acc"], width=int(1.5 * k))))
            bx, by = W / 2 + R * 0.72, CY + R * 0.72
            cv.create_image(bx * S, by * S, anchor="center", image=pil(34, 34, lambda d, k: d.ellipse([0, 0, 34 * k - 1, 34 * k - 1], fill=C["bg"])))
            mark(bx, by, 28, "ok")
            y = CY + R + 30
        else:
            mark(W / 2, 54, 64, "bad"); y = 112
        text(W / 2, y, "You're good to go" if ok else "Spotify login didn't finish", 19, b=True, anchor="center")
        y += 28
        if ok:
            app_ok = status.get("spotify_app", True)
            sub = ("Connected as %s" % status["name"]) if status.get("name") else "Connected"
            rows = [("ok" if app_ok else "warn", "Spotify", sub if app_ok else "Spotify app not installed", None)]
            st = status.get("steam")
            if st: rows.append(("ok", "Age of Empires IV", "Starts with the game", None))
            elif st is False: rows.append(("warn", "Age of Empires IV", "Launch option missing", "fix"))
            else: rows.append(("warn", "Age of Empires IV", "Steam not found", None))
            rows.append(("warn", "Skill", "Issue detected", None))     # the joke row (always)
            for kind, lab, detail, act in rows:
                rr(20, y, W - 20, y + 40, 10, C["card"])
                mark(42, y + 20, 18, kind); text(60, y + 20, lab, 12, b=True)
                if act == "fix":
                    text(W - 92, y + 20, detail, 11, C["mu"], anchor="e")
                    button(W - 84, y + 8, W - 30, y + 32, "Fix", True, do_fix, "b_fix")
                else: text(W - 32, y + 20, detail, 11, C["mu"], anchor="e")
                y += 48
            y += 6
            button(20, y, W / 2 - 6, y + 40, "Open panel", False, open_panel, "b_panel")
            button(W / 2 + 6, y, W - 20, y + 40, "Done", True, close, "b_done")
        else:
            text(W / 2, y + 4, "Log in to Spotify and click Agree.", 12, C["mu"], anchor="center"); y += 30
            button(20, y, W / 2 - 6, y + 40, "Close", False, close, "b_done")
            button(W / 2 + 6, y, W - 20, y + 40, "Try again", True, retry, "b_retry")
        cv.config(height=int((y + 60) * S))
    def do_fix():
        if not fix: return
        text(W / 2, 20, "Steam closes and reopens...", 10, C["mu"], anchor="center")
        done = []
        def go():
            try: fix()
            except Exception as e: log("Fix launch option failed: %r" % e)
            try: done.append(launch_option_is_set())
            except Exception: done.append(None)
        def poll():                               # Tk must only be touched from this thread
            if done: status.update(steam=done[0]); draw()
            else: win.after(200, poll)
        threading.Thread(target=go, daemon=True).start(); poll()
    def open_panel():
        (on_open_panel or _g_app().open_panel_process)(); close()
    def retry():
        close()
        if on_retry: on_retry()
    set_app_icon(win)
    faces.extend(load_faces())
    draw(); animate()
    win._gtg = {"cv": cv, "status": status, "actions": actions, "draw": draw}   # for tests
    reveal(win, over=parent); note_window("gtg", win); win.lift(); win.attributes("-topmost", True); win.after(300, lambda: win.attributes("-topmost", False))
    if parent is None: win.mainloop()
    return win
def app_badge(px):
    """The app icon (green circle, "IV") as a PIL image: largest frame of the bundled app.ico, else drawn like make_icon.py."""
    from PIL import Image, ImageDraw
    try:
        ico = Image.open(os.path.join(ASSETS, "assets", "app.ico")); ico.size = max(ico.info.get("sizes") or [ico.size])
        return ico.convert("RGBA").resize((px, px), Image.LANCZOS)
    except Exception: pass
    ss = 8; N = px * ss; k = N / 1024; ox, oy, w = 0.409, -0.5, 92
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([16 * k, 16 * k, N - 16 * k, N - 16 * k], fill="#1DB954")
    for pts in ([(310, 320), (310, 704)], [(490, 320), (620, 704), (750, 320)]):
        P = [((x + ox) * k, (y + oy) * k) for x, y in pts]; r = w * k / 2
        for a, b in zip(P, P[1:]): d.line([a, b], fill="#191414", width=int(w * k))
        for x, y in P: d.ellipse([x - r, y - r, x + r, y + r], fill="#191414")
    return im.resize((px, px), Image.LANCZOS)
def set_app_icon(win):
    """Title-bar icon = app.ico (bundled), so it matches the exe and shortcuts."""
    ico = os.path.join(ASSETS, "assets", "app.ico")
    try:
        if os.path.exists(ico): win.iconbitmap(ico); win.iconbitmap(default=ico); return
    except Exception as e: log("Icon: %r" % e)
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk
class GlassTip:
    """Dark glass tooltip card with an arrow, in its own layered top-level window (never clipped, per-pixel alpha
    for smooth corners + soft shadow on Windows). Anchored to an element's screen rectangle, flips above/below so it
    never covers it, clamped to that monitor's work area. 350 ms delay, instant switch between neighbours,
    120 ms fade + 2 px slide in, 80 ms fade out. One per Tk root: get_tip(widget)."""
    DELAY, WARM, FIN, FOUT, MAXW, PAD, SH = 350, 400, 120, 80, 260, 10, 12
    def __init__(self, root):
        import tkinter as tk
        self.root = root; self.w = tk.Toplevel(root, bg="#010203"); self.w.withdraw(); self.w.overrideredirect(True)
        self.key = None; self.want = None; self.job = None; self.anim = None; self.shown = False; self.t_hide = 0.0
        self.hwnd = None; self.layered = False; self.img = None; self.pos = (0, 0); self.label = None
        self.wd = None; self.cursor = None; self.foreground = None     # (tests may override cursor / foreground)
        try: self._init_layered()
        except Exception as ex: log("Tooltip: layered window unavailable (%r)" % ex)
        if not self.layered:
            self.label = tk.Label(self.w, bd=0, highlightthickness=0, bg="#010203"); self.label.pack()
            try: self.w.attributes("-transparentcolor", "#010203")
            except Exception: pass
        b = root.bind_all
        for ev in ("<ButtonPress>", "<MouseWheel>", "<KeyPress>"): b(ev, lambda e: self.hide(), add="+")
    # -- Windows layered window
    def _init_layered(self):
        import ctypes
        if os.name != "nt": return
        self.w.update_idletasks(); self._ensure_layered(); self.layered = True
    def _ensure_layered(self):
        """(Re)apply the layered style to the CURRENT wrapper window. Tk recreates the wrapper HWND on some wm
        changes (e.g. `wm transient` to a new owner): the new one is a plain window that shows as an empty
        light-grey box and ignores UpdateLayeredWindow. Called before every show."""
        import ctypes
        u = ctypes.windll.user32; self.w.update_idletasks()
        h = u.GetParent(self.w.winfo_id()) or self.w.winfo_id()
        GWL_EXSTYLE = -20; ex = u.GetWindowLongW(h, GWL_EXSTYLE); want = 0x80000 | 0x20 | 0x08000000 | 0x80   # LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW
        if ex & want != want: u.SetWindowLongW(h, GWL_EXSTYLE, ex | want)
        self.hwnd = h
    def _push(self, alpha):
        """Blit self.img (RGBA) at self.pos with overall alpha 0..1."""
        x, y = self.pos
        if not self.layered:
            self.w.geometry("+%d+%d" % (x, y))
            try: self.w.attributes("-alpha", max(0.0, min(1.0, alpha)))
            except Exception: pass
            return
        import ctypes
        from ctypes import wintypes as wt
        im = self.img; wd, ht = im.size
        r, g, b, a = im.split()
        from PIL import ImageChops
        pm = Image.merge("RGBA", (ImageChops.multiply(b, a), ImageChops.multiply(g, a), ImageChops.multiply(r, a), a))   # premultiplied BGRA
        data = pm.tobytes()
        u, g32 = ctypes.windll.user32, ctypes.windll.gdi32
        class BIH(ctypes.Structure):
            _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                        ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD), ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                        ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]
        class BLEND(ctypes.Structure):
            _fields_ = [("op", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("alpha", ctypes.c_ubyte), ("fmt", ctypes.c_ubyte)]
        bih = BIH(ctypes.sizeof(BIH), wd, -ht, 1, 32, 0, 0, 0, 0, 0, 0)
        sdc = u.GetDC(0); mdc = g32.CreateCompatibleDC(sdc); bits = ctypes.c_void_p()
        g32.CreateDIBSection.restype = ctypes.c_void_p
        hb = g32.CreateDIBSection(mdc, ctypes.byref(bih), 0, ctypes.byref(bits), None, 0)
        try:
            ctypes.memmove(bits, data, len(data)); old = g32.SelectObject(mdc, ctypes.c_void_p(hb))
            pt = wt.POINT(x, y); sz = wt.SIZE(wd, ht); src = wt.POINT(0, 0)
            bl = BLEND(0, 0, int(255 * max(0.0, min(1.0, alpha))), 1)
            u.UpdateLayeredWindow(wt.HWND(self.hwnd), sdc, ctypes.byref(pt), ctypes.byref(sz), mdc, ctypes.byref(src), 0, ctypes.byref(bl), 2)
            g32.SelectObject(mdc, old)
        finally:
            g32.DeleteObject(ctypes.c_void_p(hb)); g32.DeleteDC(mdc); u.ReleaseDC(0, sdc)
    # -- rendering
    @staticmethod
    def _font(px, bold):
        for f in (("seguisb.ttf" if bold else "segoeui.ttf"), "segoeui.ttf", "arial.ttf"):
            try: return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\\Windows"), "Fonts", f), px)
            except Exception:
                try: return ImageFont.truetype(f, px)
                except Exception: pass
        return ImageFont.load_default()
    def _lines(self, text, fnt, maxw):
        """Wrap to max 2 lines; ellipsize the rest."""
        words = str(text).split(); lines = []; cur = ""
        for w_ in words:
            t_ = (cur + " " + w_).strip()
            if fnt.getlength(t_) <= maxw or not cur: cur = t_
            else: lines.append(cur); cur = w_
        if cur: lines.append(cur)
        if len(lines) > 2: lines = [lines[0], " ".join(lines[1:])]
        out = []
        for ln in lines:
            if fnt.getlength(ln) > maxw:
                while ln and fnt.getlength(ln + "\\u2026") > maxw: ln = ln[:-1]
                ln = ln.rstrip() + "\\u2026"
            out.append(ln)
        return out or [""]
    def _render(self, text, scale, arrow_up, ax):
        Q = 3; s = scale; pad, sh = int(self.PAD * s), int(self.SH * s)
        fnt = self._font(int(12 * s * Q), True)
        lines = self._lines(text, self._font(int(12 * s), True), self.MAXW * s)
        lh = int(17 * s); tw = max(int(self._font(int(12 * s), True).getlength(l)) for l in lines)
        cw, chh = tw + 2 * pad + int(4 * s), lh * len(lines) + int(14 * s); ah = int(6 * s)
        W_, H_ = cw + 2 * sh, chh + ah + 2 * sh
        cy0 = sh + (ah if arrow_up else 0)
        ax = max(sh + int(14 * s), min(W_ - sh - int(14 * s), ax))
        def shape(d, k, fill):
            d.rounded_rectangle([sh * k, cy0 * k, (sh + cw) * k, (cy0 + chh) * k], int(8 * s * k), fill=fill)
            if arrow_up: d.polygon([((ax - ah) * k, (cy0 + 1) * k), ((ax + ah) * k, (cy0 + 1) * k), (ax * k, (cy0 - ah) * k)], fill=fill)
            else: d.polygon([((ax - ah) * k, (cy0 + chh - 1) * k), ((ax + ah) * k, (cy0 + chh - 1) * k), (ax * k, (cy0 + chh + ah) * k)], fill=fill)
        shd = Image.new("L", (W_, H_), 0); shape(ImageDraw.Draw(shd), 1, 120)
        shd = shd.filter(ImageFilter.GaussianBlur(5 * s)); shd = ImageChops_offset(shd, 0, int(3 * s))
        im = Image.new("RGBA", (W_ * Q, H_ * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        shape(d, Q, (255, 255, 255, 30))                                  # hairline edge
        inner = Image.new("RGBA", im.size, (0, 0, 0, 0)); di = ImageDraw.Draw(inner)
        di.rounded_rectangle([(sh * Q) + Q, cy0 * Q + Q, (sh + cw) * Q - Q, (cy0 + chh) * Q - Q], int(8 * s * Q) - Q, fill=(36, 36, 38, 246))
        if arrow_up: di.polygon([((ax - ah) * Q + Q, (cy0 + 1) * Q + Q), ((ax + ah) * Q - Q, (cy0 + 1) * Q + Q), (ax * Q, (cy0 - ah) * Q + 2 * Q)], fill=(36, 36, 38, 246))
        else: di.polygon([((ax - ah) * Q + Q, (cy0 + chh - 1) * Q - Q), ((ax + ah) * Q - Q, (cy0 + chh - 1) * Q - Q), (ax * Q, (cy0 + chh + ah) * Q - 2 * Q)], fill=(36, 36, 38, 246))
        im.alpha_composite(inner)
        for i, ln in enumerate(lines):
            d.text(((sh + cw / 2) * Q, (cy0 + int(7 * s) + lh * i + lh / 2) * Q), ln, font=fnt, fill=(242, 242, 242, 255), anchor="mm")
        im = im.resize((W_, H_), Image.LANCZOS)
        base = Image.new("RGBA", (W_, H_), (0, 0, 0, 0)); base.putalpha(shd); base.alpha_composite(im)
        if not self.layered:                                              # fallback: no translucency, key colour background
            flat = Image.new("RGB", (W_, H_), (1, 2, 3)); m = im.split()[3].point(lambda v: 255 if v > 90 else 0)
            flat.paste(im.convert("RGB"), (0, 0), m); base = flat
        return base, sh, cy0, chh, ah
    # -- monitor work area for a point (multi-monitor aware)
    def _work(self, x, y):
        try:
            import ctypes
            from ctypes import wintypes as wt
            class MI(ctypes.Structure): _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
            u = ctypes.windll.user32; u.MonitorFromPoint.restype = ctypes.c_void_p
            hm = u.MonitorFromPoint(wt.POINT(int(x), int(y)), 2); mi = MI(); mi.cbSize = ctypes.sizeof(MI)
            if u.GetMonitorInfoW(ctypes.c_void_p(hm), ctypes.byref(mi)):
                r = mi.rcWork; return r.left, r.top, r.right, r.bottom
        except Exception: pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
    # -- public
    # -- watchdog: the tooltip may only exist while the pointer is on its anchor in our foreground window
    def _ptr(self):
        if self.cursor: return self.cursor()
        try:
            import ctypes
            from ctypes import wintypes as wt
            pt = wt.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)); return pt.x, pt.y
        except Exception: return self.root.winfo_pointerxy()
    def _ours_fg(self):
        if self.foreground: return self.foreground()
        try:
            import ctypes
            from ctypes import wintypes as wt
            u = ctypes.windll.user32
            u.GetForegroundWindow.restype = wt.HWND
            u.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
            fg = u.GetForegroundWindow()
            if not fg: return False
            pid = wt.DWORD(); u.GetWindowThreadProcessId(fg, ctypes.byref(pid)); return pid.value == os.getpid()
        except Exception as ex:
            log("Tooltip: foreground check failed (%r)" % ex); return False          # unsure -> hide
    def ok(self):
        """Still valid to show: anchor alive + mapped, owner not minimised, our window in front, pointer on the anchor."""
        if not self.want: return False
        _, _, (x0, y0, x1, y1), _, w = self.want
        try:
            if w is not None:
                if not w.winfo_exists() or not w.winfo_viewable(): return False
                if w.winfo_toplevel().state() in ("iconic", "withdrawn"): return False
            if not self._ours_fg(): return False
            px, py = self._ptr()
            return x0 - 2 <= px <= x1 + 2 and y0 - 2 <= py <= y1 + 2
        except Exception: return False
    def _visible(self):
        try: return bool(self.w.winfo_viewable())
        except Exception: return False
    def _watch(self):
        self.wd = None
        if not (self.shown or self.job or self._visible()): return
        if (self.shown or self.job) and not self.ok(): self.hide()
        elif not (self.shown or self.job or self.anim): self._gone()          # visible but nothing owns it: remove
        self.wd = self.root.after(100, self._watch)
    def _gone(self):
        """Withdraw for sure (no fade), cancel timers."""
        for j in ("job", "anim"):
            if getattr(self, j):
                try: self.root.after_cancel(getattr(self, j))
                except Exception: pass
                setattr(self, j, None)
        self.shown = False
        try: self.w.withdraw()
        except Exception: pass
    def request(self, key, text, rect, scale=1.0, widget=None):
        """Ask for a tooltip for `key` anchored to screen rect (x0, y0, x1, y1) of `widget`."""
        if not text: self.hide(); return
        if key == self.key and (self.shown or self.job): self.want = (key, text, rect, scale, widget); return
        fading = bool(self.anim) and not self.shown
        self._cancel(); self.key = key; self.want = (key, text, rect, scale, widget)
        if fading and self._visible(): self._gone()           # a cancelled fade-out must not leave the card behind
        if not self.ok(): self.want = None; self.key = None; self._gone(); return
        if not self.wd: self.wd = self.root.after(100, self._watch)
        warm = self.shown or (time.time() - self.t_hide) * 1000 < self.WARM
        if warm: self._show(slide=False)
        else: self.job = self.root.after(self.DELAY, lambda: self._show(slide=True))
    def _cancel(self):
        for j in ("job", "anim"):
            if getattr(self, j):
                try: self.root.after_cancel(getattr(self, j))
                except Exception: pass
                setattr(self, j, None)
    def _show(self, slide=True):
        self.job = None
        if not self.want: return
        if not self.ok(): self.want = None; self.key = None; self._gone(); return   # re-check hover right before showing
        key, text, (x0, y0, x1, y1), s, _w = self.want
        try:
            if not self.w.winfo_exists(): return
            wx0, wy0, wx1, wy1 = self._work((x0 + x1) / 2, (y0 + y1) / 2)
            gap = int(6 * s)
            probe, sh, cy0, chh, ah = self._render(text, s, True, 0)
            W_, H_ = probe.size
            below = y1 + gap + H_ - sh <= wy1                        # flip above when there is no room below
            cx = (x0 + x1) / 2
            left = int(min(max(wx0 + 4 - sh, cx - W_ / 2), wx1 - 4 + sh - W_))
            img, sh, cy0, chh, ah = self._render(text, s, below, cx - left)
            top = int(y1 + gap - sh) if below else int(y0 - gap - (H_ - sh))
            top = max(wy0 - sh, min(top, wy1 + sh - H_))
            self.img = img; self.final = (left, top); dy = int(2 * s) * (1 if below else -1)
            try:                                                    # owned by the anchor's window (not globally topmost); set while hidden
                own = _w.winfo_toplevel() if _w is not None else self.root
                if str(self.w.transient() or "") != str(own): self.w.transient(own)
            except Exception: pass
            if self.layered:
                self.w.geometry("%dx%d+%d+%d" % (W_, H_, left, top)); self._ensure_layered()
                self.pos = (left, top + (dy if slide else 0)); self._push(0.0 if slide else 1.0)   # content first, then map: never an empty box
            else: self._tkimg = ImageTk.PhotoImage(img); self.label.config(image=self._tkimg); self.w.attributes("-alpha", 0.0)
            self.w.deiconify(); self.shown = True
            try: self.w.lift()
            except Exception: pass
            if not slide: self.pos = (left, top); self._push(1.0); return
            t0 = time.time()
            def step():
                k = min(1.0, (time.time() - t0) * 1000 / self.FIN); e = 1 - (1 - k) ** 3
                self.pos = (left, int(top + dy * (1 - e))); self._push(e)
                self.anim = self.root.after(15, step) if k < 1 else None
            step()
        except Exception as ex: log("Tooltip: %r" % ex)
    def hide(self, _=None, fade=True):
        self._cancel(); self.key = None; self.want = None
        if self.wd:
            try: self.root.after_cancel(self.wd)
            except Exception: pass
            self.wd = None
        if not self.shown:
            if self._visible(): self._gone()
            return
        self.shown = False; self.t_hide = time.time()
        try:
            if not fade or not self.img: self._gone(); return
            t0 = time.time()
            def step():
                self.anim = None
                if self.shown: return                             # re-shown meanwhile
                try:
                    k = min(1.0, (time.time() - t0) * 1000 / self.FOUT)
                    if k >= 1: self._gone(); return
                    self._push(1 - k); self.anim = self.root.after(15, step)
                except Exception: self._gone()
            step()
        except Exception: self._gone()
def ImageChops_offset(im, dx, dy):
    out = Image.new(im.mode, im.size, 0); out.paste(im, (dx, dy)); return out
def get_tip(widget):
    """The shared tooltip for this widget's Tk root (created on first use). Also hides on minimise/move/focus loss."""
    root = widget._root()
    t = getattr(root, "_glass_tip", None)
    if t is None:
        t = GlassTip(root); root._glass_tip = t
    tl = widget.winfo_toplevel()
    if not getattr(tl, "_tip_hooks", False):
        tl._tip_hooks = True; last = {"geo": None}
        def cfg(e):
            if e.widget is tl:
                g = (tl.winfo_rootx(), tl.winfo_rooty())
                if last["geo"] and g != last["geo"]: t.hide(fade=False)
                last["geo"] = g
        tl.bind("<Configure>", cfg, add="+"); tl.bind("<Unmap>", lambda e: t.hide(fade=False), add="+")
        tl.bind("<FocusOut>", lambda e: tl.after(60, lambda: (tl.focus_displayof() is None) and t.hide()), add="+")
        tl.bind("<Destroy>", lambda e: e.widget is tl and t.hide(fade=False), add="+")
    return t
def canvas_rect(cv, bbox):
    """Canvas bbox (px) -> screen rect."""
    x0, y0, x1, y1 = bbox; rx, ry = cv.winfo_rootx(), cv.winfo_rooty()
    return (rx + x0, ry + y0, rx + x1, ry + y1)
def after_mouse_up(w, cb, min_ms=150):
    """Call cb once the left mouse button is released (anywhere, even outside the app) and min_ms passed."""
    t0 = time.time()
    def down():
        try:
            import ctypes
            return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
        except Exception: return False
    def poll():
        try:
            if down() or (time.time() - t0) * 1000 < min_ms: w.after(30, poll)
            else: cb()
        except Exception: pass                       # window closed meanwhile
    poll()
class _Pen:
    """Icon drawing in a 22-unit space around the centre (supersampled by the caller)."""
    def __init__(s_, d, m): s_.d = d; s_.k = m / 22.0; s_.c = m / 2.0
    def p(s_, x, y): return (s_.c + x * s_.k, s_.c + y * s_.k)
    def rr(s_, x0, y0, x1, y1, r, fill=None, outline=None, w=1.6):
        s_.d.rounded_rectangle([*s_.p(x0, y0), *s_.p(x1, y1)], radius=r * s_.k, fill=fill, outline=outline, width=max(1, int(w * s_.k)) if outline else 0)
    def circ(s_, x, y, r, fill=None, outline=None, w=1.6):
        s_.d.ellipse([*s_.p(x - r, y - r), *s_.p(x + r, y + r)], fill=fill, outline=outline, width=max(1, int(w * s_.k)) if outline else 0)
    def poly(s_, pts, fill): s_.d.polygon([s_.p(x, y) for x, y in pts], fill=fill)
    def line(s_, pts, col, w):
        P_ = [s_.p(x, y) for x, y in pts]; s_.d.line(P_, fill=col, width=max(1, int(w * s_.k)), joint="curve"); r = w * s_.k / 2
        for x, y in P_: s_.d.ellipse([x - r, y - r, x + r, y + r], fill=col)
def _pen_icon(name, col, bg):
    def paint(v):
        if name == "link":
            v.rr(-9, -4, 1, 4, 4, outline=col, w=1.8); v.rr(-1, -4, 9, 4, 4, outline=col, w=1.8)
        elif name == "plus": v.line([(-5, 0), (5, 0)], col, 2); v.line([(0, -5), (0, 5)], col, 2)
        elif name == "drop":                                   # arrow down into a tray
            v.line([(0, -8), (0, 2)], col, 1.9); v.line([(-4, -2), (0, 2), (4, -2)], col, 1.9)
            v.line([(-8, 2), (-8, 7), (8, 7), (8, 2)], col, 1.9)
        elif name == "search": v.circ(-2, -2, 5.2, outline=col, w=1.9); v.line([(2, 2), (6.5, 6.5)], col, 2.1)
        elif name == "playing":
            for i, h in enumerate((7, 11, 5)): v.rr(-6.5 + i * 4.6, 5.5 - h, -4.1 + i * 4.6, 5.5, 1.1, fill=col)
        elif name == "paste": v.rr(-6, -6, 6, 8, 2, outline=col, w=1.7); v.rr(-3, -8.5, 3, -4.5, 1.5, fill=col)
        elif name == "handle":
            for yy in (-4, 0, 4):
                for xx in (-2.2, 2.2): v.circ(xx, yy, 1.3, fill=col)
        elif name == "x": v.line([(-3.6, -3.6), (3.6, 3.6)], col, 1.7); v.line([(3.6, -3.6), (-3.6, 3.6)], col, 1.7)
        elif name == "back": v.line([(5, 0), (-5, 0)], col, 2); v.line([(-1, -4.5), (-5.5, 0), (-1, 4.5)], col, 2)
        elif name == "note":
            v.circ(-3, 5, 3, fill=col); v.line([(0, 5), (0, -6), (5, -7.5)], col, 1.9)
    return paint
def _dashed_rr(dr, w, h, r, col, lw, dash, gap):
    import math
    pts = []
    def arc(cx, cy, a0, a1):
        for i in range(13):
            a = math.radians(a0 + (a1 - a0) * i / 12.0); pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    x0, y0, x1, y1 = lw, lw, w - lw, h - lw
    arc(x0 + r, y0 + r, 180, 270); arc(x1 - r, y0 + r, 270, 360); arc(x1 - r, y1 - r, 0, 90); arc(x0 + r, y1 - r, 90, 180); pts.append(pts[0])
    on, left = True, dash
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        L = math.hypot(bx - ax, by - ay); t = 0.0
        while L - t > 1e-6:
            stp = min(left, L - t)
            if on: dr.line([(ax + (bx - ax) * t / L, ay + (by - ay) * t / L), (ax + (bx - ax) * (t + stp) / L, ay + (by - ay) * (t + stp) / L)], fill=col, width=max(1, int(lw)))
            t += stp; left -= stp
            if left <= 1e-6: on = not on; left = dash if on else gap
def mosaic_image(tracks, px):
    """2x2 mosaic of the first songs' cached album art (1 song: full art), PIL RGB."""
    from PIL import Image
    im = Image.new("RGB", (px, px), "#2a2a2a")
    tr = [t for t in tracks if os.path.exists(track_cover(t))]
    if len(tr) == 1:
        try: return Image.open(track_cover(tr[0])).convert("RGB").resize((px, px), Image.LANCZOS)
        except Exception: return im
    h = px // 2
    for i, t in enumerate((tr * 4)[:4] if tr else []):
        try: im.paste(Image.open(track_cover(t)).convert("RGB").resize((h, h), Image.LANCZOS), ((i % 2) * h, (i // 2) * h))
        except Exception: pass
    return im
def save_mosaic(uri, tracks, px=96):
    try:
        os.makedirs(COVERS, exist_ok=True); mosaic_image(tracks, px).save(custom_cover(uri)); return custom_cover(uri)
    except Exception as e: log("Mosaic cover: %r" % e); return None
def install_edit_menu(w):
    """Right-click Cut / Copy / Paste / Select all for every Entry and Text in this Tk app."""
    import tkinter as tk
    m = tk.Menu(w, tearoff=0, bg="#2a2a2a", fg="#f2f2f2", activebackground="#1DB954", activeforeground="#121212",
                bd=0, relief="flat", font=("Segoe UI", 10))
    tgt = {}
    def do(ev):
        x = tgt.get("w")
        if x is not None:
            try: x.focus_set(); x.event_generate(ev)
            except tk.TclError: pass
    def sel_all():
        x = tgt.get("w")
        if x is None: return
        try: x.focus_set(); x.select_range(0, "end"); x.icursor("end")
        except Exception:
            try: x.tag_add("sel", "1.0", "end")
            except Exception: pass
    m.add_command(label="Cut", command=lambda: do("<<Cut>>")); m.add_command(label="Copy", command=lambda: do("<<Copy>>"))
    m.add_command(label="Paste", command=lambda: do("<<Paste>>")); m.add_separator(); m.add_command(label="Select all", command=sel_all)
    def show(e):
        tgt["w"] = e.widget
        try: m.tk_popup(e.x_root, e.y_root)
        finally:
            try: m.grab_release()
            except tk.TclError: pass
    for cls in ("Entry", "Text"): w.bind_class(cls, "<Button-3>", show, add="+")
def list_picker(parent, title, current="", allow_tracks=False, user=None, save=None, start_builder=False):
    """Modal picker. Returns a Spotify playlist uri, a track uri (allow_tracks), or a custom list uri; None = cancelled.
    'Paste link' takes a pasted or dropped link; 'Make your own' opens the builder (app-only list, saved in settings)."""
    import tkinter as tk, tkinter.font as tkfont, threading
    from PIL import Image, ImageDraw, ImageTk
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", line="#2a2a2a", fld="#181818",
             ib="#2a2a2a", red="#e5675f", dim="#6c6c6c")
    user = user if user is not None else load_user_settings()
    d = tk.Toplevel(parent); dark_window(d, C["bg"]); d.title("AoE4 Spotify"); d.resizable(False, False)
    try: d.transient(parent)
    except Exception: pass
    S = d.winfo_fpixels("1i") / 96.0; W = 420
    cv = tk.Canvas(d, width=int(W * S), height=int(320 * S), bg=C["bg"], highlightthickness=0); cv.pack()
    def P(*v): return [x * S for x in v]
    def F(sz, b=False): return ("Segoe UI", -int(sz * S), "bold" if b else "normal")
    imgs = {}; res = {}; handlers = {}; q = []
    if not isinstance(user.get("custom_lists"), dict): user["custom_lists"] = {}
    lists = user["custom_lists"]
    st = {"page": "pick", "drag": False, "err": "", "tracks": [], "id": None, "sc": 0, "move": None, "search": False,
          "results": [], "busy": "", "H": 320, "t0": time.time()}
    def _img(key, w, h, paint):
        k = (key, w, h)
        if k not in imgs:
            Q = 4; im = Image.new("RGBA", (max(1, w) * Q, max(1, h) * Q), (0, 0, 0, 0)); paint(ImageDraw.Draw(im), Q, im)
            imgs[k] = ImageTk.PhotoImage(im.resize((max(1, w), max(1, h)), Image.LANCZOS))
        return imgs[k]
    def rr(x0, y0, x1, y1, r, fill, outline=None, width=1.0, tag=None, dash=False):
        X0, Y0, X1, Y1 = [int(round(v)) for v in P(x0, y0, x1, y1)]; w, h = X1 - X0, Y1 - Y0
        def paint(dr, Q, im):
            if fill: dr.rounded_rectangle([0, 0, w * Q - 1, h * Q - 1], radius=r * S * Q, fill=fill)
            if outline and dash: _dashed_rr(dr, w * Q, h * Q, r * S * Q, outline, width * S * Q, 5 * S * Q, 4 * S * Q)
            elif outline: dr.rounded_rectangle([0, 0, w * Q - 1, h * Q - 1], radius=r * S * Q, outline=outline, width=max(1, int(width * S * Q)))
        return cv.create_image(X0, Y0, image=_img(("rr", r, fill, outline, width, dash), w, h, paint), anchor="nw", tags=tag)
    def circ(x, y, r, fill, tag=None):
        n = int(round(2 * r * S))
        def paint(dr, Q, im): dr.ellipse([0, 0, n * Q - 1, n * Q - 1], fill=fill)
        return cv.create_image(*P(x, y), image=_img(("c", fill), n, n, paint), anchor="center", tags=tag)
    def icon(name, x, y, col, bg=None, sz=22, tag=None):
        px = int(sz * S); px += px % 2
        def paint(dr, Q, im): _pen_icon(name, col, bg)(_Pen(dr, px * Q))
        return cv.create_image(*P(x, y), image=_img(("i", name, col, bg), px, px, paint), anchor="center", tags=tag)
    def text(x, y, s_, sz, c=None, b=False, anchor="w", tag=None):
        return cv.create_text(*P(x, y), text=s_, font=F(sz, b), fill=c or C["tx"], anchor=anchor, tags=tag)
    def thumb(path, size, key=None):
        k = ("th", key or path, size, os.path.getmtime(path) if path and os.path.exists(path) else 0)
        if k not in imgs:
            px = int(round(size * S)); Q = 4
            try:
                im = (key if isinstance(key, Image.Image) else Image.open(path)).convert("RGB").resize((px, px), Image.LANCZOS)
            except Exception: im = Image.new("RGB", (px, px), "#2a2a2a")
            m = Image.new("L", (px * Q, px * Q), 0)
            ImageDraw.Draw(m).rounded_rectangle([0, 0, px * Q - 1, px * Q - 1], (6 if size >= 40 else 5) * S * Q, fill=255)
            im.putalpha(m.resize((px, px), Image.LANCZOS)); imgs[k] = ImageTk.PhotoImage(im)
        return imgs[k]
    def mosaic(tracks, size, r=7):
        key = ("mos", size, r) + tuple(tracks[:4]) + tuple(os.path.exists(track_cover(t)) for t in tracks[:4])
        if key not in imgs:
            px = int(round(size * S)); Q = 4; im = mosaic_image(tracks, px * 2).convert("RGBA").resize((px, px), Image.LANCZOS)
            m = Image.new("L", (px * Q, px * Q), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, px * Q - 1, px * Q - 1], r * S * Q, fill=255)
            im.putalpha(m.resize((px, px), Image.LANCZOS)); imgs[key] = ImageTk.PhotoImage(im)
        return imgs[key]
    def click(tag, fn): handlers[tag] = fn
    def on_click(e):
        if st["move"] is not None: return
        if not st.pop("pdown", False) or not st.get("armed"): return   # press started elsewhere (click-through)
        if st["page"] == "build" and b_release(e): return
        for it in reversed(cv.find_overlapping(e.x, e.y, e.x, e.y)):
            for t in cv.gettags(it):
                if t in handlers: d.after_idle(handlers[t]); return
    cv.bind("<ButtonRelease-1>", lambda e: (end_move(e) if st["move"] is not None else on_click(e)))
    def on_motion(e):
        if st["page"] == "build": b_motion(e); return
        hit = any(t in handlers or t.startswith("mv") for it in cv.find_overlapping(e.x, e.y, e.x, e.y) for t in cv.gettags(it))
        cv.config(cursor="hand2" if hit else "")
        mk = st["page"] == "pick" and any("mk" in cv.gettags(it) for it in cv.find_overlapping(e.x, e.y, e.x, e.y))
        if mk != bool(st.get("mkh")): st["mkh"] = mk; draw()
    cv.bind("<Motion>", on_motion)
    def on_leave(e):
        get_tip(cv).hide()
        if st["page"] == "build":
            if bst["hov"] is not None or bst.get("tip"): bst.update(hov=None, hpart=None, tip=None); draw()
        elif st.get("mkh"): st["mkh"] = False; draw()
    cv.bind("<Leave>", on_leave)
    def trunc(t_, n): return t_ if len(t_) <= n else t_[:n - 1] + "\u2026"
    # ---- live widgets
    ent = tk.Entry(cv, bg=C["fld"], fg=C["tx"], insertbackground=C["tx"], relief="flat", bd=0, highlightthickness=0, font=F(11))
    PH = "Paste or drop a link"
    def ph_set():
        if not ent.get(): ent.insert(0, PH); ent.config(fg=C["dim"]); ent._ph = True
    def ph_clear(_=None):
        if getattr(ent, "_ph", False): ent.delete(0, "end"); ent.config(fg=C["tx"]); ent._ph = False
    ent.bind("<FocusIn>", ph_clear); ent.bind("<FocusOut>", lambda e: ph_set()); ent.bind("<Return>", lambda e: ok_link())
    ent.bind("<<Paste>>", lambda e: (ph_clear(), d.after(10, ok_link_soft)))
    ph_set()
    nm = tk.Entry(cv, bg=C["ib"], fg=C["tx"], insertbackground=C["tx"], relief="flat", bd=0, highlightthickness=0, font=F(12, True))
    se = tk.Entry(cv, bg=C["ib"], fg=C["tx"], insertbackground=C["tx"], relief="flat", bd=0, highlightthickness=0, font=F(11))
    def parse_link(t_):
        m = RE_PLAYLIST.search(t_ or "")
        if m: return "spotify:playlist:" + m.group(1)
        if allow_tracks:
            tr = parse_track(t_ or "")
            if tr: return tr
        return None
    def finish(uri): res["uri"] = uri; d.destroy()
    def ok_link():
        if getattr(ent, "_ph", False): st["err"] = "Paste a link first"; draw(); return
        u = parse_link(ent.get().strip())
        if u: finish(u)
        else: st["err"] = "Not a Spotify %s link" % ("playlist or song" if allow_tracks else "playlist"); draw()
    def ok_link_soft():
        u = parse_link(ent.get().strip())
        if u: finish(u)
    # ---- background work (Spotify lookups), results come back through q
    def post(fn): q.append(fn)
    def pump():
        while q:
            try: q.pop(0)()
            except Exception as ex: log("Picker update: %r" % ex)
        try: d.after(80, pump)
        except tk.TclError: pass
    def sp_(): return Spotify(load_config())
    def meta(t):
        uri, name, artist = store_track(t, 96)
        return {"uri": uri, "name": name, "artist": artist, "ms": int(t.get("duration_ms") or 0)}
    # ---- pages
    def open_builder(uri=None):
        l = custom_get(uri, user) if uri else None
        st.update(page="build", id=(uri[len(CUSTOM_PREFIX):] if l else None), tracks=[dict(t) for t in (l or {}).get("tracks", []) if isinstance(t, dict)],
                  sc=0.0, search=False, results=[], busy="", err="")
        bst.update(hov=None, press=None, drag=None, ins=None, target=0.0, undo=[], redo=[], sel=0, toast=None, delarm=False)
        se.delete(0, "end")
        nm.delete(0, "end"); nm.insert(0, (l or {}).get("name") or "My list"); draw()
    def delete_list():
        if not bst.get("delarm"):
            bst["delarm"] = True; draw()
            def disarm():
                if bst.get("delarm"): bst["delarm"] = False; draw()
            d.after(3000, disarm); return
        bst["delarm"] = False; lid = st["id"]; uri = CUSTOM_PREFIX + lid
        lists.pop(lid, None)
        pls_ = user.get("playlists") if isinstance(user.get("playlists"), dict) else {}
        for k_ in [k_ for k_, v_ in pls_.items() if v_ == uri]: pls_.pop(k_)               # ages using it: back to default
        am_ = user.get("after_match") if isinstance(user.get("after_match"), dict) else {}
        for k_ in ("playlist", "win", "loss"):
            if am_.get(k_) == uri: am_[k_] = ""
        if save: save(user)
        try: os.remove(custom_cover(uri))
        except OSError: pass
        log("Deleted app list %s" % lid); res["deleted"] = uri; d.destroy()
    def save_list():
        if not st["tracks"]: return
        import secrets
        lid = st["id"] or secrets.token_hex(4); uri = CUSTOM_PREFIX + lid
        name = nm.get().strip()[:40] or "My list"
        lists[lid] = {"name": name, "tracks": st["tracks"][:CUSTOM_MAX]}
        if save: save(user)
        save_mosaic(uri, [t["uri"] for t in st["tracks"]]); finish(uri)
    # ================================================================ your playlists (Spotify library grid)
    GX, GY0, GW, GH, COLS, GAP = 28, 92, W - 56, 248, 4, 10
    GP = 4                                            # inner pad so the selection ring never clips
    GT = (GW - 12 - GP - GAP * (COLS - 1)) / COLS   # tile size; 12 = scrollbar lane
    GR = GT + 42                                      # row pitch (tile + name + count)
    GH = round(2 * GR + GP - 6)                       # exactly two rows; the scroll thumb shows there is more
    gc = tk.Canvas(cv, width=int(GW * S), height=int(GH * S), bg=C["card"], highlightthickness=0, bd=0)
    mp = {"state": "load", "items": list(_MYLIB.get("items") or []), "sel": None, "sc": 0.0, "tg": 0.0, "sjob": None,
          "use": False, "err": "", "covers": {}, "gjob": None, "hov": None}
    if mp["items"]: mp["state"] = "ok"
    _cur = LIKED_URI if current == CUSTOM_PREFIX + LIKED_ID else current
    ghand = {}
    d._mp = mp                                        # (tests)
    sq = tk.Entry(cv, bg=C["fld"], fg=C["tx"], insertbackground=C["tx"], relief="flat", bd=0, highlightthickness=0, font=F(10.5))
    SPH = "Search"
    def sq_ph():
        if not sq.get(): sq.insert(0, SPH); sq.config(fg=C["dim"]); sq._ph = True
    def sq_clr(_=None):
        if getattr(sq, "_ph", False): sq.delete(0, "end"); sq.config(fg=C["tx"]); sq._ph = False
    sq.bind("<FocusIn>", sq_clr); sq.bind("<FocusOut>", lambda e: sq_ph())
    def sq_key(_=None):
        mp["sc"] = mp["tg"] = 0.0; gdraw()
    sq.bind("<KeyRelease>", sq_key); sq.bind("<<Paste>>", lambda e: d.after(1, sq_key))
    sq.bind("<Escape>", lambda e: (sq.delete(0, "end"), sq_key(), "break")[2] if sq.get() and not getattr(sq, "_ph", False) else None)
    sq_ph()
    def mp_item(u): return next((it for it in mp["items"] if it["uri"] == u), None)
    def mp_shown():
        f_ = "" if getattr(sq, "_ph", False) else sq.get().strip().lower()
        return [it for it in mp["items"] if not f_ or f_ in it["name"].lower()]
    def g_max(): return max(0.0, ((len(mp_shown()) + COLS - 1) // COLS) * GR + GP - 6 - GH)
    def g_img(key, w, h, paint):
        return _img(key, int(round(w * S)), int(round(h * S)), paint)
    def tile_img(it):
        px = int(round(GT * S)); Q = 4; R = 8 * S
        if it.get("liked"):
            k = ("tl", "liked", px)
            if k not in imgs:
                a_ = Image.new("RGB", (px, px), "#4527d6"); b_ = Image.new("RGB", (px, px), "#9cc3e6")
                v_ = Image.linear_gradient("L"); g_ = Image.blend(v_, v_.rotate(90), 0.5).resize((px, px), Image.BICUBIC)   # diagonal
                im = Image.composite(a_, b_, g_.point(lambda v: 255 - v)).convert("RGBA")
                hz = px * Q; hl = Image.new("L", (hz, hz), 0); dr = ImageDraw.Draw(hl); u = hz / 100.0
                dr.ellipse([30 * u, 36 * u, 51 * u, 57 * u], fill=255); dr.ellipse([49 * u, 36 * u, 70 * u, 57 * u], fill=255)
                dr.polygon([(31.2 * u, 50 * u), (50 * u, 69 * u), (68.8 * u, 50 * u), (50 * u, 44 * u)], fill=255)
                hl = hl.resize((px, px), Image.LANCZOS); im.paste((255, 255, 255, 255), (0, 0), hl)
            else: im = None
        else:
            pth = mp["covers"].get(it["uri"])
            if pth is None:
                pth = lib_cover(it, fetch=False) or ""; mp["covers"][it["uri"]] = pth
            k = ("tl", it["uri"], pth, px)
            if k not in imgs:
                try: im = Image.open(pth).convert("RGBA").resize((px, px), Image.LANCZOS) if pth else None
                except Exception: im = None
                if im is None:
                    im = Image.new("RGBA", (px, px), "#2c2c2c")
                    ImageDraw.Draw(im).text((px // 2 - 4 * S, px // 2 - 7 * S), "\u266a", fill="#5a5a5a")
            else: im = None
        if k not in imgs:
            m = Image.new("L", (px * Q, px * Q), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, px * Q - 1, px * Q - 1], R * Q, fill=255)
            im.putalpha(m.resize((px, px), Image.LANCZOS)); imgs[k] = ImageTk.PhotoImage(im)
        return imgs[k]
    def ring_img():
        w = GT + 6
        def paint(dr, Q, im):
            n = int(round(w * S)) * Q; dr.rounded_rectangle([0, 0, n - 1, n - 1], radius=10.5 * S * Q, outline=C["acc"], width=max(1, int(2.2 * S * Q)))
        return g_img(("ring", w), w, w, paint)
    def badge_img():
        def paint(dr, Q, im):
            n = int(round(20 * S)) * Q; dr.ellipse([0, 0, n - 1, n - 1], fill=C["acc"])
            dr.line([(n * .29, n * .52), (n * .44, n * .66), (n * .72, n * .36)], fill="#121212", width=max(1, int(2.2 * S * Q)), joint="curve")
        return g_img(("badge",), 20, 20, paint)
    def gtext(x, y, s_, sz, c, b=False, anchor="w", tag=None):
        return gc.create_text(x * S, y * S, text=s_, font=F(sz, b), fill=c, anchor=anchor, tags=tag)
    def gdraw():
        if mp["gjob"]:
            try: d.after_cancel(mp["gjob"])
            except Exception: pass
            mp["gjob"] = None
        try: gc.delete("all")
        except tk.TclError: return
        ghand.clear()
        cx, cy = GW / 2, GH / 2 - 14
        if mp["state"] != "ok":
            msg, sub, btn = {"load": ("Loading your playlists\u2026", "", None),
                             "auth": ("Finish in your browser", "Then come back here", None),
                             "scope": ("Allow your playlists", "One more Spotify permission", ("Reconnect", reconnect)),
                             "login": ("Log in to Spotify first", "Use Log in in the panel", None),
                             "off": ("Can't reach Spotify", "", ("Retry", mp_load))}[mp["state"]]
            gtext(cx, cy, msg, 12.5, C["tx"], True, "center")
            if sub: gtext(cx, cy + 20, sub, 10.5, C["mu"], False, "center")
            if btn:
                bw = 104; x0 = cx - bw / 2; y0 = cy + 40
                def paint(dr, Q, im, bw=bw):
                    dr.rounded_rectangle([0, 0, int(round(bw * S)) * Q - 1, int(round(30 * S)) * Q - 1], radius=15 * S * Q, fill=C["acc"])
                gc.create_image(x0 * S, y0 * S, image=g_img(("gbtn", bw), bw, 30, paint), anchor="nw", tags="gb")
                gtext(cx, y0 + 15, btn[0], 11, "#121212", True, "center", "gb"); ghand["gb"] = btn[1]
            return
        items = mp_shown()
        if not items:
            gtext(cx, cy, "No matches", 12, C["mu"], False, "center"); return
        top = -mp["sc"]
        for i, it in enumerate(items):
            r_, c_ = divmod(i, COLS); x = GP + c_ * (GT + GAP); y = GP + r_ * GR + top
            if y + GR < -2 or y > GH + 2: continue
            tg = "g%d" % i; ghand[tg] = (lambda u=it["uri"]: g_select(u))
            gc.create_image(x * S, y * S, image=tile_img(it), anchor="nw", tags=tg)
            if it["uri"] == mp["sel"]:
                gc.create_image((x - 3) * S, (y - 3) * S, image=ring_img(), anchor="nw", tags=tg)
                gc.create_image((x + GT - 6) * S, (y + GT - 6) * S, image=badge_img(), anchor="se", tags=tg)
            elif mp["hov"] == it["uri"]:
                def paint(dr, Q, im):
                    n = int(round(GT * S)) * Q; dr.rounded_rectangle([0, 0, n - 1, n - 1], radius=8 * S * Q, fill=(255, 255, 255, 26))
                gc.create_image(x * S, y * S, image=g_img(("hov", GT), GT, GT, paint), anchor="nw", tags=tg)
            gtext(x + 1, y + GT + 13, fit(it["name"], 10.5, True, GT - 2), 10.5, C["tx"], True, "w", tg)
            n_ = it.get("n") or 0
            gtext(x + 1, y + GT + 29, "%d song%s" % (n_, "" if n_ == 1 else "s"), 9.5, C["mu"], False, "w", tg)
        mx = g_max()
        if mx > 0:                                    # slim scroll thumb in its own lane
            vis = GH / (GH + mx); th = max(28, GH * vis); ty = (GH - th) * (mp["sc"] / mx)
            def paint(dr, Q, im, th=th):
                dr.rounded_rectangle([0, 0, int(round(4 * S)) * Q - 1, int(round(th * S)) * Q - 1], radius=2 * S * Q, fill="#5a5a5a")
            col_ = "#9a9a9a" if mp.get("sbd") else ("#7a7a7a" if mp.get("sbh") else "#5a5a5a")
            def paint(dr, Q, im, th=th, col_=col_):
                dr.rounded_rectangle([0, 0, int(round(4 * S)) * Q - 1, int(round(th * S)) * Q - 1], radius=2 * S * Q, fill=col_)
            gc.create_image((GW - 4) * S, ty * S, image=g_img(("sb", int(th), col_), 4, int(th), paint), anchor="nw", tags="sbthumb")
    def gdraw_soon():
        if not mp["gjob"]: mp["gjob"] = d.after(60, gdraw)
    def g_select(u):
        mp["sel"] = u; mp["err"] = ""; gdraw(); draw()
    def g_tag(e):
        for it_ in reversed(gc.find_overlapping(e.x, e.y, e.x, e.y)):
            for t in gc.gettags(it_):
                if t in ghand: return t
        return None
    def g_sb(e):                                      # (max, thumb height, thumb top) when the press is in the scrollbar lane
        mx = g_max()
        if mx <= 0 or e.x / S < GW - 12: return None
        th = max(28, GH * GH / (GH + mx)); return mx, th, (GH - th) * (mp["sc"] / mx)
    def g_press(e):                                   # acts on press (popup is armed only after the opening release)
        if not st.get("armed") or mp["use"]: return
        sb = g_sb(e)
        if sb:
            mx, th, ty = sb; y = e.y / S
            if not (ty <= y <= ty + th): mp["sc"] = mp["tg"] = max(0.0, min(mx, (y - th / 2) * mx / max(1, GH - th)))
            mp["sbd"] = (y, mp["sc"]); gdraw(); return
        t = g_tag(e)
        if t: ghand[t]()
    def g_double(e):
        if st.get("armed") and g_tag(e) and str(g_tag(e)).startswith("g") and mp["sel"]: use_sel()
    def g_motion(e):
        h_ = bool(g_sb(e))
        if h_ != bool(mp.get("sbh")): mp["sbh"] = h_; gdraw()
        t = g_tag(e); gc.config(cursor="hand2" if (t or h_) else "")
        items = mp_shown(); u = None
        if t and t.startswith("g") and t[1:].isdigit() and int(t[1:]) < len(items): u = items[int(t[1:])]["uri"]
        if u != mp["hov"]: mp["hov"] = u; gdraw()
    def g_leave(e):
        if mp["hov"]: mp["hov"] = None; gdraw()
    def g_wheel(e):
        mp["tg"] = max(0.0, min(g_max(), mp["tg"] - (e.delta / 120) * GR * 0.6))
        if not mp["sjob"]: g_step()
    def g_step():
        dv = mp["tg"] - mp["sc"]
        if abs(dv) < 0.6: mp["sc"] = mp["tg"]; mp["sjob"] = None; gdraw(); return
        mp["sc"] += dv * 0.35; gdraw(); mp["sjob"] = d.after(15, g_step)
    def g_drag(e):
        if not mp.get("sbd"): return
        mx = g_max(); th = max(28, GH * GH / (GH + mx)) if mx > 0 else GH; y0, s0 = mp["sbd"]
        mp["sc"] = mp["tg"] = max(0.0, min(mx, s0 + (e.y / S - y0) * mx / max(1, GH - th))); gdraw()
    def g_release(e):
        if mp.get("sbd"): mp["sbd"] = None; gdraw()
    gc.bind("<B1-Motion>", g_drag); gc.bind("<ButtonRelease-1>", g_release)
    gc.bind("<ButtonPress-1>", g_press); gc.bind("<Double-Button-1>", g_double); gc.bind("<Motion>", g_motion)
    gc.bind("<Leave>", g_leave); gc.bind("<MouseWheel>", g_wheel)
    def mp_load():
        if not mp["items"] or mp["state"] != "ok": mp["state"] = "load"; gdraw()
        def work():
            try: stt, items = my_library(sp_())
            except BaseException as ex: log("Your playlists: %r" % ex); stt, items = "off", []
            post(lambda: mp_loaded(stt, items))
            if stt != "ok": return
            from concurrent.futures import ThreadPoolExecutor
            def one(it):
                pth = lib_cover(it)
                if pth: post(lambda u=it["uri"], p=pth: (mp["covers"].__setitem__(u, p), gdraw_soon()))
            with ThreadPoolExecutor(4) as ex_: list(ex_.map(one, [it for it in items if it.get("pid")]))
        threading.Thread(target=work, daemon=True).start()
    def mp_loaded(stt, items):
        if stt == "ok":
            mp["items"] = items; mp["state"] = "ok"; mp["covers"] = {k: v for k, v in mp["covers"].items() if v}
            if mp["sel"] is None and mp_item(_cur): mp["sel"] = _cur
        elif not (stt == "off" and mp["items"]): mp["state"] = stt      # offline but cached: keep showing the cache
        gdraw(); draw()
    def reconnect():
        mp["state"] = "auth"; gdraw()
        def work():
            try: Spotify(load_config()).login()
            except BaseException as ex: log("Reconnect: %r" % ex)
            post(mp_load)
        threading.Thread(target=work, daemon=True).start()
    def use_sel():
        it = mp_item(mp["sel"])
        if not it or mp["use"]: return
        if not it.get("liked"): finish(it["uri"]); return
        mp["use"] = True; draw()
        def work():
            tr = []
            try:
                for i, t in enumerate(liked_tracks(sp_(), CUSTOM_MAX)):
                    if i < 4: uri, name, artist = store_track(t, 96)             # covers for the list mosaic
                    else: uri, name, artist = t.get("uri"), t.get("name") or "Song", ", ".join(a_.get("name", "") for a_ in (t.get("artists") or [])[:2])
                    tr.append({"uri": uri, "name": name, "artist": artist, "ms": int(t.get("duration_ms") or 0)})
            except BaseException as ex: log("Liked Songs: %r" % ex)
            post(lambda: liked_done(tr))
        threading.Thread(target=work, daemon=True).start()
    def liked_done(tr):
        mp["use"] = False
        if not tr: mp["err"] = "Couldn't load Liked Songs"; draw(); return
        lists[LIKED_ID] = {"name": "Liked Songs", "tracks": tr[:CUSTOM_MAX]}
        if save: save(user)
        try: save_mosaic(CUSTOM_PREFIX + LIKED_ID, [t["uri"] for t in tr])
        except Exception as ex: log("Liked Songs cover: %r" % ex)
        finish(CUSTOM_PREFIX + LIKED_ID)
    if mp["items"] and mp_item(_cur): mp["sel"] = _cur
    def draw():
        cv.delete("all"); handlers.clear()
        (draw_pick if st["page"] == "pick" else draw_build)()
        set_canvas_height(cv, int(st["H"] * S))
    def draw_pick():
        text(20, 24, title, 15, b=True)
        # your playlists card (Liked Songs + your Spotify playlists)
        rr(16, 44, W - 16, GY0 + GH + 12, 12, C["card"])
        circ(40, 68, 14, "#2a2a2a"); icon("note", 40, 68, C["acc"]); text(64, 68, "Your playlists", 12.5, b=True)
        sx0 = W - 28 - 150
        rr(sx0, 54, W - 28, 82, 14, C["fld"], "#4a4a4a", 1.2); icon("search", sx0 + 16, 68, C["mu"], sz=18)
        cv.create_window(*P(sx0 + 30, 68), window=sq, anchor="w", width=int((150 - 42) * S), height=int(20 * S))
        cv.create_window(*P(GX, GY0), window=gc, anchor="nw")
        o = GY0 + GH + 24 - 44                       # everything below moves down by the new card
        # paste link card
        rr(16, o + 44, W - 16, o + 172, 12, C["card"])
        circ(40, o + 68, 14, "#2a2a2a"); icon("link", 40, o + 68, C["acc"]); text(64, o + 68, "Paste link", 12.5, b=True)
        hl = st["drag"]
        rr(28, o + 86, W - 28, o + 132, 10, "#1b2a20" if hl else C["fld"], C["acc"] if hl else "#4a4a4a", 1.4, dash=True)
        icon("drop", 48, o + 109, C["acc"] if hl else C["mu"], sz=22)
        ent.config(bg="#1b2a20" if hl else C["fld"])
        cv.create_window(*P(64, o + 109), window=ent, anchor="w", width=int((W - 28 - 64 - 60) * S), height=int(24 * S))
        rr(W - 80, o + 97, W - 38, o + 121, 12, C["acc"], tag="ok"); text(W - 59, o + 109, "OK", 11, "#121212", True, "center", "ok"); click("ok", ok_link)
        hint = st["err"] or ("Drop here" if hl else "Paste a link or drag a %s from Spotify" % ("playlist or song" if allow_tracks else "playlist"))
        text(30, o + 152, hint, 10.5, C["red"] if st["err"] else (C["acc"] if hl else C["mu"]))
        # make your own card
        y = o + 184; cur_l = custom_get(current, user) if is_custom(current) else None
        hv = st.get("mkh"); cy = y + 28                                     # one button: tile, title, grey subline, chevron
        rr(16, y, W - 16, y + 56, 12, "#22302a" if hv else "#1c241f", C["acc"] if hv else "#2f6b46", 1.2, tag="mk")
        trs = [t["uri"] for t in (cur_l or {}).get("tracks", [])] if cur_l else []
        if trs: cv.create_image(*P(28, cy - 18), image=mosaic(trs, 36, 9), anchor="nw", tags="mk")      # same slot as the + tile
        else: rr(28, cy - 18, 64, cy + 18, 9, "#24553a" if hv else "#1f4630", tag="mk"); icon("plus", 46, cy, C["acc"], tag="mk")
        text(78, cy - 8, ("Edit \u00b7 " + trunc(cur_l.get("name", "My list"), 22)) if cur_l else "Make your own", 12.5, b=True, tag="mk")
        text(78, cy + 10, "Saved in this app, not Spotify", 10.5, C["mu"], tag="mk")
        cx = W - 34 + (2 if hv else 0)
        cv.create_line(*P(cx - 2.5, cy - 5, cx + 2.5, cy, cx - 2.5, cy + 5), fill=C["acc"] if hv else C["mu"], width=max(1, 1.8 * S),
                       capstyle="round", joinstyle="round", smooth=False, tags="mk")
        click("mk", lambda: open_builder(current if cur_l else None))
        # your other lists
        others = [(k_, v_) for k_, v_ in lists.items() if isinstance(v_, dict) and CUSTOM_PREFIX + k_ != current][-4:]
        y += 68
        if others:
            text(20, y + 8, "Your lists", 10.5, C["mu"], True); y += 20
            for k_, v_ in others:
                tg = "ls_" + k_; rr(16, y, W - 16, y + 40, 10, C["card"], tag=tg)
                cv.create_image(*P(26, y + 6), image=mosaic([t.get("uri", "") for t in v_.get("tracks", [])], 28), anchor="nw", tags=tg)
                text(64, y + 20, trunc(v_.get("name", "My list"), 28), 12, b=True, tag=tg)
                text(W - 30, y + 20, "%d songs" % len(v_.get("tracks", [])), 10.5, C["mu"], anchor="e", tag=tg)
                click(tg, lambda k_=k_: finish(CUSTOM_PREFIX + k_)); y += 46
        # use button (applies the playlist picked in the grid)
        sel = mp_item(mp["sel"]); y += 6
        tg = "use" if sel and not mp["use"] else None
        rr(16, y, W - 16, y + 48, 24, C["acc"] if sel else "#262626", tag=tg)
        lab = mp["err"] or (("Loading Liked Songs\u2026" if mp["use"] else "Use " + fit(sel["name"], 13.5, True, W - 110)) if sel else "Pick a playlist")
        text(W / 2, y + 24, lab, 13.5, ("#121212" if sel else (C["red"] if mp["err"] else C["dim"])), True, "center", tg)
        if tg: click("use", use_sel)
        y += 48
        st["H"] = y + 16
    # ================================================================ builder (custom list editor)
    RH, VISN, LT = 48, 7, 138                       # row height, visible rows, list top
    LB = LT + RH * VISN                             # list bottom
    bst = {"hov": None, "hpart": None, "press": None, "drag": None, "ins": None, "target": 0.0, "sjob": None,
           "toast": None, "tjob": None, "undo": [], "redo": [], "sel": 0, "sb": None, "ajob": None, "qjob": None, "tip": None}
    pv = {"uri": None, "busy": False, "sp": None, "phase": 0, "job": None}
    d._t = (st, bst, pv); d._draw = lambda: draw()   # (tests)
    _fonts, _fits = {}, {}
    def fnt(sz, bold):
        if (sz, bold) not in _fonts: _fonts[(sz, bold)] = tkfont.Font(font=F(sz, bold))
        return _fonts[(sz, bold)]
    def fit(t_, sz, bold, maxw):
        k = (t_, sz, bold, int(maxw))
        if k in _fits: return _fits[k]
        f_ = fnt(sz, bold); mw = maxw * S; o = t_
        if f_.measure(t_) > mw:
            while t_ and f_.measure(t_ + "\u2026") > mw: t_ = t_[:-1]
            o = t_.rstrip() + "\u2026"
        _fits[k] = o; return o
    def max_sc(): return max(0.0, len(st["tracks"]) * RH - RH * VISN)
    # ---- undo / redo
    def snap(): bst["undo"].append([dict(t) for t in st["tracks"]]); bst["undo"][:] = bst["undo"][-60:]; bst["redo"].clear()
    def undo_redo(back):
        a_, b_ = (bst["undo"], bst["redo"]) if back else (bst["redo"], bst["undo"])
        if not a_: toast("Nothing to undo" if back else "Nothing to redo"); return
        b_.append([dict(t) for t in st["tracks"]]); st["tracks"] = a_.pop()
        toast("Undone" if back else "Redone"); draw()
    def key_undo(e, back):
        if st["page"] != "build": return
        f_ = d.focus_get()
        if f_ is nm or (f_ is se and se.get()): return              # text editing keeps its own keys
        undo_redo(back); return "break"
    d.bind("<Control-z>", lambda e: key_undo(e, True)); d.bind("<Control-Z>", lambda e: key_undo(e, True))
    d.bind("<Control-y>", lambda e: key_undo(e, False)); d.bind("<Control-Y>", lambda e: key_undo(e, False))
    # ---- toast (status line above the buttons; separate from tooltips)
    def toast(msg, undo=False, ms=3500):
        bst["toast"] = {"msg": msg, "undo": undo}
        if bst["tjob"]:
            try: d.after_cancel(bst["tjob"])
            except Exception: pass
        def clear(): bst["tjob"] = None; bst["toast"] = None; draw()
        bst["tjob"] = d.after(ms, clear) if ms else None; draw()
    # ---- preview (same fast path as the Age Intros editor: warm Spotify session, optimistic glow)
    def _warm():
        try:
            if pv["sp"] is None: pv["sp"] = Spotify(load_config())
            if pv["sp"].tok and hasattr(pv["sp"], "warm"): pv["sp"].warm()
        except Exception as ex: log("Builder preview warm-up: %r" % ex)
    threading.Thread(target=_warm, daemon=True).start()
    def preview(uri):
        if pv["busy"]: return
        action = "pause" if pv["uri"] == uri else "play"; prev = pv["uri"]
        pv["busy"] = True; pv["uri"] = uri if action == "play" else None; draw(); anim()
        def go():
            try:
                if pv["sp"] is None: pv["sp"] = Spotify(load_config())
                sp = pv["sp"]
                r_ = "login" if not sp.tok else bool(sp.preview(uri) if action == "play" else sp.pause())
            except Exception as ex: log("Builder preview: %r" % ex); r_ = False
            def done():
                pv["busy"] = False
                if r_ == "login": pv["uri"] = prev; toast("Log in to Spotify to preview")
                elif not r_: pv["uri"] = prev if action == "pause" else (None if prev == uri else prev); toast("Couldn't play \u2013 is Spotify running?")
                draw(); anim()
            post(done)
        threading.Thread(target=go, daemon=True).start()
    def anim():                                        # breathing glow + equalizer while a song previews
        if pv["job"]: return
        def tick():
            pv["job"] = None
            if st["page"] != "build" or not pv["uri"] or not d.winfo_exists(): return
            if win_hidden(d): pv["job"] = d.after(500, tick); return     # minimized: no redraws
            pv["phase"] = (pv["phase"] + 1) % 24
            if eq_step(pv["phase"]): pv["noglow"] = False
            elif not pv.get("noglow"):                     # items missing (just changed): one full redraw
                draw(); pv["noglow"] = not cv.find_withtag("pvglow")   # still none = playing row scrolled away: idle
            pv["job"] = d.after(70, tick)
        pv["job"] = d.after(70, tick)
    glow_c = {}
    def glow_img(ph):
        k = int(ph) % 24
        if k not in glow_c:
            import math
            a = int(70 + 70 * (0.5 + 0.5 * math.sin(k / 24 * 2 * math.pi)))
            n = int(48 * S); Q = 2; L_ = Image.new("L", (n * Q, n * Q), 0)
            ImageDraw.Draw(L_).rounded_rectangle([8 * S * Q, 8 * S * Q, 40 * S * Q, 40 * S * Q], 8 * S * Q, fill=a)
            L_ = L_.filter(ImageFilter.GaussianBlur(4 * S * Q)).resize((n, n), Image.LANCZOS)
            im = Image.new("RGBA", (n, n), (29, 185, 84, 0)); im.putalpha(L_)
            ImageDraw.Draw(im).rounded_rectangle([6.5 * S, 6.5 * S, 41.5 * S, 41.5 * S], 7.5 * S, outline=(29, 185, 84, 255), width=max(1, int(1.6 * S)))
            glow_c[k] = ImageTk.PhotoImage(im)
        return glow_c[k]
    def eq_badge(x, y, ph):
        circ(x, y, 9, C["bg"]); circ(x, y, 7.5, C["acc"])
        import math
        for i_ in range(3):
            h_ = 3 + 4 * (0.5 + 0.5 * math.sin((ph + i_ * 7) / 24 * 2 * math.pi))
            cv.create_rectangle(*P(x - 4 + i_ * 3, y + 3.5 - h_, x - 2.2 + i_ * 3, y + 3.5), fill="#121212", outline="", tags="pveqbar")
        pv["eqxy"] = (x, y)
    def eq_step(ph):
        """One animation frame in place: re-image the glow, move the 3 equalizer bars (no full redraw)."""
        import math
        gl = cv.find_withtag("pvglow"); bars = cv.find_withtag("pveqbar")
        if len(gl) != 1 or len(bars) != 3 or not pv.get("eqxy"): return False
        cv.itemconfigure(gl[0], image=glow_img(ph)); x, y = pv["eqxy"]
        for i_, b_ in enumerate(bars):
            h_ = 3 + 4 * (0.5 + 0.5 * math.sin((ph + i_ * 7) / 24 * 2 * math.pi))
            cv.coords(b_, *P(x - 4 + i_ * 3, y + 3.5 - h_, x - 2.2 + i_ * 3, y + 3.5))
        return True
    def cover_overlay(playing):
        def paint(dr, Q, im):
            dr.rounded_rectangle([0, 0, 32 * S * Q - 1, 32 * S * Q - 1], 6 * S * Q, fill=(0, 0, 0, 120))
            c_ = 16 * S * Q
            if playing:
                for dx in (-4, 2): dr.rounded_rectangle([c_ + dx * S * Q, c_ - 5 * S * Q, c_ + (dx + 2.4) * S * Q, c_ + 5 * S * Q], S * Q, fill=(255, 255, 255, 255))
            else: dr.polygon([(c_ - 3.5 * S * Q, c_ - 5.5 * S * Q), (c_ - 3.5 * S * Q, c_ + 5.5 * S * Q), (c_ + 5.5 * S * Q, c_)], fill=(255, 255, 255, 255))
        return _img(("cov_ov", playing), int(32 * S), int(32 * S), paint)
    shadow_c = {}
    def ghost_shadow(w_, h_):
        k = (int(w_), int(h_))
        if k not in shadow_c:
            m = int(12 * S); W_, H_ = int(w_ * S) + 2 * m, int(h_ * S) + 2 * m; L_ = Image.new("L", (W_, H_), 0)
            ImageDraw.Draw(L_).rounded_rectangle([m, m + 4 * S, W_ - m, H_ - m + 4 * S], 10 * S, fill=170)
            im = Image.new("RGBA", (W_, H_), (0, 0, 0, 0)); im.putalpha(L_.filter(ImageFilter.GaussianBlur(6 * S)))
            shadow_c[k] = ImageTk.PhotoImage(im)
        return shadow_c[k]
    def empty_art():
        def paint(dr, Q, im):
            for dx, rot, c1, c2 in ((-28, -12, (150, 70, 70), (70, 30, 35)), (28, 12, (90, 150, 80), (35, 70, 35)), (0, 0, (70, 120, 170), (25, 45, 85))):
                n = int(46 * S * Q); g = Image.new("RGBA", (n, n)); gd = ImageDraw.Draw(g)
                for yy in range(n):
                    t_ = yy / n; gd.line([(0, yy), (n, yy)], fill=tuple(int(c1[k] * (1 - t_) + c2[k] * t_) for k in range(3)) + (255,))
                m = Image.new("L", (n, n), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, n - 1, n - 1], 8 * S * Q, fill=255); g.putalpha(m)
                g = g.rotate(rot, resample=Image.BICUBIC, expand=True)
                im.alpha_composite(g, (int(im.width / 2 + dx * S * Q - g.width / 2), int(40 * S * Q - g.height / 2)))
            cx_, cy_ = im.width / 2, 74 * S * Q; r_ = 14 * S * Q
            dr.ellipse([cx_ - r_, cy_ - r_, cx_ + r_, cy_ + r_], fill=(29, 185, 84, 255))
            lw = int(2.2 * S * Q)
            dr.line([(cx_, cy_ - 7 * S * Q), (cx_, cy_ + 6 * S * Q)], fill=(18, 18, 18, 255), width=lw)
            dr.line([(cx_ - 5 * S * Q, cy_ + 1 * S * Q), (cx_, cy_ + 6 * S * Q), (cx_ + 5 * S * Q, cy_ + 1 * S * Q)], fill=(18, 18, 18, 255), width=lw, joint="curve")
        return _img(("empty_art",), int(140 * S), int(92 * S), paint)
    # ---- adding songs
    def add_uris(uris, src=""):
        have = {t["uri"] for t in st["tracks"]}; new = [u for u in dict.fromkeys(uris) if u not in have]; dup = len(set(uris)) - len(new)
        room = CUSTOM_MAX - len(st["tracks"])
        if not new: toast("Already in the list" if dup else "Nothing to add"); return
        if room <= 0: toast("100 songs max"); return
        new = new[:room]; toast("Adding\u2026", ms=0)
        def go():
            out = []
            try:
                sp = pv["sp"] or Spotify(load_config())
                for k in range(0, len(new), 50):
                    c, r = sp._api("GET", "/tracks?ids=" + ",".join(u.split(":")[-1] for u in new[k:k + 50]))
                    if c == 200 and isinstance(r, dict): out += [meta(t) for t in (r.get("tracks") or []) if isinstance(t, dict) and t.get("uri")]
            except Exception as ex: log("Builder add: %r" % ex)
            def done():
                hv = {t["uri"] for t in st["tracks"]}; got = [t for t in out if t["uri"] not in hv][:CUSTOM_MAX - len(st["tracks"])]
                if got: snap(); st["tracks"] += got; bst["target"] = max_sc(); smooth()
                n_ = len(got)
                toast(("Added %d song%s" % (n_, "" if n_ == 1 else "s") + (" \u00b7 %d already in" % dup if dup else "")) if n_ else "Couldn't add")
            post(done)
        threading.Thread(target=go, daemon=True).start()
    def add_playing():
        toast("Checking what's playing\u2026", ms=0)
        def go():
            it = None
            try: it = now_playing(pv["sp"] or Spotify(load_config()))
            except Exception as ex: log("Now playing: %r" % ex)
            post(lambda: add_uris([it["uri"]]) if it else toast("Nothing playing"))
        threading.Thread(target=go, daemon=True).start()
    def add_paste():
        try: t_ = d.clipboard_get()
        except tk.TclError: t_ = ""
        u = parse_tracks(t_)
        if u: add_uris(u)
        else: toast("No song links in the clipboard")
    # ---- inline search with a floating results dropdown
    def do_search(now=False):
        if bst["qjob"]:
            try: d.after_cancel(bst["qjob"])
            except Exception: pass
            bst["qjob"] = None
        qq = se.get().strip()
        if len(qq) < 2: st["results"] = []; st["busy"] = ""; draw(); return
        def run():
            bst["qjob"] = None; st["busy"] = "search"; draw()
            def go():
                items = None
                try: items = search_tracks(pv["sp"] or Spotify(load_config()), qq, 5)
                except Exception as ex: log("Search: %r" % ex)
                out = [meta(t) for t in (items or [])]
                def done():
                    if se.get().strip() != qq: return                   # typed on meanwhile
                    st["results"] = out; bst["sel"] = 0; st["busy"] = ""
                    if not out: toast("No results")
                    draw()
                post(done)
            threading.Thread(target=go, daemon=True).start()
        if now: run()
        else: bst["qjob"] = d.after(350, run)
    def se_key(e):
        k = e.keysym
        if k in ("Down", "Up"):
            if st["results"]: bst["sel"] = (bst["sel"] + (1 if k == "Down" else -1)) % len(st["results"]); draw()
            return "break"
        if k == "Return":
            if st["results"]: pick_result(bst["sel"])
            else: do_search(now=True)
            return "break"
        if k == "Escape":
            if st["results"] or se.get(): se.delete(0, "end"); st["results"] = []; draw(); return "break"
            return None
        if k not in ("Left", "Right", "Home", "End", "Shift_L", "Shift_R", "Control_L", "Control_R"): do_search()
    se.bind("<KeyRelease>", lambda e: None if e.keysym in ("Down", "Up", "Return", "Escape") else se_key(e))
    se.bind("<KeyPress-Down>", se_key); se.bind("<KeyPress-Up>", se_key); se.bind("<Return>", se_key); se.bind("<Escape>", se_key)
    se.bind("<<Paste>>", lambda e: d.after(20, lambda: (add_uris(parse_tracks(se.get())), se.delete(0, "end")) if parse_tracks(se.get()) else do_search()))
    def pick_result(i_):
        if 0 <= i_ < len(st["results"]):
            r_ = st["results"][i_]
            if any(t["uri"] == r_["uri"] for t in st["tracks"]): toast("Already in the list"); return
            snap(); st["tracks"].append(dict(r_)); bst["target"] = max_sc(); smooth()
            toast("Added \u201c%s\u201d" % fit(r_.get("name", "Song"), 10.5, False, 200))
    # ---- smooth scrolling
    def smooth():
        if bst["sjob"]: return
        def step():
            bst["sjob"] = None
            t_ = max(0.0, min(max_sc(), bst["target"])); bst["target"] = t_
            dlt = t_ - st["sc"]
            if abs(dlt) < 0.6: st["sc"] = t_; draw(); return
            st["sc"] += dlt * 0.35; draw(); bst["sjob"] = d.after(16, step)
        step()
    # ---- removing
    def remove(i_):
        if not (0 <= i_ < len(st["tracks"])): return
        snap(); t_ = st["tracks"].pop(i_)
        if pv["uri"] == t_["uri"]: pass                   # keeps playing; just no row to glow on
        bst["target"] = min(bst["target"], max_sc()); st["sc"] = min(st["sc"], max_sc())
        bst["hov"] = None; toast("Removed \u201c%s\u201d" % fit(t_.get("name", "Song"), 10.5, False, 150), undo=True, ms=5000)
    # ---- drawing
    def row_top(i_): return LT + i_ * RH - st["sc"]
    def draw_build():
        trs = st["tracks"]; n = len(trs); ph = pv["phase"]; hv = bst["hov"]; dg = bst["drag"]
        # list first (header / footer are painted over its overflow)
        if n:
            first = max(0, int(st["sc"] // RH)); last = min(n, first + VISN + 2)
            for i_ in range(first, last):
                if dg and dg["i"] == i_: continue
                t_ = trs[i_]; ry = row_top(i_); tg = "row%d" % i_
                playing = pv["uri"] == t_["uri"]; hover = hv == i_ and not dg
                if playing: rr(20, ry + 2, W - 20, ry + RH - 2, 10, "#17271d", tag=tg)
                elif hover: rr(20, ry + 2, W - 20, ry + RH - 2, 10, "#1f1f1f", tag=tg)
                else: rr(20, ry + 2, W - 20, ry + RH - 2, 10, C["bg"], tag=tg)
                text(36, ry + RH / 2, str(i_ + 1), 10.5, C["acc"] if playing else C["mu"], playing, "center", tg)
                if playing: cv.create_image(*P(68, ry + RH / 2), image=glow_img(ph), anchor="center", tags=(tg, "pvglow"))
                cv.create_image(*P(52, ry + 8), image=thumb(track_cover(t_["uri"]), 32), anchor="nw", tags=tg)
                if hover: cv.create_image(*P(52, ry + 8), image=cover_overlay(playing), anchor="nw", tags=tg)
                if playing: eq_badge(84, ry + 38, ph)
                right = (W - 104) if hover else (W - 72)
                text(96, ry + 17, fit(t_.get("name", "Song"), 11.5, True, right - 96), 11.5, C["acc"] if playing else C["tx"], True, tag=tg)
                text(96, ry + 32, fit(t_.get("artist", ""), 10, False, right - 96), 10, C["mu"], tag=tg)
                dur = "%d:%02d" % (t_["ms"] // 60000, t_["ms"] // 1000 % 60) if t_.get("ms") else ""
                if hover:
                    icon("handle", W - 92, ry + RH / 2, C["mu"], sz=18, tag="hd%d" % i_)
                    text(W - 58, ry + RH / 2, dur, 10.5, C["mu"], anchor="e", tag=tg)
                    rt = "rm%d" % i_; circ(W - 40, ry + RH / 2, 11, "#3a3a3a" if bst["hpart"] == "rm" else "#2a2a2a", tag=rt)
                    icon("x", W - 40, ry + RH / 2, C["tx"], sz=18, tag=rt); click(rt, lambda i_=i_: remove(i_))
                else: text(W - 34, ry + RH / 2, dur, 10.5, C["mu"], anchor="e", tag=tg)
            if dg and bst["ins"] is not None:                          # insertion line + floating ghost
                iy = LT + bst["ins"] * RH - st["sc"]
                rr(20, iy - 1, W - 20, iy + 1, 1, C["acc"]); circ(22, iy, 3.5, C["acc"])
                t_ = trs[dg["i"]]; gy = dg["y"] - dg["off"]
                cv.create_image(*P(60 - 12, gy - 12 + 2), image=ghost_shadow(W - 100, 40), anchor="nw")
                rr(60, gy, W - 40, gy + 40, 10, "#2b2b2d", "#3a3a3c", 1)
                cv.create_image(*P(68, gy + 6), image=thumb(track_cover(t_["uri"]), 28), anchor="nw")
                text(106, gy + 14, fit(t_.get("name", "Song"), 11.5, True, W - 160), 11.5, b=True); text(106, gy + 28, fit(t_.get("artist", ""), 10, False, W - 160), 10, C["mu"])
            if max_sc() > 0:                                           # scrollbar (draggable)
                vh = RH * VISN; th = max(28, vh * vh / (n * RH)); ty = LT + (vh - th) * st["sc"] / max_sc()
                hot = bool(bst["sb"]) or bst.get("sbh")
                rr(W - 18, LT, W - 2, LB, 4, "", tag="sb")                             # invisible, easy-to-hit lane
                rr(W - 12, LT + 2, W - 8, LB - 2, 2, "#222222", tag="sb"); rr(W - 13, ty + 2, W - 7, ty + th - 2, 3, "#8a8a8a" if bst["sb"] else ("#6a6a6a" if hot else "#4a4a4a"), tag=("sb", "sbthumb"))
        else:                                                          # empty state
            hl = st["drag"]
            rr(20, LT + 8, W - 20, LT + 216, 14, "#16261c" if hl else "#151a16", C["acc"] if hl else "#3f5a48", 1.4, dash=True)
            cv.create_image(*P(W / 2, LT + 70), image=empty_art(), anchor="center")
            text(W / 2, LT + 142, "Drop songs from Spotify", 12.5, C["tx"], True, "center")
            text(W / 2, LT + 164, "or search, add what's playing, paste links", 10.5, C["mu"], False, "center")
        if n and st["drag"]: rr(16, LT - 4, W - 16, LB + 4, 12, None, C["acc"], 1.4, dash=True)   # drop from Spotify
        # masks over the list overflow
        cv.create_rectangle(0, 0, W * S, LT * S - 1, fill=C["bg"], outline="")
        cv.create_rectangle(0, LB * S + 1, W * S, (LB + 200) * S, fill=C["bg"], outline="")
        # header
        cv.create_image(*P(30, 46), image=_img(("bk", ""), int(32 * S), int(32 * S),
                        lambda dr, Q, im: dr.ellipse([0, 0, 32 * S * Q - 1, 32 * S * Q - 1], fill="#2a2a2a")), anchor="center", tags="back")
        icon("back", 30, 46, C["tx"], tag="back"); click("back", lambda: (st.update(page="pick", err=""), draw()))
        if trs: cv.create_image(*P(56, 14), image=mosaic([t["uri"] for t in trs], 64, 8), anchor="nw")
        else: rr(56, 14, 120, 78, 8, "#1f2a23"); icon("note", 88, 46, C["acc"], "#1f2a23", sz=26)
        rr(132, 16, W - 20, 46, 9, C["ib"])
        cv.create_window(*P(144, 31), window=nm, anchor="w", width=int((W - 20 - 144 - 10) * S), height=int(24 * S))
        mins = sum(t.get("ms", 0) for t in trs) // 60000
        text(134, 62, ("%d song%s \u00b7 %d min" % (n, "" if n == 1 else "s", mins)) if n else "No songs yet", 10.5, C["mu"])
        # add bar: search + add playing + paste
        sf = d.focus_get() is se
        rr(20, 92, W - 96, 126, 17, C["ib"], C["acc"] if sf else "#3a3a3a", 1)
        icon("search", 38, 109, C["acc"] if sf else C["mu"], C["ib"], sz=18)
        cv.create_window(*P(54, 109), window=se, anchor="w", width=int((W - 96 - 54 - 30) * S), height=int(22 * S))
        if st.get("busy") == "search": text(W - 108, 109, "\u2026", 12, C["mu"], anchor="e")
        if not se.get() and not sf: text(56, 109, "Search songs", 11, C["dim"], tag="seph"); click("seph", lambda: se.focus_set())
        for k_, (ic, tg) in enumerate((("playing", "tbp"), ("paste", "tbv"))):
            x_ = W - 74 + k_ * 38; circ(x_, 109, 16, "#333333" if bst.get("tip") == tg else C["ib"], tag=tg); icon(ic, x_, 109, C["tx"] if bst.get("tip") == tg else C["mu"], sz=20, tag=tg)
        click("tbp", add_playing); click("tbv", add_paste)
        # results dropdown (floats over the list)
        rs = st["results"]
        if rs:
            h_ = len(rs) * 44 + 8; y0 = 132
            cv.create_image(*P(20 - 12, y0 - 12 + 2), image=ghost_shadow(W - 116, h_), anchor="nw")
            rr(20, y0, W - 96, y0 + h_, 10, "#262628", "#3a3a3c", 1, tag="dd")
            for j_, r_ in enumerate(rs):
                yy = y0 + 4 + j_ * 44; tg = "sr%d" % j_; inl = any(t["uri"] == r_["uri"] for t in trs)
                if j_ == bst["sel"]: rr(24, yy, W - 100, yy + 42, 8, "#2f2f31", tag=tg)
                else: rr(24, yy, W - 100, yy + 42, 8, "#262628", tag=tg)
                cv.create_image(*P(30, yy + 7), image=thumb(track_cover(r_["uri"]), 28), anchor="nw", tags=tg)
                text(68, yy + 15, fit(r_["name"], 11, True, W - 200), 11, b=True, tag=tg); text(68, yy + 30, fit(r_["artist"], 9.5, False, W - 200), 9.5, C["mu"], tag=tg)
                circ(W - 120, yy + 21, 11, "#1c3a26" if not inl else "#2a2a2a", tag=tg)
                icon("x" if False else ("plus" if not inl else "note"), W - 120, yy + 21, C["acc"] if not inl else C["mu"], sz=16, tag=tg)
                click(tg, lambda j_=j_: pick_result(j_))
        # toast + footer
        ty_ = LB + 8; tb = bst["toast"]
        if tb:
            msg = tb["msg"]; tw_ = fnt(10.5, False).measure(msg) / S + 28 + (48 if tb["undo"] else 0)
            rr(20, ty_, 20 + tw_, ty_ + 32, 16, "#2b2b2d", "#3a3a3c", 1); text(34, ty_ + 16, msg, 10.5, C["tx"])
            if tb["undo"]:
                text(20 + tw_ - 14, ty_ + 16, "Undo", 10.5, C["acc"], True, "e", "undo"); click("undo", lambda: undo_redo(True))
        fy = LB + 50
        stg = "save" if n else "save_off"                                  # empty: visibly disabled, not clickable
        rr(W - 120, fy, W - 20, fy + 32, 16, C["acc"] if n else "#2a2a2a", tag=stg); text(W - 70, fy + 16, "Save", 12, "#121212" if n else C["dim"], True, "center", stg)
        rr(W - 218, fy, W - 130, fy + 32, 16, "#2a2a2a", tag="cancel"); text(W - 174, fy + 16, "Cancel", 12, C["tx"], False, "center", "cancel")
        if n: click("save", save_list)
        click("cancel", d.destroy)
        if st["id"] and st["id"] in lists:                                  # saved list: Delete (press twice)
            arm_ = bst.get("delarm")
            rr(20, fy, 122, fy + 32, 16, C["red"] if arm_ else "#2a2a2a", None if arm_ else "#5a3330", 1.2, tag="dellist")
            text(71, fy + 16, "Confirm" if arm_ else "Delete list", 11.5, "#121212" if arm_ else C["red"], True, "center", "dellist")
            click("dellist", delete_list)
        if not n:
            text(W - 70, fy + 46, "Add a song to save", 9.5, C["mu"], False, "center"); st["H"] = fy + 32 + 30
        else: st["H"] = fy + 32 + 14
    # ---- pointer
    def tags_at(e): return {t for it in cv.find_overlapping(e.x, e.y, e.x, e.y) for t in cv.gettags(it)}
    def row_of(tags):
        for t in tags:
            if t[:3] in ("row", "rm", "hd") or t.startswith("rm"):
                k = t[3:] if t.startswith("row") else t[2:]
                if k.isdigit(): return int(k)
        return None
    def b_motion(e):
        tags = tags_at(e); y_ = e.y / S
        if ("sb" in tags) != bool(bst.get("sbh")): bst["sbh"] = "sb" in tags; draw()
        h_ = row_of(tags) if LT <= y_ <= LB and not st["results"] else None
        part = "rm" if any(t.startswith("rm") for t in tags) else ("hd" if any(t.startswith("hd") for t in tags) else None)
        tipt = next((t for t in ("tbp", "tbv") if t in tags), None)
        if (h_, part, tipt) != (bst["hov"], bst["hpart"], bst.get("tip")):
            bst["hov"], bst["hpart"], bst["tip"] = h_, part, tipt; draw()
            if tipt:
                bb = cv.bbox(tipt)
                if bb: get_tip(cv).request(("bld", tipt), {"tbp": "Add what's playing", "tbv": "Paste song links"}[tipt], canvas_rect(cv, bb), S, cv)
            else: get_tip(cv).hide()
        sr = next((int(t[2:]) for t in tags if t.startswith("sr") and t[2:].isdigit()), None)
        if sr is not None and sr != bst["sel"]: bst["sel"] = sr; draw()
        cur_ = "fleur" if part == "hd" else ("hand2" if (h_ is not None or any(t in handlers for t in tags) or "sb" in tags) else "")
        if cv.cget("cursor") != cur_: cv.config(cursor=cur_)
    def b_press(e):
        tags = tags_at(e); y_ = e.y / S
        if st["results"] and "dd" not in tags and not any(t.startswith("sr") for t in tags):
            st["results"] = []; draw()                                  # click outside closes the dropdown
        if "dd" in tags or any(t.startswith("sr") for t in tags): return      # dropdown sits over the list rows
        if "sb" in tags and max_sc() > 0:
            vh = RH * VISN; th = max(28, vh * vh / (len(st["tracks"]) * RH)); ty = LT + (vh - th) * st["sc"] / max_sc()
            if not (ty <= y_ <= ty + th):                                    # track click: jump there, then grab
                st["sc"] = bst["target"] = max(0.0, min(max_sc(), (y_ - LT - th / 2) * max_sc() / max(1, vh - th)))
            bst["sb"] = (y_, st["sc"]); draw(); return
        i_ = row_of(tags)
        if i_ is not None and not any(t.startswith("rm") for t in tags) and LT <= y_ <= LB:
            bst["press"] = {"i": i_, "x": e.x / S, "y": y_, "off": y_ - row_top(i_)}
    def ins_at(y_):
        return max(0, min(len(st["tracks"]), int(round((y_ - LT + st["sc"]) / RH))))
    def b_drag(e):
        y_ = e.y / S
        if bst["sb"]:
            y0, s0 = bst["sb"]; vh = RH * VISN; th = max(28, vh * vh / (len(st["tracks"]) * RH))
            st["sc"] = bst["target"] = max(0.0, min(max_sc(), s0 + (y_ - y0) * max_sc() / max(1, vh - th))); draw(); return
        p_ = bst["press"]
        if not p_: return
        if not bst["drag"] and abs(y_ - p_["y"]) + abs(e.x / S - p_["x"]) < 5: return
        if not bst["drag"]: bst["drag"] = {"i": p_["i"], "off": p_["off"], "y": y_}; get_tip(cv).hide()
        bst["drag"]["y"] = max(LT - 20, min(LB - 20, y_)); bst["ins"] = ins_at(y_); draw()
        if (y_ < LT + 24 or y_ > LB - 24) and not bst["ajob"]:          # edge auto-scroll
            def auto():
                bst["ajob"] = None
                if not bst["drag"]: return
                yy = bst["drag"]["y"]; dv = -9 if yy < LT + 24 else (9 if yy > LB - 44 else 0)
                if not dv: return
                st["sc"] = bst["target"] = max(0.0, min(max_sc(), st["sc"] + dv)); bst["ins"] = ins_at(yy); draw()
                bst["ajob"] = d.after(30, auto)
            auto()
    def b_release(e):
        """Returns True when the builder consumed the release."""
        if bst["sb"]: bst["sb"] = None; draw(); return True
        p_, dg = bst["press"], bst["drag"]; bst["press"] = None; bst["drag"] = None
        if dg:
            i_, j_ = dg["i"], bst["ins"]; bst["ins"] = None
            if j_ is not None and j_ not in (i_, i_ + 1):
                snap(); t_ = st["tracks"].pop(i_); st["tracks"].insert(j_ - 1 if j_ > i_ else j_, t_)
            draw(); return True
        if p_:
            tags = tags_at(e)
            if row_of(tags) == p_["i"] and not any(t.startswith("rm") or t.startswith("hd") for t in tags):
                preview(st["tracks"][p_["i"]]["uri"]); return True
        return False
    def b_cancel(_=None):
        bst["press"] = None; bst["sb"] = None
        if bst["drag"]: bst["drag"] = None; bst["ins"] = None; draw()
    def on_press(e):
        st["pdown"] = bool(st.get("armed"))
        if not st.get("armed"): return
        if st["page"] == "build": b_press(e)
    def end_move(e): st["move"] = None
    cv.bind("<ButtonPress-1>", on_press); cv.bind("<B1-Motion>", lambda e: b_drag(e) if st["page"] == "build" and st.get("armed") else None)
    def cancel_ptr(_=None):
        st.pop("pdown", None); b_cancel()
    d.bind("<FocusOut>", lambda e: d.after(50, lambda: (d.focus_displayof() is None) and cancel_ptr()), add="+")
    def on_wheel(e):
        if st["page"] == "build" and not st["results"]:
            get_tip(cv).hide(); bst["target"] = max(0.0, min(max_sc(), bst["target"] - (e.delta / 120) * RH * 1.5)); smooth()
    cv.bind("<MouseWheel>", on_wheel)
    # ---- drag & drop from Spotify
    def on_drop(data):
        st["drag"] = False
        if st["page"] == "pick":
            u = parse_link(data or "")
            if u: finish(u); return
            st["err"] = "Not a Spotify %s" % ("playlist or song" if allow_tracks else "playlist"); draw()
        else:
            u = parse_tracks(data or "")
            if u: add_uris(u)
            else: st["busy"] = "Drop songs (not playlists)"; draw()
    try:
        from tkinterdnd2 import TkinterDnD, DND_TEXT
        TkinterDnD._require(d)
        for w_ in (cv, ent):
            w_.drop_target_register(DND_TEXT)
            w_.dnd_bind("<<DropEnter>>", lambda e: (st.update(drag=True, err=""), draw(), "copy")[2])
            w_.dnd_bind("<<DropPosition>>", lambda e: "copy")
            w_.dnd_bind("<<DropLeave>>", lambda e: (st.update(drag=False), draw(), "copy")[2])
            w_.dnd_bind("<<Drop>>", lambda e: (d.after_idle(lambda x=e.data: on_drop(x)), "copy")[1])
    except Exception as ex: log("Picker drag-in unavailable: %r" % ex)
    d.bind("<Escape>", lambda e: d.destroy() if st["page"] == "pick" else (st.update(page="pick"), draw()))
    install_edit_menu(d)
    if start_builder: open_builder(current if is_custom(current) else None)
    else: draw()
    pump(); mp_load()
    try: reveal(d, fade=False, over=parent)
    except Exception: pass
    def arm():                                         # input + modal grab only after the opening press is fully released
        st["armed"] = True
        try: d.grab_set()
        except tk.TclError: pass
    after_mouse_up(d, arm)
    parent.wait_window(d)
    return res.get("uri")
RELEASES_URL = "https://github.com/Capstar1/aoe4-spotify/releases"
NAMES_CACHE = os.path.join(DATA, "playlist_names.json")
COVERS = os.path.join(DATA, "covers")              # playlist cover thumbnails: <playlist id>_<snapshot>.jpg
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
AGES = [("dark", "Dark"), ("feudal", "Feudal"), ("castle", "Castle"), ("imperial", "Imperial")]
RE_PLAYLIST = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z]+/)?playlist/|spotify:playlist:)([A-Za-z0-9]{22})")
SONGS = [  # key, song, character (portrait), Spotify track, ring colour
    ("light", "For Light", "Ophilia", "spotify:track:5sEHThQpQWTZZVIbmFIx4k", "#e8d9a0"),
    ("truth", "For Truth", "Cyrus", "spotify:track:0iBkJlkxLIZvw64YMJEhpY", "#6fa8dc"),
    ("treasure", "For Treasure", "Tressa", "spotify:track:4RmbTKOJGdfKVEnwTUAobp", "#e0b040"),
    ("redemption", "For Redemption", "Olberic", "spotify:track:6bZVraEtKL5lQ7TtUrhX8K", "#b0b0b0"),
    ("revenge", "For Revenge", "Primrose", "spotify:track:6hdfIg76lNerf0bLt7ppAo", "#c0506a"),
    ("succor", "For Succor", "Alfyn", "spotify:track:0JhmuCu4N8XT9nRVFsngS9", "#7cc47c"),
    ("freedom", "For Freedom", "Therion", "spotify:track:3LxsqAQ0rXaLEHonDax63B", "#d9a066"),
    ("master", "For Master", "H'aanit", "spotify:track:5X8te47Qx2kIeAqAicMrgC", "#8fbf6a"),
]
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
def track_cover(uri): return os.path.join(COVERS, "track_%s.jpg" % uri.split(":")[-1])
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
LIKED_URI = "aoe4s:liked"; LIKED_ID = "liked"
_MYLIB = {}                                         # last good list, so a reopened picker shows it instantly
def lib_scopes_ok(sp):
    t = getattr(sp, "tok", None) or Spotify._disk_tok() or {}
    have = set(str(t.get("scope") or "").split())
    return all(x in have for x in LIB_SCOPES)
def _next_path(r):
    n = r.get("next") if isinstance(r, dict) else None
    return n.split("/v1", 1)[1] if isinstance(n, str) and "/v1/" in n else None
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
CIV_LIST = [("french", "French"), ("hre", "HRE"), ("templar", "Templar"), ("french_ha_01", "Jeanne d'Arc"),
            ("abbasid", "Abbasid"), ("abbasid_ha_01", "Ayyubids"), ("byzantine", "Byzantines"), ("malian", "Malians"),
            ("sultanate", "Delhi"), ("ottoman", "Ottomans"), ("english", "English"), ("hre_ha_01", "Dragon"),
            ("lancaster", "Lancaster"), ("mongol", "Mongols"), ("mongol_ha_gol", "Golden Horde"), ("rus", "Rus"),
            ("chinese_ha_01", "Zhu Xi"), ("chinese", "Chinese"), ("japanese", "Japanese"), ("jin_dynasty", "Jin"),
            ("japanese_ha_sen", "Sengoku"), ("sultanate_ha_tug", "Tughlaq"), ("byzantine_ha_mac", "Macedonian")]
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
        src = track_cover(song[3]) if key.startswith("c_") else os.path.join(ASSETS, "assets", "portraits", key + ".jpg")
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
        p = os.path.join(ASSETS, "assets", "flags", civ + ".png")
        if not os.path.exists(p): p = os.path.join(ASSETS, "assets", "flags", "_unknown.png")
        try: im = Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)
        except Exception:
            im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(im).rounded_rectangle([0, 0, W - 1, H - 1], 3, fill="#555555")
        ph = ImageTk.PhotoImage(im, master=self.m); self.cache[k] = ph; return ph
def default_pool(base_cfg, civ):
    bi = base_cfg.get("boss_intro") or {}
    return list((bi.get("pools") or {}).get(civ) or bi.get("default") or [])
SW_W, SW_H = 44, 24                                   # one switch size app-wide (panel toggle default)
def pool_editor(parent, user, save):
    """Tier-list style editor. user: the panel's settings dict (shared); save(): persist + refresh panel."""
    if not single_window("editor", "Age Intros"): return None
    import tkinter as tk
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", line="#2e2e2e", dis="#4a4a4a")
    win = tk.Toplevel(parent); dark_window(win, C["bg"]); win.title("AoE4 Spotify"); win.resizable(False, False)
    win.bind("<Destroy>", lambda e: release_window("editor") if e.widget is win else None, add="+")
    S = win.winfo_fpixels("1i") / 96.0
    W, H, LT, RH, GAP = 600, 720, 196, 40, 4
    CR = 14                                            # civ-row chip radius
    BOT = H - 12; STEP = RH + GAP
    cv = tk.Canvas(win, width=int(W * S), height=int(H * S), bg=C["bg"], highlightthickness=0); cv.pack()
    art = Art(win, S)
    from PIL import Image, ImageDraw, ImageTk
    imgs = {}
    def rr_img(w, h, r, fill, outline=None, width=1.5):
        k = (w, h, r, fill, outline, width)
        if k not in imgs:
            Q = 4; Wp, Hp = max(1, int(round(w * S))), max(1, int(round(h * S)))
            im = Image.new("RGBA", (Wp * Q, Hp * Q), (0, 0, 0, 0))
            ImageDraw.Draw(im).rounded_rectangle([0, 0, Wp * Q - 1, Hp * Q - 1], r * S * Q, fill=fill, outline=outline,
                                                 width=int(width * S * Q) if outline else 0)
            imgs[k] = ImageTk.PhotoImage(im.resize((Wp, Hp), Image.LANCZOS), master=win)
        return imgs[k]
    def rr(x0, y0, x1, y1, r, fill, outline=None, width=1.5, tags=None):
        cv.create_image(x0 * S, y0 * S, anchor="nw", image=rr_img(x1 - x0, y1 - y0, r, fill, outline, width), tags=tags)
    def text(x, y, s, sz, c=None, b=False, anchor="w", tags=None):
        cv.create_text(x * S, y * S, text=s, fill=c or C["tx"], anchor=anchor, font=("Segoe UI", -int(sz * S), "bold" if b else "normal"), tags=tags)
    def undo_glyph(cx, cy, c):
        k = ("undo", c)
        if k not in imgs:
            Q = 4; Z = int(18 * S); im = Image.new("RGBA", (Z * Q, Z * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im); m = Z * Q
            lw = max(2, int(2 * S * Q)); d.arc([m*.2, m*.2, m*.86, m*.86], 200, 470, fill=c, width=lw)
            d.polygon([(m*.06, m*.4), (m*.38, m*.4), (m*.2, m*.64)], fill=c)
            imgs[k] = ImageTk.PhotoImage(im.resize((Z, Z), Image.LANCZOS), master=win)
        cv.create_image(cx * S, cy * S, image=imgs[k])
    base = load_config(user=False)
    _bi = base.get("boss_intro") or {}
    if migrate_intros_v2(user, {**(_bi.get("pools") or {}), "__default__": _bi.get("default") or []}): save()   # v2 per-age lists
    load_custom_songs(user)
    if normalize_pools(user): save()                                   # same songs -> same chip order
    ed = {"age": "imperial", "page": "overview"}            # page: "overview" or the age being edited
    def ages_on(): return {a_: build_intros(base, user)[a_]["enabled"] for a_ in INTRO_AGES}
    def pools(age=None):
        age = age or ed["age"]; bp = (user.get("intro_pools") or {}).get(age) or {}
        if age == "imperial": return {c: song_sorted(bp[c] if c in bp else default_pool(base, c)) for c, _ in CIV_LIST}
        return {c: song_sorted(bp.get(c) or []) for c, _ in CIV_LIST}          # other ages: blank unless you add songs
    def row_default(civ): return default_pool(base, civ) if ed["age"] == "imperial" else []
    def age_custom(age=None):                          # anything to reset on this age?
        age = age or ed["age"]; return bool((user.get("intro_pools") or {}).get(age))
    st = {"sc": 0, "hov": None, "drag": None, "ghost": None, "drop": None, "press": None, "msg": None}
    max_sc = lambda: max(0, len(CIV_LIST) * STEP - GAP - (BOT - LT))
    def row_y(i): return LT + i * STEP - st["sc"]
    NB = len(BUILTIN_SONGS)
    def _ysp():
        m = len(SONGS) - NB; return min(50.0, 100.0 / max(1, m))
    def tray_xy(i):                                    # OCTOPATH group | divider | YOURS group (+ the '+' chip)
        if i < NB: return 53 + i * 48, 137
        return 438 + tray_rad(NB) + 2 + (i - NB) * _ysp(), 137      # left edge of the first chip under the YOURS label
    def tray_rad(i): return 19 if i < NB else max(9.0, min(19.0, _ysp() * 0.45))
    def tray_r(): return 19
    def chip_xy(i, j): return 205 + j * 34, row_y(i) + RH / 2
    def _bp(p):
        if ed["age"] != "imperial": return {c: song_sorted(v) for c, v in p.items() if v}
        return {c: song_sorted(v) for c, v in p.items() if song_sorted(v) != song_sorted(default_pool(base, c))}
    def snap():                                         # everything the editor can change (all ages)
        return json.loads(json.dumps({k: user.get(k) for k in ("intro_pools", "intro_ages", "custom_songs", "intro_preset")}))
    hist = {"cur": snap(), "undo": [], "redo": []}     # Ctrl+Z / Ctrl+Y history for this editor session (all tabs)
    def _apply(sn):
        for k, v in sn.items():
            if v: user[k] = json.loads(json.dumps(v))
            else: user.pop(k, None)
        load_custom_songs(user); normalize_pools(user); save()
    def age_empty(age): return not any(pools(age).values())
    def record():
        for a_ in INTRO_AGES:                          # an age with no songs at all can't be on (same undo step)
            if age_empty(a_) and ages_on()[a_]:
                ia = dict(user.get("intro_ages") or {}); ia[a_] = False; user["intro_ages"] = ia
        sn = snap()
        if sn != hist["cur"]:
            hist["undo"].append(hist["cur"]); hist["redo"].clear(); hist["cur"] = sn
            del hist["undo"][:-500]
        _apply(sn)
    def commit(p):
        ip = dict(user.get("intro_pools") or {}); bp = _bp(p)
        if bp: ip[ed["age"]] = bp
        else: ip.pop(ed["age"], None)
        if ip: user["intro_pools"] = ip
        else: user.pop("intro_pools", None)
        record()
    def set_age_on(a_, on):
        if on and age_empty(a_): return                # greyed out until the age has a song
        ia = dict(user.get("intro_ages") or {}); ia[a_] = bool(on); user["intro_ages"] = ia; record()
    def add_custom(uri, name, artist): add_customs([(uri, name, artist)])
    def add_customs(items):                            # several songs = one undo step
        items = [t for t in items if t[0] not in SONG_BY_URI or t[0] in {c.get("uri") for c in (user.get("custom_songs") or [])}]
        if not items: return 0
        new = {t[0] for t in items}
        cs = [c for c in (user.get("custom_songs") or []) if c.get("uri") not in new]
        cs += [{"uri": u, "name": n, "artist": a} for u, n, a in items]; user["custom_songs"] = cs; record(); draw()
        return len(items)
    uiq = []                                        # worker threads hand UI work to the Tk thread
    ui = uiq.append
    def uipump():
        while uiq:
            try: uiq.pop(0)()
            except Exception as ex: log('UI task: %r' % ex)
        try: win.after(30, uipump)
        except Exception: pass
    win.after(30, uipump)
    # ---- drag songs in from the Spotify app (OLE text drop on the editor window)
    def drop_text(data):
        uris = [u for u in parse_tracks(data) if u not in SONG_BY_URI]
        if not parse_tracks(data): toast("Drop Spotify songs here"); return
        if not uris: toast("Already in YOURS"); return
        toast("Adding\u2026")
        def go():
            try:
                sp = Spotify(load_config()); got = fetch_tracks(sp, uris) if sp.tok else "login"
            except Exception as ex: log("Drop songs: %r" % ex); got = None
            def done():
                if got == "login": toast("Log in to Spotify first")
                elif not got: toast("Couldn't find those songs")
                else:
                    n = add_customs(got); toast("Added %d song%s" % (n, "" if n == 1 else "s"))
            try: ui(done)
            except Exception: pass
        threading.Thread(target=go, daemon=True).start()
    def drop_over(on):
        if bool(st.get("dropover")) != on: st["dropover"] = on; draw()
    try:
        from tkinterdnd2 import TkinterDnD, DND_TEXT
        TkinterDnD._require(win); cv.drop_target_register(DND_TEXT)
        cv.dnd_bind("<<DropEnter>>", lambda e: (drop_over(True), "copy")[1])
        cv.dnd_bind("<<DropPosition>>", lambda e: "copy")
        cv.dnd_bind("<<DropLeave>>", lambda e: (drop_over(False), "copy")[1])
        cv.dnd_bind("<<Drop>>", lambda e: (drop_over(False), drop_text(e.data), "copy")[2])
        st["dnd"] = True
    except Exception as ex: log("Drag-in from Spotify unavailable: %r" % ex); st["dnd"] = False
    win._drop = (drop_text, drop_over)                 # (tests)
    def remove_custom(uri):
        user["custom_songs"] = [c for c in (user.get("custom_songs") or []) if c.get("uri") != uri]
        ip = user.get("intro_pools") or {}
        for a_ in list(ip):
            for civ in list(ip[a_]):
                ip[a_][civ] = [u_ for u_ in ip[a_][civ] if u_ != uri]
                if not ip[a_][civ] and a_ != "imperial": ip[a_].pop(civ)   # Imperial: [] = emptied (not the default)
        record(); draw()
    def undo_redo(back):
        src, dst = (hist["undo"], hist["redo"]) if back else (hist["redo"], hist["undo"])
        if not src or st["drag"]: return "break"
        dst.append(hist["cur"]); hist["cur"] = src.pop(); _apply(hist["cur"]); st["msg"] = None; draw()
        return "break"
    def open_page(page):
        ed["page"] = page
        if page != "overview": ed["age"] = page
        st["sc"] = 0; st["hov"] = None; draw()
        try:                                           # re-evaluate hover/cursor for the new page right away
            px, py = cv.winfo_pointerx() - cv.winfo_rootx(), cv.winfo_pointery() - cv.winfo_rooty()
            h = hit(px / S, py / S) if 0 <= px < cv.winfo_width() and 0 <= py < cv.winfo_height() else None
        except Exception: h = None
        set_hover(h)
    CARD_Y = lambda k: 132 + k * 136
    # ---- presets (overview bar)
    def cur_preset():
        n = user.get("intro_preset") or DEFAULT_PRESET_NAME
        return next((p for p in user_presets(user) if p["name"] == n), None)
    def dirty():
        p = cur_preset(); return p is None or preset_key(user, p) != preset_key(user)
    def switch_preset(name):
        p = next((p for p in user_presets(user) if p["name"] == name), None)
        if not p: return
        apply_preset(user, p); st["menu"] = None; record(); fetch_missing_covers(); draw()
    def save_preset(name=None):                        # name=None: overwrite the current one
        ps = [p for p in (user.get("intro_presets") or []) if isinstance(p, dict)]
        if name is None:
            cur = cur_preset()
            if not cur or cur.get("builtin"): return
            name = cur["name"]; ps = [p for p in ps if p.get("name") != name]
        else: name = unique_preset_name(user, name)
        ps.append(preset_from_user(user, name)); user["intro_presets"] = ps; user["intro_preset"] = name
        hist["cur"] = snap(); _apply(hist["cur"]); st["menu"] = None; draw()
    def share():
        p = preset_from_user(user, (cur_preset() or {}).get("name") or user.get("intro_preset") or "Shared")
        code = encode_preset(p); win.clipboard_clear(); win.clipboard_append(code)
        try: win.update()
        except Exception: pass
        win._last_code = code; toast("Code copied")
    def toast(msg):
        st["toast"] = msg
        if st.get("toastjob"): win.after_cancel(st["toastjob"])
        def clr(): st["toast"] = None; st["toastjob"] = None; draw()
        st["toastjob"] = win.after(1800, clr); draw()
    def import_preset(p):
        p = dict(p); p["name"] = unique_preset_name(user, p["name"]); p.pop("builtin", None)
        user["intro_presets"] = [q for q in (user.get("intro_presets") or [])] + [p]
        apply_preset(user, p); record(); fetch_missing_covers(); draw(); toast("Imported")
        return p["name"]
    def fetch_missing_covers():                        # imported songs: covers arrive in the background
        miss = [c["uri"] for c in (user.get("custom_songs") or []) if not os.path.exists(track_cover(c["uri"]))]
        if not miss: return
        def go():
            try:
                sp = Spotify(load_config())
                if not sp.tok: return
                for u_ in miss: fetch_track(sp, u_)
            except Exception as ex: log("Covers: %r" % ex); return
            ui(lambda: (art.cache.clear(), draw()))           # Tk only on the UI thread
        threading.Thread(target=go, daemon=True).start()
    def name_dialog(title, init, cb):
        d = tk.Toplevel(win); dark_window(d, C["card"]); d.title("AoE4 Spotify"); d.resizable(False, False); d.transient(win)
        tk.Label(d, text=title, bg=C["card"], fg=C["tx"], font=("Segoe UI", 11, "bold")).pack(padx=16, pady=(14, 6), anchor="w")
        e_ = tk.Entry(d, width=32, bg="#2a2a2a", fg=C["tx"], insertbackground=C["tx"], relief="flat", font=("Segoe UI", 10)); e_.pack(padx=16, ipady=5)
        e_.insert(0, init); e_.select_range(0, "end")
        def ok(*_):
            v = e_.get().strip()
            if v: d.destroy(); cb(v)
        tk.Button(d, text="Save", command=ok, bg=C["acc"], fg="#121212", relief="flat", font=("Segoe UI", 10, "bold"), padx=14).pack(padx=16, pady=(10, 14), anchor="e")
        e_.bind("<Return>", ok); d.bind("<Escape>", lambda e: d.destroy())
        reveal(d, over=win); e_.focus_set(); win._name = (d, e_, ok); return "break"
    def import_dialog():
        d = tk.Toplevel(win); dark_window(d, "#1e1e1e"); d.title("AoE4 Spotify"); d.resizable(False, False); d.transient(win)
        DW, DH = 480, 360; dc = tk.Canvas(d, width=int(DW * S), height=int(DH * S), bg="#1e1e1e", highlightthickness=0); dc.pack()
        e_ = tk.Entry(d, bg="#141414", fg="#c8c8c8", insertbackground=C["tx"], relief="flat", font=("Segoe UI", 10),
                      highlightthickness=max(1, int(S)), highlightbackground="#3e3e3e", highlightcolor=C["acc"])
        res = {"p": None, "err": None, "hov": None}; dimg = []
        def drr(x0, y0, x1, y1, r, fill, outline=None, width=1.5):
            dc.create_image(x0 * S, y0 * S, anchor="nw", image=rr_img(x1 - x0, y1 - y0, r, fill, outline, width), tags="g")
        def dtext(x, y, s_, sz, c=None, b=False, anchor="w"):
            dc.create_text(x * S, y * S, text=s_, fill=c or C["tx"], anchor=anchor, font=("Segoe UI", -int(sz * S), "bold" if b else "normal"), tags="g")
        def ddraw():
            dc.delete("g"); dimg.clear()
            if not dc.find_withtag("entry"): dc.create_window(24 * S, 66 * S, anchor="nw", width=int(432 * S), height=int(40 * S), window=e_, tags="entry")
            dc.create_image(38 * S, 36 * S, image=art.disc(30, "#1e3c28", outline=C["acc"], ow=1.5), tags="g"); dc.create_image(38 * S, 36 * S, image=bar_icon("import", C["acc"]), tags="g")
            dtext(62, 36, "Import", 17, b=True); dtext(452, 34, "Ãƒâ€”", 20, C["tx"] if res["hov"] == "x" else C["mu"], anchor="center")
            drr(24, 126, 456, 290, 14, "#262626")
            p, err = res["p"], res["err"]
            if p:
                for j, u_ in enumerate(preset_songs(base, p)[:3]):
                    sg = SONG_BY_URI.get(u_) or next(((None, c_["name"]) for c_ in p["custom"] if c_["uri"] == u_), None)
                    key = sg[0] if sg and sg[0] else None
                    if key: dc.create_image((56 + j * 20) * S, 158 * S, image=art.chip(key, 15), tags="g")
                    else: dc.create_image((56 + j * 20) * S, 158 * S, image=art.plus(15), tags="g")
                dtext(130, 150, p["name"], 16, b=True); dtext(130, 171, "from code", 10, C["mu"])
                cnt = preset_counts(base, p); on = {a_: bool(p["ages"].get(a_, a_ == "imperial")) for a_ in INTRO_AGES}
                for k_, a_ in enumerate(INTRO_AGES):
                    x = 40 + k_ * 102
                    dc.create_image((x + 15) * S, 219 * S, image=art.disc(30, "#1e3c28" if on[a_] and cnt[a_] else "#2c2c2c",
                                    ("I", "II", "III", "IV")[k_], C["acc"] if on[a_] and cnt[a_] else C["mu"], 11), tags="g")
                    dtext(x + 38, 212, str(cnt[a_]), 14, b=True); dtext(x + 38, 228, "civs", 9, C["mu"])
                dc.create_image(55 * S, 263 * S, image=art.plus(13), tags="g")
                dtext(78, 256, str(len(p["custom"])), 14, b=True); dtext(78, 272, "custom", 9, C["mu"])
                dc.create_line(*[v * S for v in (382, 263, 387, 268, 396, 257)], fill=C["acc"], width=max(1, 2.2 * S), capstyle="round", joinstyle="round", tags="g")
                dtext(404, 263, "Valid", 11, C["acc"], True)
            elif err:
                dc.create_image(240 * S, 186 * S, image=art.disc(34, "#3c1e1e", "!", "#e5534b", 17), tags="g")
                dtext(240, 228, err, 12, "#e5534b", True, "center")
            else:
                dtext(240, 208, "Paste a code someone shared with you", 11, C["mu"], anchor="center")
            drr(24, 306, 190, 346, 20, "#383838" if res["hov"] == "cancel" else "#2a2a2a"); dtext(107, 326, "Cancel", 13, b=True, anchor="center")
            gc = (C["acc"] if res["hov"] != "ok" else "#3be477") if p else "#24412e"
            drr(202, 306, 456, 346, 20, gc); dtext(329, 326, "Import as preset", 13, "#0a0a0a" if p else "#5f7a68", True, "center")
        def check(*_):
            v = e_.get().strip(); res["p"], res["err"] = decode_preset(v) if v else (None, None); ddraw()
        def dhit(e):
            x, y = e.x / S, e.y / S
            if 438 <= x <= 466 and 20 <= y <= 50: return "x"
            if 306 <= y <= 346: return "cancel" if 24 <= x <= 190 else ("ok" if 202 <= x <= 456 else None)
        def dmove(e):
            h = dhit(e)
            if h != res["hov"]: res["hov"] = h; dc.config(cursor="hand2" if h and (h != "ok" or res["p"]) else ""); ddraw()
        def go_import():
            if res["p"]: d.destroy(); import_preset(res["p"])
        def dclick(e):
            h = dhit(e)
            if h in ("x", "cancel"): d.destroy()
            elif h == "ok": go_import()
        dc.bind("<Motion>", dmove); dc.bind("<ButtonRelease-1>", dclick)
        e_.bind("<KeyRelease>", check); e_.bind("<<Paste>>", lambda e: d.after(1, check)); e_.bind("<Return>", lambda e: go_import())
        d.bind("<Escape>", lambda e: d.destroy())
        try:
            clip = win.clipboard_get()
            if isinstance(clip, str) and clip.strip().startswith("AOE4S"): e_.insert(0, clip.strip())
        except Exception: pass
        check(); reveal(d, over=win); e_.focus_set(); win._imp = (d, e_, res, go_import, check)
        return "break"
    BAR_Y = 92
    def add_dialog():
        """Search Spotify, add what's playing, or paste a link. Clicking a result adds it."""
        D = dict(bg=C["card"], row="#2a2a2a", fld="#232323", tx=C["tx"], mu=C["mu"], acc=C["acc"])
        d = tk.Toplevel(win); dark_window(d, D["bg"]); d.title("AoE4 Spotify"); d.resizable(False, False); d.transient(win)
        Wd, RHd, NR = 400, 52, 6
        top = tk.Frame(d, bg=D["bg"]); top.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(top, text="Add a song", bg=D["bg"], fg=D["tx"], font=("Segoe UI", 12, "bold")).pack(side="left")
        fr = tk.Frame(d, bg=D["fld"], highlightthickness=1, highlightbackground="#3a3a3a", highlightcolor=D["acc"]); fr.pack(fill="x", padx=16)
        tk.Label(fr, text="\u2315", bg=D["fld"], fg=D["mu"], font=("Segoe UI Symbol", 12)).pack(side="left", padx=(8, 0))
        e_ = tk.Entry(fr, bg=D["fld"], fg=D["tx"], insertbackground=D["tx"], relief="flat", font=("Segoe UI", 11), width=36)
        e_.pack(side="left", fill="x", expand=True, ipady=7, padx=(4, 8))
        ph = tk.Label(fr, text="Search Spotify or paste a song link", bg=D["fld"], fg="#6f6f6f", font=("Segoe UI", 11))
        ph.place(x=30, rely=0.5, anchor="w"); ph.bind("<Button-1>", lambda e: e_.focus_set())
        np_ = tk.Label(d, text="\u266b  Add what's playing", bg=D["row"], fg=D["tx"], font=("Segoe UI", 10, "bold"), padx=12, pady=6, cursor="hand2")
        np_.pack(anchor="w", padx=16, pady=(10, 6))
        np_.bind("<Enter>", lambda e: np_.config(bg="#333333")); np_.bind("<Leave>", lambda e: np_.config(bg=D["row"]))
        rc = tk.Canvas(d, width=Wd * S, height=NR * RHd * S, bg=D["bg"], highlightthickness=0); rc.pack(padx=16 - 8, pady=(0, 4))
        msg = tk.Label(d, text="", bg=D["bg"], fg=D["mu"], font=("Segoe UI", 9)); msg.pack(anchor="w", padx=16, pady=(0, 12))
        R = {"items": [], "hov": None, "job": None, "seq": 0, "thumbs": {}, "busy": False}
        def say(t, err=False): msg.config(text=t, fg="#e5534b" if err else D["mu"])
        def thumb(item):
            u = item["uri"]
            if u in R["thumbs"]: return R["thumbs"][u]
            return None
        def paint():
            rc.delete("all")
            have = {c.get("uri") for c in (user.get("custom_songs") or [])} | set(SONG_BY_URI)
            for k, it in enumerate(R["items"][:NR]):
                y0 = k * RHd; added = it["uri"] in have
                if R["hov"] == k and not added: rc.create_image(0, y0 * S, anchor="nw", image=rr_img(Wd, RHd - 4, 10, D["row"]))
                im = thumb(it)
                if im: rc.create_image((8 + 20) * S, (y0 + 24) * S, image=im)
                else: rc.create_image(8 * S, (y0 + 4) * S, anchor="nw", image=rr_img(40, 40, 8, "#333333"))
                name = it.get("name", ""); art_ = ", ".join(a_.get("name", "") for a_ in (it.get("artists") or [])[:2])
                rc.create_text(58 * S, (y0 + 16) * S, text=name[:44], anchor="w", fill=D["mu"] if added else D["tx"], font=("Segoe UI", -int(12 * S), "bold"))
                rc.create_text(58 * S, (y0 + 33) * S, text=art_[:52], anchor="w", fill=D["mu"], font=("Segoe UI", -int(10.5 * S)))
                if added: rc.create_text((Wd - 12) * S, (y0 + 24) * S, text="\u2713 Added", anchor="e", fill=D["acc"], font=("Segoe UI", -int(10 * S), "bold"))
                elif R["hov"] == k: rc.create_text((Wd - 12) * S, (y0 + 24) * S, text="+ Add", anchor="e", fill=D["acc"], font=("Segoe UI", -int(10 * S), "bold"))
        def load_thumbs(items, seq):
            from PIL import Image, ImageDraw
            import io
            for it in items[:NR]:
                if it["uri"] in R["thumbs"] or seq != R["seq"]: continue
                url = pick_image((it.get("album") or {}).get("images"), 64)
                try: im = Image.open(io.BytesIO(http_get(url))).convert("RGB") if url else None
                except Exception: im = None
                if im is None: continue
                Z = int(40 * S); Q = 4; im = im.resize((Z * Q, Z * Q), Image.LANCZOS)
                m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, Z * Q - 1, Z * Q - 1], 8 * S * Q, fill=255)
                out = Image.new("RGBA", im.size, (0, 0, 0, 0)); out.paste(im, (0, 0), m); out = out.resize((Z, Z), Image.LANCZOS)
                def put(u=it["uri"], o=out):
                    try: R["thumbs"][u] = ImageTk.PhotoImage(o, master=d); paint()
                    except Exception: pass
                try: ui(put)
                except Exception: return
        def sp_():
            sp = Spotify(load_config())
            return sp if sp.tok else None
        def show(items, seq):
            if seq != R["seq"]: return
            R["items"] = items or []; R["hov"] = None; paint()
            if items is None: say("Couldn't search (offline?)", True)
            elif not items: say("No songs found")
            else: say("Click a song to add it")
            if items: threading.Thread(target=load_thumbs, args=(items, seq), daemon=True).start()
        def search(q):
            R["seq"] += 1; seq = R["seq"]; say("Searching\u2026")
            def go():
                try:
                    sp = sp_(); res = search_tracks(sp, q) if sp else "login"
                except Exception as ex: log("Search: %r" % ex); res = None
                def done():
                    if res == "login": say("Log in to Spotify in AoE4 Spotify first", True)
                    else: show(res, seq)
                try: ui(done)
                except Exception: pass
            threading.Thread(target=go, daemon=True).start()
        def add_items(objs, close=False):
            got = [store_track(o) for o in objs]          # (cover download happens on a worker)
            def done():
                n = add_customs(got); paint()
                say("Added \u2713" if n else "Already in YOURS")
                if close and n:
                    try: d.destroy()
                    except Exception: pass
            try: ui(done)
            except Exception: pass
        def add_links(uris):
            say("Looking it up\u2026")
            def go():
                try:
                    sp = sp_(); got = fetch_tracks(sp, uris) if sp else "login"
                except Exception as ex: log("Add song: %r" % ex); got = None
                def done():
                    if got == "login": say("Log in to Spotify in AoE4 Spotify first", True)
                    elif not got: say("Couldn't find that song (offline?)", True)
                    else:
                        n = add_customs(got); say("Added \u2713" if n else "Already in YOURS")
                        if n: d.destroy()
                try: ui(done)
                except Exception: pass
            threading.Thread(target=go, daemon=True).start()
        def on_key(*_):
            t = e_.get().strip(); ph.place_forget() if t else ph.place(x=30, rely=0.5, anchor="w")
            if R["job"]: d.after_cancel(R["job"]); R["job"] = None
            if not t: R["seq"] += 1; R["items"] = []; paint(); say(""); return
            uris = parse_tracks(t)
            if uris:
                new = [u for u in uris if u not in SONG_BY_URI]
                if not new: say("Already in YOURS"); return
                say("Press Enter to add" + (" %d songs" % len(new) if len(new) > 1 else "")); return
            R["job"] = d.after(350, lambda: search(t))      # debounced
        def ok(*_):
            t = e_.get().strip(); uris = parse_tracks(t)
            if uris:
                new = [u for u in uris if u not in SONG_BY_URI]
                if new: add_links(new)
                else: say("Already in YOURS")
            elif t:
                if R["items"]: threading.Thread(target=add_items, args=([R["items"][0]],), daemon=True).start()
                else: search(t)
            else: say("Type a song name or paste a Spotify song link", True)
        def what_playing(*_):
            say("Checking Spotify\u2026")
            def go():
                try:
                    sp = sp_(); it = now_playing(sp) if sp else "login"
                except Exception as ex: log("Now playing: %r" % ex); it = None
                def done():
                    if it == "login": say("Log in to Spotify in AoE4 Spotify first", True)
                    elif not it: say("Nothing is playing on Spotify", True)
                    elif it["uri"] in SONG_BY_URI: say("\u201c%s\u201d is already in YOURS" % it.get("name", ""))
                    else: threading.Thread(target=add_items, args=([it], True), daemon=True).start()
                try: ui(done)
                except Exception: pass
            threading.Thread(target=go, daemon=True).start()
        def row_at(ev):
            k = int(ev.y / S // RHd)
            return k if 0 <= k < min(NR, len(R["items"])) else None
        def on_motion(ev):
            k = row_at(ev)
            if k != R["hov"]: R["hov"] = k; rc.config(cursor="hand2" if k is not None else ""); paint()
        def on_click(ev):
            k = row_at(ev)
            if k is None: return
            it = R["items"][k]
            if it["uri"] in SONG_BY_URI: return
            threading.Thread(target=add_items, args=([it],), daemon=True).start()
        rc.bind("<Motion>", on_motion); rc.bind("<Leave>", lambda e: (R.update(hov=None), rc.config(cursor=""), paint()))
        rc.bind("<ButtonRelease-1>", on_click); np_.bind("<Button-1>", what_playing)
        e_.bind("<KeyRelease>", on_key); e_.bind("<<Paste>>", lambda e: d.after(1, on_key))
        e_.bind("<Return>", ok); d.bind("<Escape>", lambda e: d.destroy())
        reveal(d, over=win); e_.focus_set()
        win._add = (d, e_, ok, msg, {"R": R, "on_key": on_key, "search": search, "what_playing": what_playing, "click_row": lambda k: on_click(type("E", (), {"y": (k * RHd + 10) * S})()), "paint": paint})   # (tests)
        return "break"
    win.bind("<Control-z>", lambda e: undo_redo(True)); win.bind("<Control-Z>", lambda e: undo_redo(False))   # Ctrl+Shift+Z
    win.bind("<Control-y>", lambda e: undo_redo(False)); win.bind("<Control-Y>", lambda e: undo_redo(False))
    win.bind("<Control-Shift-Z>", lambda e: undo_redo(False)); win.bind("<Control-Shift-z>", lambda e: undo_redo(False))
    # ---- hit testing (logical coords)
    SB_X0, SB_X1 = 564, 584                            # scrollbar hit lane (thumb drawn at 572..576, wider when hot)
    def sb_geom():
        ms = max_sc(); vh = BOT - LT
        if not ms: return None
        th = max(28.0, vh * vh / (vh + ms)); ty = LT + (vh - th) * st["sc"] / ms
        return ms, vh, th, ty
    def hit(x, y):
        if ed["page"] != "overview" and SB_X0 <= x <= SB_X1 and LT <= y <= BOT and max_sc(): return ("sb",)
        return _hit(x, y)
    def _hit(x, y):
        if ed["page"] == "overview":
            m = st.get("menu")
            if not m and 18 <= x <= 50 and 42 <= y <= 74: return ("back",)        # same spot as on the age pages
            if m == "presets":
                ps = user_presets(user)
                for i_, p in enumerate(ps):
                    if 26 <= x <= 324 and 126 + i_ * 46 <= y <= 168 + i_ * 46: return ("pm", p["name"])
                yn = 126 + len(ps) * 46
                if 26 <= x <= 324 and yn + 2 <= y <= yn + 32: return ("pnew",)
                if 20 <= x <= 330 and 116 <= y <= yn + 40: return ("menu",)
            elif m == "save":
                if 344 <= x <= 544 and 116 <= y <= 148: return ("ssave",) if not (cur_preset() or {}).get("builtin") else ("menu",)
                if 344 <= x <= 544 and 148 <= y <= 182: return ("snew",)
            if 74 <= y <= 110:
                if 20 <= x <= 330: return ("preset",)
                if 344 <= x <= 436: return ("save",)
                if (x - 494) ** 2 + (y - BAR_Y) ** 2 <= 16 ** 2: return ("share",)
                if (x - 542) ** 2 + (y - BAR_Y) ** 2 <= 16 ** 2: return ("import",)
            if m: return None
            for k, a_ in enumerate(INTRO_AGES):
                y0 = CARD_Y(k)
                if 20 <= x <= 580 and y0 <= y <= y0 + 128:
                    if 486 <= x <= 544 and y0 + 26 <= y <= y0 + 58: return ("swoff", a_, 515, y0 + 58) if age_empty(a_) else ("cardtog", a_)
                    return ("card", a_)
            return None
        for i in range(len(SONGS) + 1):
            cx, cy = tray_xy(i); rt = tray_rad(i) + 2
            if (x - cx) ** 2 + (y - cy) ** 2 <= rt ** 2: return ("tray", i) if i < len(SONGS) else ("plus",)
        if 18 <= x <= 50 and 42 <= y <= 74: return ("back",)
        if 514 <= x <= 566 and 42 <= y <= 74: return ("swoff", ed["age"], 544, 74) if age_empty(ed["age"]) else ("tabtog", ed["age"])
        if age_custom() and 568 <= x <= 590 and 46 <= y <= 70: return ("reset",)
        if LT <= y <= BOT and 20 <= x <= 568:
            i = int((y - LT + st["sc"]) // STEP)
            if 0 <= i < len(CIV_LIST) and row_y(i) <= y <= row_y(i) + RH:
                p = pools()[CIV_LIST[i][0]]; minn = 0
                for j in range(len(p)):
                    cx, cy = chip_xy(i, j)
                    if len(p) > minn and (x - cx - 11) ** 2 + (y - cy + 11) ** 2 <= 7 ** 2 and st["hov"] in (("chip", i, j), ("x", i, j)):
                        return ("x", i, j)
                    if (x - cx) ** 2 + (y - cy) ** 2 <= 16 ** 2: return ("chip", i, j)
                if ed["age"] == "imperial" and 532 <= x <= 562: return ("undo", i)
                return ("row", i)
        return None
    def sw(xr, cy, on, disabled=False):                # same switch as the main panel (SW_W x SW_H, knob SW_H-6); right edge xr, centred on cy
        x0, y0 = xr - SW_W, cy - SW_H / 2
        rr(x0, y0, xr, y0 + SW_H, SW_H / 2, "#2e2e2e" if disabled else (C["acc"] if on else "#3a3a3a"), tags="sw")
        kx = xr - SW_H / 2 if on else x0 + SW_H / 2
        cv.create_image(kx * S, cy * S, image=art.disc(SW_H - 6, "#6a6a6a" if disabled else "#ffffff"), tags=("sw", "swknob"))
    def badge(x, y, age, on, r):
        cv.create_image(x * S, y * S, image=art.disc(2 * r, "#1e3c28" if on else "#2c2c2c",
                        {"dark": "I", "feudal": "II", "castle": "III", "imperial": "IV"}[age], C["acc"] if on else C["mu"], r * 0.62))
    def chev(x, y, c, back=False):
        cv.create_image(x * S, y * S, image=art.chevron(22, c, back)); return
        k = -1 if back else 1
        cv.create_line((x - 4 * k) * S, (y - 7) * S, (x + 3 * k) * S, y * S, (x - 4 * k) * S, (y + 7) * S, fill=c,
                       width=max(1, 2 * S), capstyle="round", joinstyle="round")
    def draw_overview():
        cv.delete("all"); on = ages_on(); hov = st["hov"]
        cv.create_image(34 * S, 58 * S, image=art.chevron(32, C["tx"], True, "#2a2a2a" if (hov or ("",))[0] == "back" else C["card"], w=6, h=12), tags="backbtn")
        cv.create_polygon(*[v * S for v in (66, 67, 66, 51, 73, 58, 78, 47, 83, 58, 90, 51, 90, 67)], fill=C["acc"])   # crown centred like the age badge (78, 58)
        text(102, 58, "Age Intros", 18, b=True, tags="htitle")
        for k, a_ in enumerate(INTRO_AGES):
            y = CARD_Y(k); p = pools(a_); n = sum(1 for v in p.values() if v); hv = hov and hov[1:] == (a_,)
            rr(20, y, 580, y + 128, 18, "#262626" if hv else C["card"], "#464646" if hv else None)
            badge(62, y + 42, a_, on[a_], 24)
            text(100, y + 30, a_.capitalize(), 17, b=True)
            text(100, y + 54, ("%d/%d civs" % (n, len(CIV_LIST))) if n else "Empty", 11, C["acc"] if (n and on[a_]) else C["mu"], True)
            sw(534, y + 42, on[a_], age_empty(a_)); chev(560, y + 42, C["mu"])
            rr(100, y + 82, 330, y + 88, 3, "#323232")
            if n: rr(100, y + 82, 100 + max(6, 230 * n // len(CIV_LIST)), y + 88, 3, C["acc"] if on[a_] else "#5a5a5a")
            allu = [u for u in song_sorted([u for v in p.values() for u in v]) if u in SONG_BY_URI]; used = allu[:5]
            if used:
                for j, u in enumerate(used):
                    cv.create_image((375 + j * 24) * S, (y + 85) * S, image=art.chip(SONG_BY_URI[u][0], 13))
                more = len(allu) - len(used)
                if more > 0:                               # '+X' overflow chip (variant A): same size, overlapping
                    ox = (375 + len(used) * 24) * S
                    cv.create_image(ox, (y + 85) * S, image=art.disc(33, "#262626" if hv else C["card"]))
                    cv.create_image(ox, (y + 85) * S, image=art.disc(30, "#2c2c2c", "+%d" % more, "#dcdcdc", 11, outline="#6e6e6e", ow=2.5))
            else:
                for j in range(3):
                    cv.create_oval((360 + j * 24) * S, (y + 70) * S, (390 + j * 24) * S, (y + 100) * S, outline="#464646", width=max(1, S), fill=C["card"])
        if st.get("toast"):
            import tkinter.font as tkfont
            tw = tkfont.Font(root=win, family="Segoe UI", size=-int(13 * S), weight="bold").measure(st["toast"]) / S + 70
            x0 = W / 2 - tw / 2; rr(x0, H - 46, x0 + tw, H - 8, 19, "#282828", C["acc"], 1.2)
            cv.create_image((x0 + 25) * S, (H - 27) * S, image=art.disc(22, C["acc"]))
            cv.create_line(*[v * S for v in (x0 + 19, H - 27, x0 + 23, H - 23, x0 + 30, H - 31)], fill="#0a0a0a", width=max(1, 2.4 * S), capstyle="round", joinstyle="round")
            text(x0 + 45, H - 27, st["toast"], 13, b=True)
        else: text(W / 2, H - 20, "Click an age to edit", 10, "#5a5a5a", anchor="center")
        draw_bar()
    def chev_down(x, y, c):
        cv.create_line(*[v * S for v in (x - 4, y - 2, x, y + 2, x + 4, y - 2)], fill=c, width=max(1, 2 * S), capstyle="round", joinstyle="round")
    def bar_icon(kind, c):
        k = ("baricon", kind, c)
        if k not in imgs:
            Q = 4; Z = even_px(30, S); im = Image.new("RGBA", (Z * Q, Z * Q), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
            u = Z * Q / 30.0; cx = cy = Z * Q / 2; lw = max(Q, int(round(1.8 * S * Q)))
            P = lambda pts: [(cx + a * u, cy + b * u) for a, b in pts]
            if kind == "save":
                d_.line(P([(0, -7), (0, 3)]), fill=c, width=lw); d_.line(P([(-4, -1), (0, 3), (4, -1)]), fill=c, width=lw, joint="curve")
                d_.line(P([(-7, 2), (-7, 7), (7, 7), (7, 2)]), fill=c, width=lw, joint="curve")
            elif kind == "share":
                for a, b in ((-5, 0), (5, -6), (5, 6)): d_.ellipse([cx + (a - 2.6) * u, cy + (b - 2.6) * u, cx + (a + 2.6) * u, cy + (b + 2.6) * u], fill=c)
                d_.line(P([(-5, 0), (5, -6)]), fill=c, width=max(Q, int(1.5 * S * Q))); d_.line(P([(-5, 0), (5, 6)]), fill=c, width=max(Q, int(1.5 * S * Q)))
            else:
                d_.rounded_rectangle([cx - 6 * u, cy - 6 * u, cx + 6 * u, cy + 8 * u], 2.5 * u, outline=c, width=lw)
                d_.rounded_rectangle([cx - 3 * u, cy - 8 * u, cx + 3 * u, cy - 4 * u], 1.5 * u, fill=c)
            imgs[k] = ImageTk.PhotoImage(im.resize((Z, Z), Image.LANCZOS), master=win)
        return imgs[k]
    def draw_bar():
        hov = st["hov"] or ("",); m = st.get("menu"); y = BAR_Y; cur = cur_preset()
        op = m == "presets" or hov[0] == "preset"
        rr(20, y - 18, 330, y + 18, 18, "#2a2a2a" if op else C["card"], C["acc"] if m == "presets" else "#3e3e3e", 1.2)
        cv.create_image(40 * S, y * S, image=art.disc(12, C["acc"]))
        text(56, y, user.get("intro_preset") or DEFAULT_PRESET_NAME, 13, b=True)
        if dirty(): cv.create_image(292 * S, y * S, image=art.disc(8, "#c8a24a"))
        chev_down(310, y, C["tx"] if op else C["mu"])
        so = m == "save" or hov[0] == "save"
        rr(344, y - 15, 436, y + 15, 15, "#2a2a2a" if so else C["card"], C["acc"] if m == "save" else "#3e3e3e", 1.2)
        cv.create_image(364 * S, y * S, image=bar_icon("save", C["tx"])); text(378, y, "Save", 12, b=True)
        for cx_, kind in ((494, "share"), (542, "import")):
            hv = hov[0] == kind
            cv.create_image(cx_ * S, y * S, image=art.disc(30, "#383838" if hv else "#2a2a2a"))
            cv.create_image(cx_ * S, y * S, image=bar_icon(kind, "#ffffff" if hv else "#cdcdcd"))
        if m == "presets":
            ps = user_presets(user); yb = 126 + len(ps) * 46
            rr(18, 114, 332, yb + 44, 15, "#0c0c0c"); rr(20, 116, 330, yb + 40, 14, "#242424", "#3e3e3e", 1)
            for i_, p in enumerate(ps):
                yy = 126 + i_ * 46; is_cur = p["name"] == (user.get("intro_preset") or DEFAULT_PRESET_NAME)
                if is_cur: rr(26, yy, 324, yy + 42, 10, "#1e3426")
                elif hov == ("pm", p["name"]): rr(26, yy, 324, yy + 42, 10, "#2e2e2e")
                for j, u_ in enumerate(preset_songs(base, p)[:3]):
                    sg = SONG_BY_URI.get(u_)
                    if sg: cv.create_image((48 + j * 16) * S, (yy + 21) * S, image=art.chip(sg[0], 10))
                text(100, yy + 21, p["name"], 13, C["acc"] if is_cur else C["tx"], True)
                cnt = preset_counts(base, p)
                ag = " ".join(r for r, a_ in zip(("I", "II", "III", "IV"), INTRO_AGES) if cnt[a_] and (p.get("ages") or {}).get(a_, a_ == "imperial"))
                text(250, yy + 21, ag, 10, C["mu"], True)
                if is_cur: cv.create_line(*[v * S for v in (300, yy + 21, 305, yy + 26, 314, yy + 15)], fill=C["acc"], width=max(1, 2.2 * S), capstyle="round", joinstyle="round")
            cv.create_line(32 * S, (yb + 1) * S, 318 * S, (yb + 1) * S, fill="#3e3e3e", width=max(1, int(S)))
            nh = hov[0] == "pnew"
            if nh: rr(26, yb + 4, 324, yb + 32, 8, "#2e2e2e")
            text(48, yb + 18, "+", 16, C["acc"], anchor="center"); text(62, yb + 18, "New preset", 12, C["acc"], True)
        elif m == "save":
            rr(342, 114, 546, 186, 13, "#0c0c0c"); rr(344, 116, 544, 184, 12, "#242424", "#3e3e3e", 1)
            cp = cur_preset(); ro = not cp or cp.get("builtin")
            if hov[0] == "ssave" and not ro: rr(348, 120, 540, 148, 8, "#2e2e2e")
            if hov[0] == "snew": rr(348, 152, 540, 180, 8, "#2e2e2e")
            nm = user.get("intro_preset") or DEFAULT_PRESET_NAME
            text(360, 134, ("Save to \u201c%s\u201d" % nm) if len(nm) <= 14 else "Save to this preset", 12, "#5a5a5a" if ro else C["tx"], True)
            text(360, 166, "Save as new\u2026", 12, C["tx"], True)
    def draw():
        if ed["page"] == "overview": draw_overview(); return
        cv.delete("all"); p = pools(); hov = st["hov"]; drag = st["drag"]
        # list (drawn first; header/tray cover what scrolls above)
        for i, (civ, name) in enumerate(CIV_LIST):
            y = row_y(i)
            if y > BOT or y + RH < LT - 60: continue
            drop = st["drop"] == i
            rr(20, y, 568, y + RH, 10, "#1c2a20" if drop else C["card"], C["acc"] if drop else None)
            cv.create_image(32 * S, (y + RH / 2) * S, anchor="w", image=art.flag(civ))
            text(72, y + RH / 2, name, 12, b=True)
            for j, uri in enumerate(p[civ]):
                s = SONG_BY_URI.get(uri)
                if not s: continue
                cx, cy = chip_xy(i, j)
                moving = drag and drag["src"] == ("row", i, j)
                cv.create_image(cx * S, cy * S, image=art.chip(s[0], CR, dim=bool(moving)))
            cy = y + RH / 2
            if drop:
                x = 205 + len(p[civ]) * 34
                cv.create_oval((x - 15) * S, (cy - 15) * S, (x + 15) * S, (cy + 15) * S, outline=C["acc"], width=max(1, int(1.5 * S)))
                text(x, cy, "+", 13, C["acc"], True, "center")
            elif not p[civ]:                               # empty civ: dashed drop slot (+ hint on the first one)
                cv.create_oval(190 * S, (cy - 15) * S, 220 * S, (cy + 15) * S, outline="#4b4b4b", width=max(1, S), dash=(3, 3))
                if i == next((k for k, (c_, _) in enumerate(CIV_LIST) if not p[c_]), -1):
                    text(205, cy, "+", 13, "#6e6e6e", anchor="center"); text(232, cy, "Drag songs here", 10, "#646464")
            if ed["age"] == "imperial" and p[civ] != song_sorted(default_pool(base, civ)):
                undo_glyph(547, cy, C["mu"])
        # scrollbar
        g_ = sb_geom()
        if g_:
            ms, vh, th, ty = g_; act = bool(st.get("sbd")); hot = act or (st["hov"] or ("",))[0] == "sb"
            x0_, x1_ = (571, 577) if hot else (572, 576)
            rr(x0_, LT, x1_, BOT, 3 if hot else 2, "#2a2a2a", tags="sbtrack")
            rr(x0_, ty, x1_, ty + th, 3 if hot else 2, "#9a9a9a" if act else ("#7a7a7a" if hot else "#5a5a5a"), tags="sbthumb")
        # header + tray (opaque, on top of the scrolled list)
        cv.create_rectangle(0, 0, W * S, (LT - 4) * S, fill=C["bg"], outline="", tags="cover")
        cv.create_rectangle(0, BOT * S, W * S, H * S, fill=C["bg"], outline="", tags="cover")
        a_ = ed["age"]; on = ages_on()
        cv.create_image(34 * S, 58 * S, image=art.chevron(32, C["tx"], True, "#2a2a2a" if (st["hov"] or ("",))[0] == "back" else C["card"], w=6, h=12), tags="backbtn")
        badge(78, 58, a_, on[a_], 15); text(102, 58, a_.capitalize(), 18, b=True, tags="htitle")
        sw(562, 58, on[a_], age_empty(a_))
        if age_custom(): undo_glyph(578, 58, C["mu"])
        rr(20, 88, 580, 180, 18, "#1a1a1a", C["line"])
        text(36, 99, "OCTOPATH", 8.5, C["mu"], True)
        if st.get("dropover"):                         # dragging songs in from Spotify
            rr(430, 92, 576, 176, 14, "#16261b", C["acc"], 2); text(438, 99, "DROP TO ADD", 8.5, C["acc"], True)
        else: text(438, 99, "YOURS", 8.5, C["acc"], True)
        cv.create_line(424 * S, 102 * S, 424 * S, 168 * S, fill=C["line"], width=max(1, S))
        for i, s_ in enumerate(SONGS):
            cx, cy = tray_xy(i); tr = tray_rad(i)
            if drag and drag["src"] == ("tray", i):
                cv.create_oval((cx - tr - 3) * S, (cy - tr - 3) * S, (cx + tr + 3) * S, (cy + tr + 3) * S, outline=C["acc"], width=max(1, int(1.5 * S)))
            cv.create_image(cx * S, cy * S, image=art.chip(s_[0], tr))
        cx, cy = tray_xy(len(SONGS)); cv.create_image(cx * S, cy * S, image=art.plus(tray_rad(len(SONGS))))
        # drag ghost
        if drag and drag.get("xy"):
            gx, gy = drag["xy"]; s = SONGS[drag["song"]]
            cv.create_image(gx * S, gy * S, image=art.chip(s[0], 19), tags="ghost")
        overlay()
    # click a chip (no drag) = play that theme on Spotify now; click it again = pause
    pv = {"song": None, "busy": False, "phase": 0, "sp": None, "q": [], "msgjob": None, "env": 0.0, "gsong": None, "gt": 0, "gjob": None,
          "lock": threading.Lock()}
    def _warm():                                       # token + keep-alive connection + device id, before the first click
        try:
            with pv["lock"]:
                if pv["sp"] is None: pv["sp"] = Spotify(load_config())
                sp = pv["sp"]
            if sp.tok and hasattr(sp, "warm"): sp.warm()
        except Exception as e: log("Preview warm-up: %r" % e)
    threading.Thread(target=_warm, daemon=True).start()
    glow_cache = {}
    def hint(msg, x, y):
        st["msg"] = (msg, x, y + 26)
        if pv["msgjob"]: win.after_cancel(pv["msgjob"])
        def clear():
            pv["msgjob"] = None
            if st["msg"] and st["msg"][0] == msg: st["msg"] = None; overlay()
        pv["msgjob"] = win.after(2600, clear); overlay()
    def preview(i, xy):
        if pv["busy"]: return
        action = "pause" if pv["song"] == SONGS[i][0] else "play"
        pv["busy"] = True; pv["xy"] = xy; pv["prev"] = pv["song"]; pv["t_click"] = time.perf_counter()
        pv["song"] = SONGS[i][0] if action == "play" else None          # optimistic: glow reacts on the click
        if action == "play" and pv.get("gsong") != SONGS[i][0]: pv["env"] = 0.0      # new song: one fade-in from 0
        overlay(); glow_kick()
        def go():
            try:
                with pv["lock"]:
                    if pv["sp"] is None: pv["sp"] = Spotify(load_config())
                sp = pv["sp"]
                if not sp.tok: res = "login"
                else: res = bool(sp.preview(SONGS[i][3]) if action == "play" else sp.pause())
            except Exception as e:
                log("Preview failed: %r" % e); res = False
            pv["q"].append((action, i, res))
        threading.Thread(target=go, daemon=True).start()
    def pvpump():
        changed = False
        while pv["q"]:
            action, i, res = pv["q"].pop(0); pv["busy"] = False; changed = True
            pv["t_done"] = time.perf_counter()
            if res == "login": pv["song"] = pv.get("prev"); hint("Log in to Spotify in AoE4 Spotify to preview", *pv["xy"])
            elif action == "play":
                if res: pv["song"] = SONGS[i][0]; log("Preview: %s" % SONGS[i][1])
                else: pv["song"] = pv.get("prev") if pv.get("prev") != SONGS[i][0] else None; hint("Couldn't play - is Spotify (Premium) running?", *pv["xy"])
            else:
                if not res and pv.get("prev"): pv["song"] = pv["prev"]       # pause failed: still playing
                else: pv["song"] = None
        if changed: overlay(); glow_kick()
        try: win.after(30, pvpump)
        except Exception: pass
    def glow_spots(song):
        if ed["page"] == "overview": return []
        spots = [(tray_xy(i), tray_rad(i)) for i, s in enumerate(SONGS) if s[0] == song]
        p = pools()
        for i, (civ, _) in enumerate(CIV_LIST):
            y = row_y(i)
            if y + RH < LT or y > BOT: continue
            for j, uri in enumerate(p[civ]):
                if SONG_BY_URI.get(uri, ("",))[0] == song: spots.append((chip_xy(i, j), CR))
        return spots
    def glow_img(r, ph, env):
        k = (r, ph, env)
        if k not in glow_cache: glow_cache[k] = ImageTk.PhotoImage(render_glow(r, S, ph, env))
        return glow_cache[k]
    def glow_tick():                                   # 'now playing' breathing glow, ~30 fps while active
        pv["gjob"] = None
        if pv["song"] and win_hidden(win): pv["gjob"] = win.after(500, glow_tick); return   # minimized: sleep
        if pv["song"]: pv["gsong"] = pv["song"]
        pv["env"] = min(1.0, pv["env"] + 0.1) if pv["song"] else max(0.0, pv["env"] - 0.1)
        pv["gt"] = (pv["gt"] + 1) % GLOW_N
        try:
            glow_sync()
            if pv["song"] or pv["env"] > 0: pv["gjob"] = win.after(33, glow_tick)
        except Exception as ex: log("Glow: %r" % ex)
    def glow_sync():
        """Place the glow items at their chips' *current* positions. Called by the animation timer and at the
        end of every redraw (scroll, drag, edits), so the glow moves in lockstep with its chip: existing items
        are moved/re-imaged in place (coords + itemconfigure), never left at stale coordinates."""
        items = [it for it in pv.setdefault("gitems", []) if cv.type(it)]   # a full redraw deletes them
        moving = st["drag"] and st["drag"].get("xy") is not None          # a press alone is not a drag: keep the glow
        spots = glow_spots(pv["gsong"]) if (pv["env"] > 0 and not moving and pv.get("gsong")) else []
        for n, ((cx, cy), r) in enumerate(spots):
            img = glow_img(r, pv["gt"], round(pv["env"], 1)); tray = cy < LT - 4
            tags = ("glow",) if tray else ("glow", "glowlist")       # list glows scroll under header/bottom covers
            if n < len(items):
                cv.coords(items[n], cx * S, cy * S); cv.itemconfigure(items[n], image=img, tags=tags)
            else:
                items.append(cv.create_image(cx * S, cy * S, image=img, anchor="center", tags=tags))
        for it in items[len(spots):]: cv.delete(it)
        pv["gitems"] = items[:len(spots)]
        # z-order: each glow sits directly ABOVE its own chip (halo, ring and badge over the chip edge; the
        # face shows through the cut-out), but list glows stay below the header/bottom covers that the
        # list scrolls under. Restacked every redraw and tick; items are never recreated for this.
        for it, ((cx, cy), r) in zip(pv["gitems"], spots):
            under = [i for i in cv.find_overlapping(cx * S, cy * S, cx * S, cy * S)
                     if cv.type(i) == "image" and not set(cv.gettags(i)) & {"glow", "cover", "tip", "ghost"}]
            if under: cv.tag_raise(it, under[-1])
            else: cv.tag_raise(it)
        if cv.find_withtag("ovl"): cv.tag_raise("ovl")             # hover ring, x badge, tooltip: always on top
        if cv.find_withtag("ghost"): cv.tag_raise("ghost")
    def glow_kick():
        if not pv["gjob"]: glow_tick()
    _draw_base = draw
    def draw():                                        # every redraw re-places the glow in the same pass
        _draw_base()
        try: glow_sync()
        except Exception as ex: log("Glow: %r" % ex)
    def playing_marks():
        return                                         # replaced by the glow layer (glow_tick)
        import math
        k = 1.5 + 1.5 * math.sin(pv["phase"] / 24 * 2 * math.pi)            # gentle pulse
        lw = max(1, int(2 * S))
        spots = [(tray_xy(i), 20) for i, s in enumerate(SONGS) if s[0] == pv["song"]]
        p = pools()
        for i, (civ, _) in enumerate(CIV_LIST):
            y = row_y(i)
            if y + RH < LT or y > BOT: continue
            for j, uri in enumerate(p[civ]):
                if SONG_BY_URI.get(uri, ("",))[0] == pv["song"]: spots.append((chip_xy(i, j), 15))
        for (cx, cy), r in spots:
            R = r + 3 + k
            cv.create_oval((cx - R) * S, (cy - R) * S, (cx + R) * S, (cy + R) * S, outline=C["acc"], width=lw)
            bx, by = cx + r * 0.72, cy + r * 0.72                             # small speaker badge
            cv.create_oval((bx - 7) * S, (by - 7) * S, (bx + 7) * S, (by + 7) * S, fill=C["acc"], outline=C["bg"], width=lw)
            text(bx, by - 0.5, "\u266a", 9, "#121212", True, "center")

    def overlay():
        """Hover-only layer (highlights, x badge, tooltip): redrawn alone, so hovering never re-renders the list."""
        cv.delete("ovl"); mark = max(cv.find_all() or (0,)); hov = st["hov"]; drag = st["drag"]
        playing_marks()
        if hov and not drag:
            p = pools()
            if ed["page"] == "overview": pass
            elif hov[0] in ("chip", "x") and len(p[CIV_LIST[hov[1]][0]]) > 0:
                cx, cy = chip_xy(hov[1], hov[2]); xc = C["acc"] if hov[0] == "x" else "#3a3a3a"
                cv.create_image((cx + 11) * S, (cy - 11) * S, image=art.disc(14, xc, fg=C["tx"], cross=2.6, outline=C["bg"], ow=1.5))
            elif hov[0] == "undo" and p[CIV_LIST[hov[1]][0]] != song_sorted(default_pool(base, CIV_LIST[hov[1]][0])):
                y = row_y(hov[1]) + RH / 2
                if LT <= y <= BOT: undo_glyph(547, y, C["tx"])
            elif hov[0] == "reset" and age_custom():
                undo_glyph(578, 58, C["tx"])
            elif hov[0] == "back":
                cv.create_image(34 * S, 58 * S, image=art.chevron(32, C["tx"], True, "#2a2a2a", w=6, h=12))
            elif hov[0] == "plus":                     # brighter '+' instead of a second ring
                cx, cy = tray_xy(len(SONGS)); cv.create_image(cx * S, cy * S, image=art.plus(tray_rad(len(SONGS)), hover=True))
            elif hov[0] == "tray":
                ii = hov[1]; cx, cy = tray_xy(ii); R_ = tray_rad(ii) + 3
                cv.create_oval((cx - R_) * S, (cy - R_) * S, (cx + R_) * S, (cy + R_) * S, outline=C["acc"], width=max(1, int(1.5 * S)))
        tip = st["msg"]                                # status message only (tooltips live in the shared GlassTip)
        if tip:
            tw = msg_font.measure(tip[0]) / S + 20; x0 = min(max(8, tip[1] - tw / 2), W - 8 - tw)
            ty = min(max(8, tip[2]), H_vis() - 32)
            rr(x0, ty, x0 + tw, ty + 24, 12, "#1c3a26", C["acc"], 1)
            text(x0 + tw / 2, ty + 12, tip[0], 10, C["tx"], anchor="center")
        for it in cv.find_all():
            if it > mark: cv.addtag_withtag("ovl", it)
    import tkinter.font as _tkf
    msg_font = _tkf.Font(root=win, family="Segoe UI", size=-int(10 * S))
    def H_vis():
        try: return cv.winfo_height() / S
        except Exception: return 600
    gtip = get_tip(cv)
    def song_tip(h):
        """(key, text, screen rect) for a hovered song cover / disabled switch, else None."""
        if not h or st["drag"]: return None
        if h[0] in ("tray", "chip"):
            p = pools()
            s_ = SONGS[h[1]] if h[0] == "tray" else SONG_BY_URI.get(p[CIV_LIST[h[1]][0]][h[2]])
            if not s_: return None
            cx, cy = tray_xy(h[1]) if h[0] == "tray" else chip_xy(h[1], h[2])
            r = tray_rad(h[1]) if h[0] == "tray" else 15
            if h[0] == "chip" and not (LT <= cy <= BOT): return None
            return (h, "%s \u2014 %s" % (s_[1], s_[2]) if s_[2] else s_[1], (cx - r, cy - r - 3, cx + r, cy + r + 3))
        if h[0] == "swoff": return (h, "Add a song first", (h[2] - 12, h[3] - 30, h[2] + 12, h[3] - 6))
        return None
    def set_hover(h):
        """Hover changed: update the overlay now, show the tooltip after a short delay."""
        OV = ("back", "card", "cardtog", "swoff", "preset", "save", "share", "import", "pm", "pnew", "ssave", "snew")
        redraw = ed["page"] == "overview" and (st["hov"] or ("",))[0] in OV or (h or ("",))[0] in OV
        st["hov"] = h; st["msg"] = None; st["tipok"] = False
        if redraw and ed["page"] == "overview": draw()                 # card hover highlight
        t_ = song_tip(h)
        if t_ and not (st.get("press") and not st.get("released", True)):
            k_, txt, (a0, b0, a1, b1) = t_
            gtip.request(("intro",) + tuple(k_), txt, canvas_rect(cv, (a0 * S, b0 * S, a1 * S, b1 * S)), S, cv)
        else: gtip.hide()
        overlay()
        cur = "hand2" if h and h[0] in ("tray", "chip", "x", "undo", "reset", "plus", "tabtog", "card", "cardtog", "back",
                                        "preset", "save", "share", "import", "pm", "pnew", "ssave", "snew") else ("no" if h and h[0] == "swoff" else "")
        if cv.cget("cursor") != cur: cv.config(cursor=cur)
    def L(e): return e.x / S, e.y / S
    def on_motion(e):
        t0 = time.perf_counter(); h = hit(*L(e))
        if h != st["hov"]:
            sbch = (h == ("sb",)) != (st["hov"] == ("sb",))
            set_hover(h)
            if sbch: draw()                                # scrollbar hover styling lives in the main frame
        st["mt"] = max(st.get("mt", 0), time.perf_counter() - t0)     # slowest motion handler (tests)
    def on_press(e):
        cv.focus_set()                                     # keep keyboard focus here (Ctrl+Z / Ctrl+Y)
        x, y = L(e); h = hit(x, y); st["press"] = (x, y, h); st["released"] = False
        if h == ("sb",):                                   # grab the thumb (track click: jump there, then grab)
            g_ = sb_geom()
            if g_:
                ms, vh, th, ty = g_
                if not (ty <= y <= ty + th): st["sc"] = max(0, min(ms, (y - LT - th / 2) * ms / max(1, vh - th)))
                st["sbd"] = (y, st["sc"]); gtip.hide(fade=False); draw()
            return
        if h and h[0] == "tray": st["drag"] = {"src": h, "song": h[1], "xy": None}
        elif h and h[0] == "chip" and pools()[CIV_LIST[h[1]][0]][h[2]] in SONG_BY_URI:
            uri = pools()[CIV_LIST[h[1]][0]][h[2]]
            st["drag"] = {"src": ("row", h[1], h[2]), "song": [s[3] for s in SONGS].index(uri), "xy": None}
    def on_drag(e):
        if st.get("sbd"):                                  # thumb follows the pointer 1:1
            g_ = sb_geom()
            if g_:
                ms, vh, th, _ = g_; y0, s0 = st["sbd"]; y = L(e)[1]
                sc_ = max(0, min(ms, s0 + (y - y0) * ms / max(1, vh - th)))
                if sc_ != st["sc"]: st["sc"] = sc_; draw()
            return
        d = st["drag"]
        if not d: return
        x, y = L(e); px, py, _ = st["press"]
        if d["xy"] is None and abs(x - px) + abs(y - py) < 4: return       # < 4 px = a click (preview)
        d["xy"] = (x, y)
        if y > BOT - 24 and st["sc"] < max_sc(): st["sc"] = min(max_sc(), st["sc"] + 8)     # auto-scroll while dragging
        elif LT < y < LT + 24 and st["sc"] > 0: st["sc"] = max(0, st["sc"] - 8)
        sc0, drop0 = st["sc"], st["drop"]
        h = hit(x, y); st["drop"] = h[1] if h and h[0] in ("row", "chip", "x", "undo") else None
        if st["drop"] is not None and d["src"][0] == "row" and d["src"][1] == st["drop"]: st["drop"] = None
        if st["drop"] is not None and SONGS[d["song"]][3] in pools()[CIV_LIST[st["drop"]][0]]: st["drop"] = None   # no duplicates
        if st["sc"] == sc0 and st["drop"] == drop0 and cv.find_withtag("ghost"): cv.coords("ghost", x * S, y * S)
        else: draw()
    def on_release(e):
        if st.get("sbd"): st["sbd"] = None; st["released"] = True; st["hov"] = hit(*L(e)); draw(); return
        st["released"] = True; d, st["drag"] = st["drag"], None; drop, st["drop"] = st["drop"], None
        x, y = L(e); h = hit(x, y); p = pools()
        if d and d["xy"] is not None:
            uri = SONGS[d["song"]][3]
            if drop is not None:
                civ = CIV_LIST[drop][0]
                if uri not in p[civ]: p[civ].append(uri)
                if d["src"][0] == "row" and len(p[CIV_LIST[d["src"][1]][0]]) > 1: p[CIV_LIST[d["src"][1]][0]].remove(uri)   # move
                commit(p)
            elif d["src"][0] == "row" and not (h and h[0] in ("row", "chip", "x", "undo") and h[1] == d["src"][1]):
                remove(d["src"][1], d["src"][2])        # dragged out of its row
            st["hov"] = hit(x, y); draw(); return
        ph = st["press"][2] if st["press"] else None
        if d and ph and ph[0] in ("tray", "chip") and h == ph:                 # click on a chip: preview
            preview(d["song"], tray_xy(ph[1]) if ph[0] == "tray" else chip_xy(ph[1], ph[2]))
        elif ed["page"] == "overview" and st.get("menu") and not (h and h[0] in ("pm", "pnew", "ssave", "snew", "menu", "preset", "save")):
            st["menu"] = None                              # click outside an open menu just closes it
        elif h and h[0] == "preset": st["menu"] = None if st.get("menu") == "presets" else "presets"
        elif h and h[0] == "save": st["menu"] = None if st.get("menu") == "save" else "save"
        elif h and h[0] == "pm": switch_preset(h[1]); return
        elif h and h[0] == "pnew": st["menu"] = None; draw(); win.after_idle(lambda: name_dialog("New preset", "My preset", save_preset)); return
        elif h and h[0] == "ssave": save_preset(); toast("Saved"); return
        elif h and h[0] == "snew": st["menu"] = None; draw(); win.after_idle(lambda: name_dialog("Save as new preset", "My preset", save_preset)); return
        elif h and h[0] == "share": share(); return
        elif h and h[0] == "import": win.after_idle(import_dialog)
        elif h and h[0] == "card": open_page(h[1]); return
        elif h and h[0] == "cardtog": set_age_on(h[1], not ages_on()[h[1]])
        elif h and h[0] == "back":
            if ed["page"] == "overview": close_editor()            # overview: back arrow closes the window
            else: open_page("overview")
            return
        elif h and h[0] == "x": remove(h[1], h[2])
        elif h and h[0] == "undo":
            p = pools(); p[CIV_LIST[h[1]][0]] = row_default(CIV_LIST[h[1]][0]); commit(p)
        elif h and h[0] == "reset": commit({c: row_default(c) for c, _ in CIV_LIST})
        elif h and h[0] == "tabtog": set_age_on(h[1], not ages_on()[h[1]])
        elif h and h[0] == "plus": win.after_idle(add_dialog)
        st["hov"] = hit(x, y); draw()
    def remove(i, j):
        p = pools(); civ = CIV_LIST[i][0]
        p[civ].pop(j); commit(p)
    def on_right(e):
        h = hit(*L(e))
        if h and h[0] in ("chip", "x"): remove(h[1], h[2]); st["hov"] = hit(*L(e)); draw()
        elif h and h[0] == "tray" and SONGS[h[1]][0].startswith("c_"):          # your own song: right-click > Remove
            uri = SONGS[h[1]][3]; m = tk.Menu(win, tearoff=0, bg=C["card"], fg=C["tx"], activebackground="#2a2a2a", activeforeground=C["tx"])
            m.add_command(label="Remove song", command=lambda: remove_custom(uri)); win._menu = m
            try: m.tk_popup(e.x_root, e.y_root)
            finally: m.grab_release()
    def on_wheel(e):
        if ed["page"] == "overview": return
        gtip.hide(fade=False)
        st["sc"] = max(0, min(max_sc(), st["sc"] - (e.delta / 120) * 46)); st["hov"] = hit(*L(e)); draw()
    cv.bind("<Motion>", on_motion); cv.bind("<ButtonPress-1>", on_press); cv.bind("<B1-Motion>", on_drag)
    def on_release_guarded(e):                         # a release whose press opened this window (or was elsewhere) does nothing
        if st["press"] is None: st["hov"] = hit(*L(e)); draw(); return
        try: on_release(e)
        finally: st["press"] = None
    cv.bind("<ButtonRelease-1>", on_release_guarded); cv.bind("<Button-3>", on_right); cv.bind("<MouseWheel>", on_wheel)
    def close_editor():                                # any close (back arrow, Esc on overview, title-bar X): panel to front
        try: win.destroy()
        except Exception: pass
        if parent is not None: parent.after(10, lambda: focus_window(parent))
    win.protocol("WM_DELETE_WINDOW", close_editor)
    cv.bind("<Leave>", lambda e: (gtip.hide(), set_hover(None) if not st["drag"] else None))
    win.bind("<Escape>", lambda e: open_page("overview") if ed["page"] != "overview" else (st.update(menu=None), draw()))
    win.bind("<BackSpace>", lambda e: open_page("overview") if ed["page"] != "overview" else None)
    set_app_icon(win)
    draw(); fetch_missing_covers()
    pvpump()
    win._ed = {"record": record, "undo_redo": undo_redo, "pv": pv, "cv": cv, "st": st, "pools": pools, "tray_xy": tray_xy, "chip_xy": chip_xy, "row_y": row_y, "S": S, "draw": draw,
               "ed": ed, "ages_on": ages_on, "add_custom": add_custom, "remove_custom": remove_custom, "add_dialog": add_dialog, "hist": hist, "glow_kick": glow_kick,
               "open_page": open_page, "set_age_on": set_age_on, "tray_rad": tray_rad, "CARD_Y": CARD_Y,
               "switch_preset": switch_preset, "save_preset": save_preset, "share": share, "import_preset": import_preset,
               "import_dialog": import_dialog, "dirty": dirty, "toast": toast}  # tests
    reveal(win, over=parent); note_window("editor", win); win.lift(); win.focus_force()
    return win
GLOW_N = 54                                        # frames per breathing cycle (54 x 33 ms = 1.8 s)
def ink_centre(layer):
    """Shift a glyph layer (RGBA, supersampled) so the centroid of its ink sits on the image centre."""
    from PIL import ImageChops
    al = layer.getchannel("A"); W_, H_ = al.size; data = al.load(); sx = sy = tot = 0
    for y in range(0, H_):
        for x in range(0, W_):
            v = data[x, y]
            if v: sx += x * v; sy += y * v; tot += v
    if not tot: return layer
    dx = int(round((W_ - 1) / 2 - sx / tot)); dy = int(round((H_ - 1) / 2 - sy / tot))
    return ImageChops.offset(layer, dx, dy)
def even_px(logical, S):
    """Pixel size rounded to an EVEN number: Tk centres images at coord - size//2, so even sizes put the
    image centre exactly on the coordinate (odd ones land half a pixel off)."""
    n = int(round(logical * S)); return n + (n % 2)
def chip_px(r, S): n = int(round((2 * r + 4) * S)); return n + (n % 2)   # always even: centred on whole pixels   # chip image size; the glow shares its parity
def render_glow(r, S, phase, env, Q=4, badge=True):
    """One frame of the 'now playing' glow around a round chip of logical radius r (RGBA PIL image).
    Feathered radial halo (opacity ~35%..75%, breathing scale), crisp thin inner ring, tiny equalizer badge."""
    import math
    from PIL import Image, ImageDraw
    t = 0.5 - 0.5 * math.cos(2 * math.pi * phase / GLOW_N)          # ease-in-out sine 0..1..0
    # Same parity as the chip image: Tk centres an image at coord - size//2, so an odd chip with an even
    # glow (or vice versa) lands half a pixel off. D = chip + 2*pad keeps both centres on the same pixel.
    D = chip_px(r, S) + 2 * int(round(16 * S)); B = D * Q; c = B / 2; k = S * Q
    im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    def box(rad):                         # integer, inclusive box symmetric about the image centre (PIL rounds otherwise)
        R = int(round(rad)); C = B // 2; return [C - R, C - R, C + R - 1, C + R - 1]
    g = (29, 185, 84)
    a_max = (0.35 + 0.40 * t) * env
    r0 = r * k; r1 = (r + 9 + 7 * t) * k                             # halo from chip edge out to r1 (breathes)
    steps = 48
    for s in range(steps, -1, -1):                                   # outer -> inner, each ring overwrites
        f = s / steps; rad = r0 + (r1 - r0) * f
        a = a_max * (1 - f) ** 2.2                                   # smooth falloff, no hard edge
        d.ellipse(box(rad), fill=g + (int(255 * a),))
    ri = (r - 0.5) * k; d.ellipse(box(ri), fill=(0, 0, 0, 0))   # keep the portrait clean
    br = 0.25 + 0.35 * t                                              # ring brightness modulation
    rc = tuple(int(g[i] + (255 - g[i]) * br * 0.6) for i in range(3))
    rr_ = (r + 1.6) * k; w = max(1, int(1.4 * k))
    d.ellipse(box(rr_), outline=rc + (int(235 * env),), width=w)
    if not badge: return im.resize((D, D), Image.LANCZOS)
    bx, by, br_ = c + r * 0.86 * k, c + r * 0.86 * k, 6.0 * k       # equalizer badge: small, bottom-right, off the face
    d.ellipse([bx - br_, by - br_, bx + br_, by + br_], fill=(18, 18, 18, int(255 * env)), outline=g + (int(255 * env),), width=max(1, int(1.2 * k)))
    for i in range(3):
        h = (1.8 + 3.6 * (0.5 + 0.5 * math.sin(2 * math.pi * (2 * phase / GLOW_N + i * 0.37) + i))) * k
        x = bx + (i - 1) * 2.6 * k; bw = 0.85 * k
        d.rounded_rectangle([x - bw, by + 2.7 * k - h, x + bw, by + 2.7 * k], bw, fill=g + (int(255 * env),))
    return im.resize((D, D), Image.LANCZOS)
def panel():
    if not single_window("panel", "AoE4 Spotify"): return
    import tkinter as tk, subprocess, webbrowser as wb
    try: import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", off="#3a3a3a", line="#2a2a2a",
             ib="#2a2a2a", idle="#8a8a8a", red="#e5484d", acc="#1DB954", dis="#555555", org="#f0a030")
    root = tk.Tk(); dark_window(root, C["bg"]); root.title("AoE4 Spotify"); root.resizable(False, False)
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
    G0, GREY_ACC, CORAL, CORAL_TX = "#1DB954", "#6e6e6e", "#e5675f", "#f0d6d4"
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
    def open_github():
        try: webbrowser.open(GITHUB_URL)
        except Exception as e: log("Open GitHub: %r" % e)
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
            hov["row"] = row
        hl = next((int(t[3:]) for t in tags if t.startswith("opn") and t[3:].isdigit()), None)
        if hl != hov["hl"]:
            if isinstance(hov["hl"], int): cv.itemconfigure("hl%d" % hov["hl"], state="hidden")
            if hl is not None: cv.itemconfigure("hl%d" % hl, state="normal")
            hov["hl"] = hl
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
    def PL_Y(i): return 214 + i * 46                       # age row top
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
    state = {"spotify": None, "game": None}
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

    def icon(i, cx, cy, c):
        if i == 0:
            oval_(P(cx-8, cy-8, cx+8, cy+8), fill=c, outline=""); oval_(P(cx-3, cy-11, cx+11, cy+3), fill=C["ib"], outline="")
        elif i == 1:
            cv.create_polygon(P(cx-9, cy-1, cx, cy-9, cx+9, cy-1), fill=c); cv.create_rectangle(*P(cx-6, cy-1, cx+6, cy+8), fill=c, outline="")
        elif i == 2:
            cv.create_rectangle(*P(cx-8, cy-3, cx+8, cy+9), fill=c, outline="")
            for k in (-8, -2, 4): cv.create_rectangle(*P(cx+k, cy-8, cx+k+4, cy-3), fill=c, outline="")
        else:
            cv.create_polygon(P(cx-9, cy+6, cx-9, cy-6, cx-4, cy, cx, cy-9, cx+4, cy, cx+9, cy-6, cx+9, cy+6), fill=c)

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
        text(M + 44, 30, "AoE4 Spotify", 19, b=True)
        tw = tkfont.Font(font=F(19, True)).measure("AoE4 Spotify") / S
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
        click("en", lambda: (set_user("enabled", not en), anim_enabled(en), threading.Thread(target=music_sync, args=(not en,), daemon=True).start()))
        tip("encard", "Runs automatically when you launch AoE4 from Steam and mutes the game's own music. You don't need this window open." if en else "Off: music won't switch when you play, and the game's music is back on.")
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
            rr(M, 172, R_, 172 + PL_H, 10, C["card"]); cv.create_line(*P(M + 12, 208, R_ - 12, 208), fill=C["line"])
        rr(M, 172, R_, 208, 10, C["card"], tag="plh")
        text(M + 16, 190, "Playlists", 13, b=True, tag="plh")
        cv.create_image(*P(R_ - 18, 190), image=chev_up if ui["open"] else chev_down, anchor="center", tags="plh")
        click("plh", lambda: (ui.update(open=not ui["open"], am=False), draw()))
        X = M + 22; XR = R_ - 22                           # age rows: same inset left and right
        for i, (k, lab) in enumerate(AGES if ui["open"] else []):
            rx = XR - 6 - 30; y = PL_Y(i); uri = cfg["playlists"].get(k, ""); is_def = uri == defaults.get(k)
            if i < len(AGES) - 1: cv.create_line(*P(X + 48, y + 44, XR, y + 44), fill="#2a2a2a", tags="pldiv")
            rr(X - 6, y, XR + 6, y + 42, 9, "#262626", tag="rowhl%d" % i); cv.itemconfigure("rowhl%d" % i, state="normal" if hov.get("row") == i else "hidden")
            pid = uri.split(":")[-1]
            cimg = cover_img(custom_cover(uri) if is_custom(uri) else (covers.get(pid) or (cover_file(pid) if pid else None)))
            if cimg:                                       # playlist cover: click = open in Spotify
                cv.create_image(*P(X + 24, y + 21), image=cimg, anchor="center", tags="cov%d" % i)
                click("cov%d" % i, lambda pid=pid, uri=uri, k=k, lab=lab: change(k, lab) if is_custom(uri) else open_playlist(pid))
                tip("cov%d" % i, "Edit list" if is_custom(uri) else "Open in Spotify")
            else:
                rr(X + 9, y + 6, X + 39, y + 36, 6, C["ib"]); icon(i, X + 24, y + 21, C["acc"])
            rr(X + 38, y + 7, rx - 76, y + 35, 8, "", tag="opn%d" % i)          # transparent hit area (gaps between texts)
            rr(X + 38, y + 7, rx - 76, y + 35, 8, "#2c2c2c", tag="hl%d" % i); cv.itemconfigure("hl%d" % i, state="hidden")
            text(X + 48, y + 21, lab, 13, b=True, tag="opn%d" % i)
            oval_(P(X+118, y+17, X+126, y+25), fill=C["acc"] if uri else C["idle"], outline="", tags="opn%d" % i)
            nm = pl_name(uri); nm = nm if len(nm) <= 15 else nm[:14] + "\u2026"
            text(X + 132, y + 21, nm, 12, C["mu"], tag="opn%d" % i)
            if pid:
                click("opn%d" % i, lambda pid=pid, uri=uri, k=k, lab=lab: change(k, lab) if is_custom(uri) else open_playlist(pid))
                tip("opn%d" % i, "Edit list" if is_custom(uri) else "Open in Spotify"); hover_hl(i)
            rr(rx - 70, y + 9, rx - 8, y + 33, 12, C["card"], C["acc"], ("chg%d" % i, "chgx")); text(rx - 39, y + 21, "Change", 10, C["acc"], True, "center", ("chg%d" % i, "chgx")); cv.itemconfigure("chg%d" % i, state="normal" if hov.get("row") == i else "hidden")   # hover-only: hidden before first paint
            rc = C["dis"] if is_def else C["mu"]
            rr(rx, y + 9, rx + 30, y + 33, 12, C["card"], rc, "rev%d" % i); undo_icon(rx + 15, y + 21, rc, "rev%d" % i)
            click("chg%d" % i, lambda k=k, lab=lab: change(k, lab))
            if not is_def: click("rev%d" % i, lambda k=k: revert(k))
            tip("rev%d" % i, "Revert" if not is_def else "Revert (already default)")
        # Age 4 Intro theme
        base = 172 + PL_H + 10 if ui["open"] else 218
        Hn = base + 112 + (AM_H if ui.get("am") else 46) + M
        ui["H"] = Hn                                       # applied after the whole frame is drawn (see draw wrapper)
        y = base; bon = bool((cfg.get("boss_intro") or {}).get("enabled", True))
        rr(M, y, R_, y + 46, 10, C["card"], tag="intro"); icon(3, M + 24, y + 23, C["acc"])
        text(M + 46, y + 23, "Age Intros", 13, b=True, tag="intro")
        sx = M + 46 + tkfont.Font(font=F(13, True)).measure("Age Intros") / S + 14
        ion = cfg.get("intros") or {}
        for j, (a_, rn) in enumerate(zip(INTRO_AGES, ("I", "II", "III", "IV"))):   # one pip per age, lit when its intro is on
            lit = bool((ion.get(a_) or {}).get("enabled")) and bon; px_ = sx + 11 + j * 25
            oval_(P(px_ - 10, y + 13, px_ + 10, y + 33), fill=C["acc"] if lit else "#2a2a2a", outline="" if lit else "#3a3a3a", tags="intro")
            text(px_, y + 23, rn, 9, "#121212" if lit else C["mu"], True, "center", "intro")
        toggle(R_ - 30 - 44, y + 11, bon, "boss")
        chev_right(R_ - 15, y + 23, C["mu"], "intro", 16)
        click("intro", open_editor); tip("intro", "Intro song per age and civ")
        click("boss", lambda: set_user("boss_intro_enabled", not bon))
        # fade
        y = base + 56; fv = float(cfg.get("fade_seconds", 2))
        rr(M, y, R_, y + 46, 10, C["card"])
        cv.create_image(*P(M + 24, y + 23), image=fade_icon(C["acc"]), anchor="center")
        text(M + 46, y + 23, "Fade", 13, b=True)
        x0, x1 = FX0, FX1; xv = x0 + (x1 - x0) * fv / 5
        rr(x0, y + 20, x1, y + 26, 3, C["off"], tag="fade"); rr(x0, y + 20, max(xv, x0 + 6), y + 26, 3, C["acc"], tag="fade")
        oval_(P(xv-9, y+14, xv+9, y+32), fill="white", outline=C["acc"], width=2*S, tags="fade")
        text(R_ - 12 - 30 - 10, y + 23, ("%.1fs" % fv) if fv else "Off", 12, C["acc"], True, "e")
        fdef = float(base_cfg.get("fade_seconds", 2)); f_is_def = abs(fv - fdef) < 1e-6
        rc = C["dis"] if f_is_def else C["mu"]          # revert to default fade, right-aligned like playlist rows
        rx = R_ - 12 - 30
        rr(rx, y + 11, rx + 30, y + 35, 12, C["card"], rc, "revf"); undo_icon(rx + 15, y + 23, rc, "revf")
        if not f_is_def: click("revf", lambda: (user.pop("fade_seconds", None), save_user(user), draw()))
        tip("revf", "Revert" if not f_is_def else "Revert (already default)")
        # After match: expandable radio list (what the music does when a match ends)
        y = base + 112; am = after_match_cfg(cfg); mode = am["mode"]; aopen = bool(ui.get("am"))
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
            rr(mx0, my0, R_, my0 + 180 + dy, 10, "#262626", "#3a3a3a")
            rr(mx0 + 6, my0 + 6, R_ - 6, my0 + 38, 7, "#262626", tag="m_chk"); text(mx0 + 20, my0 + 22, "\u21bb  Check for updates", 12, C["tx"], tag="m_chk")
            rr(mx0 + 6, my0 + 38, R_ - 6, my0 + 70, 7, "#262626", tag="m_log"); text(mx0 + 20, my0 + 54, "\u2630  Open log", 12, C["tx"], tag="m_log")
            gw = tkfont.Font(font=F(12)).measure("\u2630  ") / S                 # label column of the other items
            rr(mx0 + 6, my0 + 70, R_ - 6, my0 + 102, 7, "#262626", tag="m_gh")
            cv.create_image(*P(mx0 + 20 + (gw - 8) / 2, my0 + 86), image=gh_icon(), anchor="center", tags="m_gh")
            text(mx0 + 20 + gw, my0 + 86, "GitHub", 12, C["tx"], tag="m_gh")
            if own: rr(mx0 + 6, my0 + 102, R_ - 6, my0 + 134, 7, "#262626", tag="m_own"); text(mx0 + 20, my0 + 118, "\u25ce  Your Spotify app", 12, C["tx"], tag="m_own")
            cv.create_line(*P(mx0 + 10, my0 + 140 + dy, R_ - 10, my0 + 140 + dy), fill="#3a3a3a")
            rr(mx0 + 6, my0 + 144 + dy, R_ - 6, my0 + 174 + dy, 7, "#262626", tag="m_un"); text(mx0 + 20, my0 + 159 + dy, "\u2715  Uninstall", 12, C["red"], True, tag="m_un")
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
        d = tk.Toplevel(root); dark_window(d, C["card"]); d.title("AoE4 Spotify"); d.transient(root); d.resizable(False, False)
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
                                    fix=lambda: with_steam_closed(set_launch_option)))
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
                                    fix=lambda: with_steam_closed(set_launch_option)))
        threading.Thread(target=go, daemon=True).start()

    art = Art(root, S)
    try:                                               # drag songs / playlists from Spotify onto Victory / Defeat
        from tkinterdnd2 import TkinterDnD, DND_TEXT
        TkinterDnD._require(root); cv.drop_target_register(DND_TEXT)
        cv.dnd_bind("<<DropPosition>>", lambda e: "copy")
        cv.dnd_bind("<<Drop>>", lambda e: (root.after_idle(lambda d=e: am_drop(d)), "copy")[1])
    except Exception as ex: log("Panel drag-in unavailable: %r" % ex)
    def open_editor(): pool_editor(root, user, lambda: (save_user(user), draw()))
    pending_access()

    def start_update():
        info = upd["info"]
        if not info or upd["phase"] in ("dl", "run"): return
        upd.update(phase="dl", pct=0); draw()
        dest = os.path.join(os.environ.get("TEMP") or DATA, "AoE4 Spotify Setup %s.exe" % info["version"])
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
        steam = " Steam will close for a moment and reopen by itself." if steam_running() else ""
        if messagebox.askyesno("Uninstall AoE4 Spotify?", "Removes the app, its shortcuts and settings, and puts the game's launch options and music volume back." + steam):
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
            s = {"spotify": os.path.exists(TOKEN), "game": aoe_running()}
            if s != state: state.update(s); post(draw)
        threading.Thread(target=go, daemon=True).start()
    def tick():
        if not win_hidden(root): refresh_now()        # minimized: nothing to show, no polling
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
    root._ui = ui                                      # (tests)
    draw(); reveal(root, warm=warm_panel); note_window("panel", root); pump(); tick(); fetch_names(); check_updates(); root.mainloop()
