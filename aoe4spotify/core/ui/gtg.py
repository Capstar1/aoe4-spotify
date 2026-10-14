"""The "You're good to go" window after Spotify login.

Split out of core/gui.py in 1.0.9; behaviour unchanged.
"""

import json, os, re, threading
from aoe4spotify.core.runtime import ASSETS, dark_window, log, note_window, release_window, reveal, single_window
from aoe4spotify.core.branding import APP_NAME
from aoe4spotify.games.registry import active as game
from aoe4spotify.core.ui.widgets import set_app_icon

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
    if not single_window("gtg", APP_NAME): return None
    win = tk.Toplevel(parent) if parent else tk.Tk()
    dark_window(win, C["bg"])
    win.bind("<Destroy>", lambda e: release_window("gtg") if e.widget is win else None, add="+")
    win.title(APP_NAME); win.configure(bg=C["bg"]); win.resizable(False, False)
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
            else: rows.append(("warn", game().name, (game().launcher or "Launcher") + " not found", None))
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
        text(W / 2, 20, (game().launcher or "The launcher") + " closes and reopens...", 10, C["mu"], anchor="center")
        done = []
        def go():
            try: fix()
            except Exception as e: log("Fix launch option failed: %r" % e)
            try: done.append(game().launch_option_is_set())
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
