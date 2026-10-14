"""The playlist / song picker (list_picker).

Split out of core/gui.py in 1.0.9; behaviour unchanged.
"""

import os, re, threading, time
from aoe4spotify.core.runtime import dark_window, log, reveal, set_canvas_height, win_hidden
from aoe4spotify.core.branding import APP_NAME
from aoe4spotify.core.settings import CUSTOM_MAX, CUSTOM_PREFIX, custom_cover, custom_get, is_custom, load_config, load_user_settings
from aoe4spotify.core.spotify import Spotify
from PIL import ImageFilter
from aoe4spotify.core.ui import aa
from aoe4spotify.core.ui.library import LIKED_ID, LIKED_URI, RE_PLAYLIST, _MYLIB, lib_cover, liked_tracks, my_library, now_playing, parse_track, parse_tracks, search_tracks, store_track, track_cover
from aoe4spotify.core.ui.widgets import _Pen, _dashed_rr, _pen_icon, after_mouse_up, canvas_rect, get_tip, install_edit_menu, mosaic_image, save_mosaic

def list_picker(parent, title, current="", allow_tracks=False, user=None, save=None, start_builder=False):
    """Modal picker. Returns a Spotify playlist uri, a track uri (allow_tracks), or a custom list uri; None = cancelled.
    'Paste link' takes a pasted or dropped link; 'Make your own' opens the builder (app-only list, saved in settings)."""
    import tkinter as tk, tkinter.font as tkfont, threading
    from PIL import Image, ImageDraw, ImageTk
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", line="#2a2a2a", fld="#181818",
             ib="#2a2a2a", red="#e5675f", dim="#6c6c6c")
    user = user if user is not None else load_user_settings()
    d = tk.Toplevel(parent); dark_window(d, C["bg"]); d.title(APP_NAME); d.resizable(False, False)
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
        aa.line(cv, P(cx - 2.5, cy - 5, cx + 2.5, cy, cx - 2.5, cy + 5), C["acc"] if hv else C["mu"], max(1, 1.8 * S), tags="mk")
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
