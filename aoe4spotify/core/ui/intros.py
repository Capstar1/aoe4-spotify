"""The age-intro editor (pool_editor).

Split out of core/gui.py in 1.0.9; behaviour unchanged.
"""

import json, os, re, threading, time
from aoe4spotify.core.runtime import dark_window, focus_window, log, note_window, release_window, reveal, single_window, win_hidden
from aoe4spotify.core.settings import apply_user, DEFAULT_AGE, DEFAULT_PRESET_NAME, INTRO_AGES, apply_preset, build_intros, decode_preset, encode_preset, load_config, migrate_intros_v2, preset_counts, preset_from_user, preset_key, preset_songs, unique_preset_name, user_presets, autosave_preset, migrate_autosave
from aoe4spotify.core.spotify import Spotify
from aoe4spotify.core.branding import APP_NAME, SHARE_PREFIX
from aoe4spotify.games.registry import active as game
from aoe4spotify.core.ui.glow import GLOW_N, even_px, render_badge, render_glow
from aoe4spotify.core.ui.library import ROMAN, Art, BUILTIN_SONGS, CIV_LIST, SONGS, SONG_BY_URI, SW_H, SW_W, default_pool, fetch_track, fetch_tracks, http_get, load_custom_songs, normalize_pools, now_playing, parse_tracks, pick_image, search_tracks, song_sorted, store_track, track_cover
from aoe4spotify.core.ui import aa
from aoe4spotify.core.ui.widgets import canvas_rect, get_tip, set_app_icon

def pool_editor(parent, user, save, on_close=None, height=None):
    """Tier-list style editor. user: the panel's settings dict (shared); save(): persist + refresh panel.
    on_close given: built INSIDE parent (a page of the main window, not a window of its own); the host packs the
    returned frame and on_close() runs when the page is left (back arrow, Esc/Backspace on the overview).
    height: the host's height (logical px); the page matches it, but never shorter than its four age cards need."""
    inline = on_close is not None
    if not inline and not single_window("editor", "Age Intros"): return None
    import tkinter as tk
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", line="#2e2e2e", dis="#4a4a4a")
    if inline: win = tk.Frame(parent, bg=C["bg"], highlightthickness=0); wtop = parent.winfo_toplevel()
    else:
        win = wtop = tk.Toplevel(parent); dark_window(win, C["bg"]); win.title(APP_NAME); win.resizable(False, False)
        win.bind("<Destroy>", lambda e: release_window("editor") if e.widget is win else None, add="+")
    S = win.winfo_fpixels("1i") / 96.0
    HY = 40                                            # header row centre (back arrow, icon, title): same on every page
    OV_TOP, OV_STEP, OV_CARD, OV_FOOT = 124, 106, 96, 48             # overview: first card y, card pitch, card height, footer
    W, LT, RH, GAP = 520, 178, 40, 4                   # right-hand items are placed from W (W - n)
    H_MIN = OV_TOP + len(INTRO_AGES) * OV_STEP - (OV_STEP - OV_CARD) + OV_FOOT   # every age card fits (4 ages -> 586)
    H = max(H_MIN, int(height or 0))                   # inline: as tall as the main window, never less than H_MIN
    CR = 14                                            # civ-row chip radius
    BOT = H - 12; STEP = RH + GAP
    cv = tk.Canvas(win, width=int(W * S), height=int(H * S), bg=C["bg"], highlightthickness=0); cv.pack()
    art = Art(win, S)
    from aoe4spotify.core.ui.crown import crown_color, crown_image
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
    if migrate_autosave(user): save()                                  # old unsaved edits -> a user preset (never Default)
    ed = {"age": DEFAULT_AGE, "page": "overview"}            # page: "overview" or the age being edited
    def ages_on(): return {a_: build_intros(base, user)[a_]["enabled"] for a_ in INTRO_AGES}
    def pools(age=None):
        age = age or ed["age"]; bp = (user.get("intro_pools") or {}).get(age) or {}
        if age == DEFAULT_AGE: return {c: song_sorted(bp[c] if c in bp else default_pool(base, c)) for c, _ in CIV_LIST}
        return {c: song_sorted(bp.get(c) or []) for c, _ in CIV_LIST}          # other ages: blank unless you add songs
    def row_default(civ): return default_pool(base, civ) if ed["age"] == DEFAULT_AGE else []
    def age_custom(age=None):                          # anything to reset on this age?
        age = age or ed["age"]; return bool((user.get("intro_pools") or {}).get(age))
    st = {"sc": 0, "hov": None, "drag": None, "ghost": None, "drop": None, "press": None, "msg": None}
    max_sc = lambda: max(0, len(CIV_LIST) * STEP - GAP - (BOT - LT))
    def row_y(i): return LT + i * STEP - st["sc"]
    NB = len(BUILTIN_SONGS)
    def _ysp():
        m = len(SONGS) - NB; return min(50.0, 100.0 / max(1, m))
    # built-in song pack (adapter's intro_pack): folded behind one emblem; t = 0 folded .. 1 unfolded
    PACK = game().intro_pack if NB else None
    pk = {"open": bool(user.get("intro_pack_open")) if PACK else True, "job": None, "last": 0.0}
    pk["t"] = 1.0 if pk["open"] else 0.0
    ER, EX, TY = 23, 57, 119                           # emblem radius / centre (logical)
    def _ease(u): u = max(0.0, min(1.0, u)); return u * u * (3 - 2 * u)
    def _bsp():                                        # unfolded spacing: songs + '<' + divider + YOURS fit the tray
        m = len(SONGS) - NB; yw = 16 + (m * _ysp() if m else 0) + 2 * 19 + 4   # divider .. right edge of the '+'
        return max(22.0, min(48.0, ((W - 24) - yw - 63 - 53) / max(1, NB - 1)))   # 63: last song edge, '<', gap to divider
    def _u(i):                                         # song i's own progress: they leave the emblem one after another
        return _ease((pk["t"] - 0.10 - i * 0.05) / max(0.2, 0.90 - (NB - 1) * 0.05))
    def back_xy(): return 53 + (NB - 1) * _bsp() + 19 + 7 + 11, TY
    def _far(): return max(EX + (53 + i * _bsp() - EX) * _u(i) for i in range(NB))
    def div_x():
        if not PACK: return W - 176
        far = _far()                                   # the divider rides just behind the furthest song
        return max(EX + ER + 16, far + 19 + 12 + 32 * _ease((pk["t"] - 0.82) / 0.18))   # (+ room for '<' as it appears)
    def tray_xy(i):                                    # built-in group | divider | YOURS group (+ the '+' chip)
        if PACK:
            if i < NB:
                u = _u(i); tx = 53 + i * _bsp(); return EX + (tx - EX) * u, TY
            return div_x() + 16 + tray_rad(NB) + (i - NB) * _ysp(), TY
        if i < NB: return 53 + i * min(48.0, ((W - 176) - 53 - 26) / max(1, NB - 1)), 119      # built-ins squeeze to fit the tray
        return (W - 162) + tray_rad(NB) + 2 + (i - NB) * _ysp(), 119      # left edge of the first chip under the YOURS label
    def tray_rad(i): return 19 if i < NB else max(9.0, min(19.0, _ysp() * 0.45))
    def tray_r(): return 19
    def chip_xy(i, j): return 205 + j * 34, row_y(i) + RH / 2
    def _bp(p):
        if ed["age"] != DEFAULT_AGE: return {c: song_sorted(v) for c, v in p.items() if v}
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
        newp = autosave_preset(user)                   # every edit autosaves (Default -> new 'Custom')
        sn = snap()
        if sn != hist["cur"]:
            hist["undo"].append(hist["cur"]); hist["redo"].clear(); hist["cur"] = sn
            del hist["undo"][:-500]
        _apply(sn)
        if newp: toast("Saved as \u201c%s\u201d" % newp)
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
        try:
            if win.winfo_exists(): win.after(30, uipump)        # closed: the loop ends (the panel process lives on)
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
                if not ip[a_][civ] and a_ != DEFAULT_AGE: ip[a_].pop(civ)   # Imperial: [] = emptied (not the default)
        record(); draw()
    def undo_redo(back):
        src, dst = (hist["undo"], hist["redo"]) if back else (hist["redo"], hist["undo"])
        if not src or st["drag"]: return "break"
        dst.append(hist["cur"]); hist["cur"] = src.pop(); _apply(hist["cur"])
        if autosave_preset(user) is not None: hist["cur"] = snap()
        save(); st["msg"] = None; draw()
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
    CARD_Y = lambda k: OV_TOP + k * OV_STEP
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
        d = tk.Toplevel(win); dark_window(d, C["card"]); d.title(APP_NAME); d.resizable(False, False); d.transient(wtop)
        tk.Label(d, text=title, bg=C["card"], fg=C["tx"], font=("Segoe UI", 11, "bold")).pack(padx=16, pady=(14, 6), anchor="w")
        e_ = tk.Entry(d, width=32, bg="#2a2a2a", fg=C["tx"], insertbackground=C["tx"], relief="flat", font=("Segoe UI", 10)); e_.pack(padx=16, ipady=5)
        e_.insert(0, init); e_.select_range(0, "end")
        def ok(*_):
            v = e_.get().strip()
            if v: d.destroy(); cb(v)
        tk.Button(d, text="Save", command=ok, bg=C["acc"], fg="#121212", relief="flat", font=("Segoe UI", 10, "bold"), padx=14).pack(padx=16, pady=(10, 14), anchor="e")
        e_.bind("<Return>", ok); d.bind("<Escape>", lambda e: d.destroy())
        reveal(d, over=wtop); e_.focus_set(); win._name = (d, e_, ok); return "break"
    def import_dialog():
        d = tk.Toplevel(win); dark_window(d, "#1e1e1e"); d.title(APP_NAME); d.resizable(False, False); d.transient(wtop)
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
                cnt = preset_counts(base, p); on = {a_: bool(p["ages"].get(a_, a_ == DEFAULT_AGE)) for a_ in INTRO_AGES}
                for k_, a_ in enumerate(INTRO_AGES):
                    x = 40 + k_ * 102
                    dc.create_image((x + 15) * S, 219 * S, image=art.disc(30, "#1e3c28" if on[a_] and cnt[a_] else "#2c2c2c",
                                    ROMAN[k_], C["acc"] if on[a_] and cnt[a_] else C["mu"], 11), tags="g")
                    dtext(x + 38, 212, str(cnt[a_]), 14, b=True); dtext(x + 38, 228, "civs", 9, C["mu"])
                dc.create_image(55 * S, 263 * S, image=art.plus(13), tags="g")
                dtext(78, 256, str(len(p["custom"])), 14, b=True); dtext(78, 272, "custom", 9, C["mu"])
                aa.check(dc, 389 * S, 262.5 * S, 14 * S, C["acc"], max(1, 2.2 * S), tags="g")
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
            if isinstance(clip, str) and clip.strip().startswith(SHARE_PREFIX): e_.insert(0, clip.strip())
        except Exception: pass
        check(); reveal(d, over=wtop); e_.focus_set(); win._imp = (d, e_, res, go_import, check)
        return "break"
    BAR_Y = 84                                        # 10 px below the header (breathing room)
    def add_dialog():
        """Search Spotify, add what's playing, or paste a link. Clicking a result adds it."""
        D = dict(bg=C["card"], row="#2a2a2a", fld="#232323", tx=C["tx"], mu=C["mu"], acc=C["acc"])
        d = tk.Toplevel(win); dark_window(d, D["bg"]); d.title(APP_NAME); d.resizable(False, False); d.transient(wtop)
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
                    if res == "login": say(("Log in to Spotify in " + APP_NAME + " first"), True)
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
                    if got == "login": say(("Log in to Spotify in " + APP_NAME + " first"), True)
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
                    if it == "login": say(("Log in to Spotify in " + APP_NAME + " first"), True)
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
        reveal(d, over=wtop); e_.focus_set()
        win._add = (d, e_, ok, msg, {"R": R, "on_key": on_key, "search": search, "what_playing": what_playing, "click_row": lambda k: on_click(type("E", (), {"y": (k * RHd + 10) * S})()), "paint": paint})   # (tests)
        return "break"
    kb = cv if inline else win                         # keys: inline the canvas holds the focus (a Frame never gets key events)
    kb.bind("<Control-z>", lambda e: undo_redo(True)); kb.bind("<Control-Z>", lambda e: undo_redo(False))   # Ctrl+Shift+Z
    kb.bind("<Control-y>", lambda e: undo_redo(False)); kb.bind("<Control-Y>", lambda e: undo_redo(False))
    kb.bind("<Control-Shift-Z>", lambda e: undo_redo(False)); kb.bind("<Control-Shift-z>", lambda e: undo_redo(False))
    # ---- hit testing (logical coords)
    SB_X0, SB_X1 = (W - 36), (W - 16)                            # scrollbar hit lane (thumb drawn at 572..576, wider when hot)
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
            if not m and 18 <= x <= 50 and HY - 16 <= y <= HY + 16: return ("back",)        # same spot as on the age pages
            if m == "presets":
                ps = user_presets(user)
                for i_, p in enumerate(ps):
                    if 26 <= x <= 324 and 118 + i_ * 46 <= y <= 160 + i_ * 46: return ("pm", p["name"])
                yn = 118 + len(ps) * 46
                if 26 <= x <= 324 and yn + 2 <= y <= yn + 32: return ("pnew",)
                if 20 <= x <= 330 and 108 <= y <= yn + 40: return ("menu",)
            if BAR_Y - 18 <= y <= BAR_Y + 18:
                if 20 <= x <= (W - 140): return ("preset",)
                if (x - (W - 106)) ** 2 + (y - BAR_Y) ** 2 <= 16 ** 2: return ("share",)
                if (x - (W - 58)) ** 2 + (y - BAR_Y) ** 2 <= 16 ** 2: return ("import",)
            if m: return None
            for k, a_ in enumerate(INTRO_AGES):
                y0 = CARD_Y(k)
                if 20 <= x <= (W - 20) and y0 <= y <= y0 + OV_CARD:
                    if (W - 114) <= x <= (W - 56) and y0 + 16 <= y <= y0 + 48: return ("swoff", a_, (W - 85), y0 + 48) if age_empty(a_) else ("cardtog", a_)
                    return ("card", a_)
            return None
        if PACK and pk["t"] == 0.0 and (x - EX) ** 2 + (y - TY) ** 2 <= (ER + 2) ** 2: return ("pack",)
        if PACK and pk["t"] == 1.0 and (x - back_xy()[0]) ** 2 + (y - TY) ** 2 <= 13 ** 2: return ("packx",)
        for i in range(len(SONGS) + 1):
            if PACK and i < NB and pk["t"] < 1.0: continue          # folded / moving: not clickable
            cx, cy = tray_xy(i); rt = tray_rad(i) + 2
            if (x - cx) ** 2 + (y - cy) ** 2 <= rt ** 2: return ("tray", i) if i < len(SONGS) else ("plus",)
        if 18 <= x <= 50 and HY - 16 <= y <= HY + 16: return ("back",)
        if (W - 86) <= x <= (W - 34) and HY - 16 <= y <= HY + 16: return ("swoff", ed["age"], (W - 56), HY + 16) if age_empty(ed["age"]) else ("tabtog", ed["age"])
        if age_custom() and (W - 32) <= x <= (W - 10) and HY - 12 <= y <= HY + 12: return ("reset",)
        if LT <= y <= BOT and 20 <= x <= (W - 32):
            i = int((y - LT + st["sc"]) // STEP)
            if 0 <= i < len(CIV_LIST) and row_y(i) <= y <= row_y(i) + RH:
                p = pools()[CIV_LIST[i][0]]; minn = 0
                for j in range(len(p)):
                    cx, cy = chip_xy(i, j)
                    if len(p) > minn and (x - cx - 11) ** 2 + (y - cy + 11) ** 2 <= 7 ** 2 and st["hov"] in (("chip", i, j), ("x", i, j)):
                        return ("x", i, j)
                    if (x - cx) ** 2 + (y - cy) ** 2 <= 16 ** 2: return ("chip", i, j)
                if ed["age"] == DEFAULT_AGE and (W - 68) <= x <= (W - 38): return ("undo", i)
                return ("row", i)
        return None
    def sw(xr, cy, on, disabled=False):                # same switch as the main panel (SW_W x SW_H, knob SW_H-6); right edge xr, centred on cy
        x0, y0 = xr - SW_W, cy - SW_H / 2
        rr(x0, y0, xr, y0 + SW_H, SW_H / 2, "#2e2e2e" if disabled else (C["acc"] if on else "#3a3a3a"), tags="sw")
        kx = xr - SW_H / 2 if on else x0 + SW_H / 2
        cv.create_image(kx * S, cy * S, image=art.disc(SW_H - 6, "#6a6a6a" if disabled else "#ffffff"), tags=("sw", "swknob"))
    def badge(x, y, age, on, r):
        cv.create_image(x * S, y * S, image=art.disc(2 * r, "#1e3c28" if on else "#2c2c2c",
                        ROMAN[INTRO_AGES.index(age)], C["acc"] if on else C["mu"], r * 0.62))
    def crown_state():
        c = apply_user(load_config(user=False), user)
        return crown_color(bool((c.get("boss_intro") or {}).get("enabled", True)), bool(c.get("enabled", True)))
    def crown_img(color=None):
        """Age Intros header crown: the shared symmetric crown (24 wide); green or the disabled grey; cached per colour."""
        color = color or crown_state(); k = ("crown", color)
        if k not in imgs: imgs[k] = ImageTk.PhotoImage(crown_image(24, S, color), master=win)
        return imgs[k]
    def chev(x, y, c, back=False):
        cv.create_image(x * S, y * S, image=art.chevron(22, c, back))
    def draw_overview():
        cv.delete("all"); on = ages_on(); hov = st["hov"]
        cv.create_image(34 * S, HY * S, image=art.chevron(32, C["tx"], True, "#2a2a2a" if (hov or ("",))[0] == "back" else C["card"], w=6, h=12), tags="backbtn")
        cv.create_image(78 * S, HY * S, image=crown_img(), tags="crown")                 # anti-aliased crown, centred like the age badge
        text(102, HY, "Age Intros", 18, b=True, tags="htitle")
        for k, a_ in enumerate(INTRO_AGES):
            y = CARD_Y(k); p = pools(a_); n = sum(1 for v in p.values() if v); hv = hov and hov[1:] == (a_,)
            rr(20, y, (W - 20), y + OV_CARD, 18, "#262626" if hv else C["card"], "#464646" if hv else None)
            badge(62, y + 32, a_, on[a_], 18)
            text(100, y + 22, a_.capitalize(), 17, b=True)
            text(100, y + 40, ("%d/%d civs" % (n, len(CIV_LIST))) if n else "Empty", 11, C["acc"] if (n and on[a_]) else C["mu"], True)
            sw((W - 66), y + 32, on[a_], age_empty(a_)); chev((W - 40), y + 32, C["mu"])
            rr(100, y + 62, (W - 270), y + 66, 3, "#323232")
            if n: rr(100, y + 62, 100 + max(6, (W - 370) * n // len(CIV_LIST)), y + 66, 3, C["acc"] if on[a_] else "#5a5a5a")
            allu = [u for u in song_sorted([u for v in p.values() for u in v]) if u in SONG_BY_URI]; used = allu[:5]
            if used:
                for j, u in enumerate(used):
                    cv.create_image(((W - 225) + j * 24) * S, (y + 64) * S, image=art.chip(SONG_BY_URI[u][0], 13))
                more = len(allu) - len(used)
                if more > 0:                               # '+X' overflow chip (variant A): same size, overlapping
                    ox = ((W - 225) + len(used) * 24) * S
                    cv.create_image(ox, (y + 64) * S, image=art.disc(33, "#262626" if hv else C["card"]))
                    cv.create_image(ox, (y + 64) * S, image=art.disc(30, "#2c2c2c", "+%d" % more, "#dcdcdc", 11, outline="#6e6e6e", ow=2.5))
            else:
                for j in range(3):
                    aa.oval(cv, ((W - 240) + j * 24) * S, (y + 48) * S, ((W - 210) + j * 24) * S, (y + 78) * S, fill=C["card"], outline="#464646", width=max(1, S))
        if st.get("toast"):
            import tkinter.font as tkfont
            tw = tkfont.Font(root=win, family="Segoe UI", size=-int(13 * S), weight="bold").measure(st["toast"]) / S + 70
            x0 = W / 2 - tw / 2; rr(x0, H - 46, x0 + tw, H - 8, 19, "#282828", C["acc"], 1.2)
            cv.create_image((x0 + 25) * S, (H - 27) * S, image=art.disc(22, C["acc"]))
            aa.check(cv, (x0 + 25) * S, (H - 27) * S, 12 * S, "#0a0a0a", max(1, 2.4 * S))
            text(x0 + 45, H - 27, st["toast"], 13, b=True)
        else: text(W / 2, H - 20, "Click an age to edit", 10, "#5a5a5a", anchor="center")
        draw_bar()
    def chev_down(x, y, c):
        aa.line(cv, [v * S for v in (x - 4, y - 2, x, y + 2, x + 4, y - 2)], c, max(1, 2 * S))
    def bar_icon(kind, c):
        k = ("baricon", kind, c)
        if k not in imgs:
            Q = 4; Z = even_px(30, S); im = Image.new("RGBA", (Z * Q, Z * Q), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
            u = Z * Q / 30.0; cx = cy = Z * Q / 2; lw = max(Q, int(round(1.8 * S * Q)))
            P = lambda pts: [(cx + a * u, cy + b * u) for a, b in pts]
            if kind == "share":
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
        rr(20, y - 18, (W - 140), y + 18, 18, "#2a2a2a" if op else C["card"], C["acc"] if m == "presets" else "#3e3e3e", 1.2)
        cv.create_image(40 * S, y * S, image=art.disc(12, C["acc"]))
        nm = user.get("intro_preset") or DEFAULT_PRESET_NAME
        text(56, y, nm if len(nm) <= 30 else nm[:29] + "\u2026", 13, b=True, tags="pname")
        text((W - 176), y, "Auto-saved", 10, C["mu"], True, anchor="e", tags="autosaved")
        chev_down((W - 160), y, C["tx"] if op else C["mu"])
        for cx_, kind in (((W - 106), "share"), ((W - 58), "import")):
            hv = hov[0] == kind
            cv.create_image(cx_ * S, y * S, image=art.disc(30, "#383838" if hv else "#2a2a2a"))
            cv.create_image(cx_ * S, y * S, image=bar_icon(kind, "#ffffff" if hv else "#cdcdcd"))
        if m == "presets":
            ps = user_presets(user); yb = 118 + len(ps) * 46
            rr(18, 106, 332, yb + 44, 15, "#0c0c0c"); rr(20, 108, 330, yb + 40, 14, "#242424", "#3e3e3e", 1)
            for i_, p in enumerate(ps):
                yy = 118 + i_ * 46; is_cur = p["name"] == (user.get("intro_preset") or DEFAULT_PRESET_NAME)
                if is_cur: rr(26, yy, 324, yy + 42, 10, "#1e3426")
                elif hov == ("pm", p["name"]): rr(26, yy, 324, yy + 42, 10, "#2e2e2e")
                for j, u_ in enumerate(preset_songs(base, p)[:3]):
                    sg = SONG_BY_URI.get(u_)
                    if sg: cv.create_image((48 + j * 16) * S, (yy + 21) * S, image=art.chip(sg[0], 10))
                text(100, yy + 21, p["name"], 13, C["acc"] if is_cur else C["tx"], True)
                cnt = preset_counts(base, p)
                ag = " ".join(r for r, a_ in zip(ROMAN, INTRO_AGES) if cnt[a_] and (p.get("ages") or {}).get(a_, a_ == DEFAULT_AGE))
                text(250, yy + 21, ag, 10, C["mu"], True)
                if is_cur: aa.check(cv, 307 * S, (yy + 20.5) * S, 14 * S, C["acc"], max(1, 2.2 * S), tags="ptick")
            cv.create_line(32 * S, (yb + 1) * S, 318 * S, (yb + 1) * S, fill="#3e3e3e", width=max(1, int(S)))
            nh = hov[0] == "pnew"
            if nh: rr(26, yb + 4, 324, yb + 32, 8, "#2e2e2e")
            text(48, yb + 18, "+", 16, C["acc"], anchor="center"); text(62, yb + 18, "New preset", 12, C["acc"], True)
    def draw():
        if ed["page"] == "overview": draw_overview(); return
        cv.delete("all"); p = pools(); hov = st["hov"]; drag = st["drag"]
        # list (drawn first; header/tray cover what scrolls above)
        for i, (civ, name) in enumerate(CIV_LIST):
            y = row_y(i)
            if y > BOT or y + RH < LT - 60: continue
            drop = st["drop"] == i
            rr(20, y, (W - 32), y + RH, 10, "#1c2a20" if drop else C["card"], C["acc"] if drop else None)
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
                cv.create_image(x * S, cy * S, image=art.ring(15, C["acc"]), tags="ring")          # anti-aliased, concentric
                text(x, cy, "+", 13, C["acc"], True, "center")
            elif not p[civ]:                               # empty civ: dashed drop slot (+ hint on the first one)
                aa.oval(cv, 190 * S, (cy - 15) * S, 220 * S, (cy + 15) * S, outline="#4b4b4b", width=max(1, S), dash=(3, 3), tags="slot")
                if i == next((k for k, (c_, _) in enumerate(CIV_LIST) if not p[c_]), -1):
                    text(205, cy, "+", 13, "#6e6e6e", anchor="center"); text(232, cy, "Drag songs here", 10, "#646464")
            if ed["age"] == DEFAULT_AGE and p[civ] != song_sorted(default_pool(base, civ)):
                undo_glyph((W - 53), cy, C["mu"])
        # scrollbar
        g_ = sb_geom()
        if g_:
            ms, vh, th, ty = g_; act = bool(st.get("sbd")); hot = act or (st["hov"] or ("",))[0] == "sb"
            x0_, x1_ = ((W - 29), (W - 23)) if hot else ((W - 28), (W - 24))
            rr(x0_, LT, x1_, BOT, 3 if hot else 2, "#2a2a2a", tags="sbtrack")
            rr(x0_, ty, x1_, ty + th, 3 if hot else 2, "#9a9a9a" if act else ("#7a7a7a" if hot else "#5a5a5a"), tags="sbthumb")
        # header + tray (opaque, on top of the scrolled list)
        cv.create_rectangle(0, 0, W * S, (LT - 4) * S, fill=C["bg"], outline="", tags="cover")
        cv.create_rectangle(0, BOT * S, W * S, H * S, fill=C["bg"], outline="", tags="cover")
        a_ = ed["age"]; on = ages_on()
        cv.create_image(34 * S, HY * S, image=art.chevron(32, C["tx"], True, "#2a2a2a" if (st["hov"] or ("",))[0] == "back" else C["card"], w=6, h=12), tags="backbtn")
        badge(78, HY, a_, on[a_], 15); text(102, HY, a_.capitalize(), 18, b=True, tags="htitle")
        sw((W - 38), HY, on[a_], age_empty(a_))
        if age_custom(): undo_glyph((W - 22), HY, C["mu"])
        rr(20, 70, (W - 20), 162, 18, "#1a1a1a", C["line"])
        text(36, 81, game().intro_group_label, 8.5, C["mu"], True)
        if st.get("dropover"):                         # dragging songs in from Spotify
            rr(div_x() + 6, 74, (W - 24), 158, 14, "#16261b", C["acc"], 2); text(div_x() + 14, 81, "DROP TO ADD", 8.5, C["acc"], True)
        else: text(div_x() + 14, 81, "YOURS", 8.5, C["acc"], True)
        cv.create_line(div_x() * S, 84 * S, div_x() * S, 150 * S, fill=C["line"], width=max(1, S))
        order = list(range(len(SONGS)))
        if PACK and pk["t"] < 1.0: order = list(range(NB - 1, -1, -1)) + order[NB:]   # moving: each song slides out from UNDER the one before
        for i in order:
            s_ = SONGS[i]; cx, cy = tray_xy(i); tr = tray_rad(i)
            if PACK and i < NB and pk["t"] < 1.0:      # folding / unfolding: slide out from under the emblem, dim until halfway
                u = _u(i)
                if u <= 0.0: continue
                cv.create_image(cx * S, cy * S, image=art.chip(s_[0], tr, dim=u < 0.5)); continue
            if drag and drag["src"] == ("tray", i):
                cv.create_image(cx * S, cy * S, image=art.ring(tr + 3, C["acc"]), tags="ring")    # anti-aliased, same centre as the chip
            cv.create_image(cx * S, cy * S, image=art.chip(s_[0], tr))
        cx, cy = tray_xy(len(SONGS)); cv.create_image(cx * S, cy * S, image=art.plus(tray_rad(len(SONGS))))
        if PACK:
            k_ = 1.0 - _ease(pk["t"] / 0.45)            # emblem shrinks away first (and grows back last)
            if k_ > 0.12: cv.create_image(EX * S, TY * S, image=art.emblem(PACK, round(ER * k_ * 4) / 4), tags="pack")
            b_ = _ease((pk["t"] - 0.82) / 0.18)          # '<' fades in at the very end
            if b_ > 0.0: cv.create_image((_far() + 26 + 11 * b_) * S, TY * S, image=art.chevron(round(22 * (0.5 + 0.5 * b_)), "#bdbdbd", True, "#2a2a2a", w=4, h=8, lw=1.8), tags="packx")
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
            if res == "login": pv["song"] = pv.get("prev"); hint(("Log in to Spotify in " + APP_NAME + " to preview"), *pv["xy"])
            elif action == "play":
                if res: pv["song"] = SONGS[i][0]; log("Preview: %s" % SONGS[i][1])
                else: pv["song"] = pv.get("prev") if pv.get("prev") != SONGS[i][0] else None; hint("Couldn't play - is Spotify (Premium) running?", *pv["xy"])
            else:
                if not res and pv.get("prev"): pv["song"] = pv["prev"]       # pause failed: still playing
                else: pv["song"] = None
        if changed: overlay(); glow_kick()
        try:
            if win.winfo_exists(): win.after(30, pvpump)
        except Exception: pass
    def glow_spots(song):
        if ed["page"] == "overview": return []
        spots = [(tray_xy(i), tray_rad(i)) for i, s in enumerate(SONGS) if s[0] == song and not (PACK and i < NB and pk["t"] < 1.0)]
        if PACK and pk["t"] < 0.45 and any(s[0] == song for s in BUILTIN_SONGS): spots.append(((EX, TY), ER))
        p = pools()
        for i, (civ, _) in enumerate(CIV_LIST):
            y = row_y(i)
            if y + RH < LT or y > BOT: continue
            for j, uri in enumerate(p[civ]):
                if SONG_BY_URI.get(uri, ("",))[0] == song: spots.append((chip_xy(i, j), CR))
        return spots
    def _right_nb(cx, cy, r, own=None):
        """(item, dx) of the chip overlapping this one from the right (squeezed tray), else None."""
        best = None
        for i in cv.find_overlapping((cx + 1) * S, cy * S, (cx + 2 * r + 4) * S, cy * S):
            if i == own or cv.type(i) != "image" or set(cv.gettags(i)) & SKIP: continue
            c_ = cv.coords(i)
            if not c_ or abs(c_[1] - cy * S) > 1.5: continue
            dx = c_[0] / S - cx
            if 1 < dx < 2 * r + 2 and (best is None or dx < best[1]): best = (i, round(dx, 1))
        return best
    SKIP = {"glow", "cover", "tip", "ghost", "ring", "chipring", "slot", "badge", "ovl", "pack", "packx"}
    def glow_img(r, ph, env):
        """Halo + ring only (the equalizer badge is its own item, always on top)."""
        k = (r, ph, env)
        if k not in glow_cache: glow_cache[k] = ImageTk.PhotoImage(render_glow(r, S, ph, env, badge=False))
        return glow_cache[k]
    def badge_img(r, ph, env):
        k = ("badge", r, ph, env)
        if k not in glow_cache: glow_cache[k] = ImageTk.PhotoImage(render_badge(r, S, ph, env))
        return glow_cache[k]
    def own_chip(cx, cy):
        under = [i for i in cv.find_overlapping(cx * S, cy * S, cx * S, cy * S) if cv.type(i) == "image" and not set(cv.gettags(i)) & SKIP]
        return under[-1] if under else None
    def place_marks():
        """Squeezed chips keep their normal order (right neighbour on top). Highlights (hover ring) sit directly
        above their own chip, so the neighbour covers them; the playing badge stays above everything."""
        for it in cv.find_withtag("chipring"):
            c_ = cv.coords(it); o = own_chip(c_[0] / S, c_[1] / S) if c_ else None
            if o: cv.tag_raise(it, o)
        if cv.find_withtag("badgetop"): cv.tag_raise("badgetop")
        if cv.find_withtag("ghost"): cv.tag_raise("ghost")
    def glow_tick():                                   # 'now playing' breathing glow, ~30 fps while active
        pv["gjob"] = None
        if pv["song"] and win_hidden(wtop): pv["gjob"] = win.after(500, glow_tick); return   # minimized: sleep
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
        bitems = [it for it in pv.setdefault("bitems", []) if cv.type(it)]
        for n, ((cx, cy), r) in enumerate(spots):
            tray = cy < LT - 4
            img = glow_img(r, pv["gt"], round(pv["env"], 1)); bimg = badge_img(r, pv["gt"], round(pv["env"], 1))
            tags = ("glow",) if tray else ("glow", "glowlist")       # list glows scroll under header/bottom covers
            btags = ("badge", "badgetop") if tray else ("badge", "glowlist")
            if n < len(items):
                cv.coords(items[n], cx * S, cy * S); cv.itemconfigure(items[n], image=img, tags=tags)
            else:
                items.append(cv.create_image(cx * S, cy * S, image=img, anchor="center", tags=tags))
            if n < len(bitems):
                cv.coords(bitems[n], cx * S, cy * S); cv.itemconfigure(bitems[n], image=bimg, tags=btags)
            else:
                bitems.append(cv.create_image(cx * S, cy * S, image=bimg, anchor="center", tags=btags))
        for it in items[len(spots):] + bitems[len(spots):]: cv.delete(it)
        pv["gitems"] = items[:len(spots)]; pv["bitems"] = bitems[:len(spots)]
        # z-order: chips keep their order (a squeezed right neighbour stays ON TOP of the playing chip). Each glow
        # sits directly above its own chip, so the neighbour covers it; list glows stay below the header/bottom
        # covers. The badge goes above the neighbour too (tray: above everything).
        for it, b_, ((cx, cy), r) in zip(pv["gitems"], pv["bitems"], spots):
            own = own_chip(cx, cy)
            if own is not None:
                cv.tag_raise(it, own); nb = _right_nb(cx, cy, r, own)
                cv.tag_raise(b_, nb[0] if nb else it)
            else: cv.tag_raise(it); cv.tag_raise(b_)
        if cv.find_withtag("ovl"): cv.tag_raise("ovl")             # x badge, status message: on top
        place_marks()
    def glow_kick():
        if not pv["gjob"]: glow_tick()
    _draw_base = draw
    def draw():                                        # every redraw re-places the glow in the same pass
        _draw_base()
        try: glow_sync()
        except Exception as ex: log("Glow: %r" % ex)
    def playing_marks():
        return                                         # replaced by the glow layer (glow_tick)
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
                if LT <= y <= BOT: undo_glyph((W - 53), y, C["tx"])
            elif hov[0] == "reset" and age_custom():
                undo_glyph((W - 22), HY, C["tx"])
            elif hov[0] == "back":
                cv.create_image(34 * S, HY * S, image=art.chevron(32, C["tx"], True, "#2a2a2a", w=6, h=12))
            elif hov[0] == "pack" and PACK:
                cv.create_image(EX * S, TY * S, image=art.emblem(PACK, ER, hover=True))
            elif hov[0] == "packx" and PACK:
                cv.create_image(back_xy()[0] * S, TY * S, image=art.chevron(22, C["tx"], True, "#3a3a3a", w=4, h=8, lw=1.8))
            elif hov[0] == "plus":                     # brighter '+' instead of a second ring
                cx, cy = tray_xy(len(SONGS)); cv.create_image(cx * S, cy * S, image=art.plus(tray_rad(len(SONGS)), hover=True))
            elif hov[0] == "tray":
                ii = hov[1]; cx, cy = tray_xy(ii); R_ = tray_rad(ii) + 3
                cv.create_image(cx * S, cy * S, image=art.ring(R_, C["acc"]), tags=("ring", "chipring"))   # placed right above its chip (place_marks)
        tip = st["msg"]                                # status message only (tooltips live in the shared GlassTip)
        if tip:
            tw = msg_font.measure(tip[0]) / S + 20; x0 = min(max(8, tip[1] - tw / 2), W - 8 - tw)
            ty = min(max(8, tip[2]), H_vis() - 32)
            rr(x0, ty, x0 + tw, ty + 24, 12, "#1c3a26", C["acc"], 1)
            text(x0 + tw / 2, ty + 12, tip[0], 10, C["tx"], anchor="center")
        for it in cv.find_all():
            if it > mark: cv.addtag_withtag("ovl", it)
        place_marks()
    import tkinter.font as _tkf
    msg_font = _tkf.Font(root=win, family="Segoe UI", size=-int(10 * S))
    def H_vis():
        try: return cv.winfo_height() / S
        except Exception: return 600
    gtip = get_tip(cv)
    BAR_TIPS = {"share": "Share preset (copies a code)", "import": "Import preset from code"}
    def song_tip(h):
        """(key, text, screen rect) for a hovered song cover / disabled switch, else None."""
        if not h or st["drag"]: return None
        if h[0] == "pack": return (h, "%s \u2014 %d songs (click to show)" % (PACK["name"], NB), (EX - ER, TY - ER - 3, EX + ER, TY + ER + 3))
        if h[0] == "packx": bx = back_xy()[0]; return (h, "Fold %s songs" % PACK["name"], (bx - 11, TY - 14, bx + 11, TY + 14))
        if h[0] in ("tray", "chip"):
            p = pools()
            s_ = SONGS[h[1]] if h[0] == "tray" else SONG_BY_URI.get(p[CIV_LIST[h[1]][0]][h[2]])
            if not s_: return None
            cx, cy = tray_xy(h[1]) if h[0] == "tray" else chip_xy(h[1], h[2])
            r = tray_rad(h[1]) if h[0] == "tray" else 15
            if h[0] == "chip" and not (LT <= cy <= BOT): return None
            return (h, "%s \u2014 %s" % (s_[1], s_[2]) if s_[2] else s_[1], (cx - r, cy - r - 3, cx + r, cy + r + 3))
        if h[0] == "swoff": return (h, "Add a song first", (h[2] - 12, h[3] - 30, h[2] + 12, h[3] - 6))
        if h[0] in ("share", "import") and ed["page"] == "overview":
            cx = (W - 106) if h[0] == "share" else (W - 58)
            return (h, BAR_TIPS[h[0]], (cx - 16, BAR_Y - 16, cx + 16, BAR_Y + 16))
        return None
    def set_hover(h):
        """Hover changed: update the overlay now, show the tooltip after a short delay."""
        OV = ("back", "card", "cardtog", "swoff", "preset", "share", "import", "pm", "pnew")
        redraw = ed["page"] == "overview" and (st["hov"] or ("",))[0] in OV or (h or ("",))[0] in OV
        st["hov"] = h; st["msg"] = None; st["tipok"] = False
        if redraw and ed["page"] == "overview": draw()                 # card hover highlight
        t_ = song_tip(h)
        if t_ and not (st.get("press") and not st.get("released", True)):
            k_, txt, (a0, b0, a1, b1) = t_
            gtip.request(("intro",) + tuple(k_), txt, canvas_rect(cv, (a0 * S, b0 * S, a1 * S, b1 * S)), S, cv)
        else: gtip.hide()
        overlay()
        cur = "hand2" if h and h[0] in ("pack", "packx", "tray", "chip", "x", "undo", "reset", "plus", "tabtog", "card", "cardtog", "back",
                                        "preset", "share", "import", "pm", "pnew") else ("no" if h and h[0] == "swoff" else "")
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
        elif h and h[0] in ("pack", "packx") and ph == h: pack_set(h[0] == "pack"); return
        elif ed["page"] == "overview" and st.get("menu") and not (h and h[0] in ("pm", "pnew", "menu", "preset")):
            st["menu"] = None                              # click outside an open menu just closes it
        elif h and h[0] == "preset": st["menu"] = None if st.get("menu") == "presets" else "presets"
        elif h and h[0] == "pm": switch_preset(h[1]); return
        elif h and h[0] == "pnew": st["menu"] = None; draw(); win.after_idle(lambda: name_dialog("New preset", "My preset", save_preset)); return
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
    PACK_S = 0.45                                      # fold / unfold duration (s)
    def pack_set(open_):
        """Unfold (True) / fold the built-in pack; remembered in the settings. Reverses smoothly mid-way."""
        if not PACK or pk["open"] == open_: return
        pk["open"] = open_; user["intro_pack_open"] = open_; save()
        st["hov"] = None; gtip.hide(fade=False)
        if pk["job"] is None: pk["last"] = time.perf_counter(); pack_tick()
    def pack_tick():                                   # ~60 fps only while moving; no timer once settled
        pk["job"] = None
        try:
            if not win.winfo_exists(): return
        except Exception: return
        now = time.perf_counter(); dt = min(0.05, now - pk["last"]); pk["last"] = now
        goal = 1.0 if pk["open"] else 0.0; step = dt / PACK_S
        pk["t"] = min(goal, pk["t"] + step) if goal > pk["t"] else max(goal, pk["t"] - step)
        draw()
        if pk["t"] != goal: pk["job"] = win.after(16, pack_tick)
        else:
            try:
                px_, py_ = cv.winfo_pointerx() - cv.winfo_rootx(), cv.winfo_pointery() - cv.winfo_rooty()
                set_hover(hit(px_ / S, py_ / S))
            except Exception: pass
    def _pack_stop(e):
        if e.widget is win and pk["job"]:
            try: win.after_cancel(pk["job"])
            except Exception: pass
            pk["job"] = None
    win.bind("<Destroy>", _pack_stop, add="+")
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
        if inline:                                     # page: stop the preview glow timer, hand the window back
            for j_ in (pv.get("gjob"), pv.get("msgjob"), st.get("toastjob")):
                if j_:
                    try: win.after_cancel(j_)
                    except Exception: pass
            gtip.hide(fade=False)
        if inline:                                     # host swaps the panel back in FIRST, then the page goes
            later = False
            try: later = on_close() == "later"       # host may drop the page itself once its swap ran
            finally:
                if not later:
                    try: win.destroy()
                    except Exception: pass
            return
        try: win.destroy()
        except Exception: pass
        if parent is not None: parent.after(10, lambda: focus_window(parent))
    if not inline: win.protocol("WM_DELETE_WINDOW", close_editor)
    cv.bind("<Leave>", lambda e: (gtip.hide(), set_hover(None) if not st["drag"] else None))
    def esc(_=None):                                   # age page -> overview; overview: close the menu (inline: menu closed -> back to the panel)
        if ed["page"] != "overview": open_page("overview")
        elif inline and not st.get("menu"): close_editor()
        else: st.update(menu=None); draw()
    kb.bind("<Escape>", esc)
    kb.bind("<BackSpace>", lambda e: open_page("overview") if ed["page"] != "overview" else (close_editor() if inline else None))
    if not inline: set_app_icon(win)
    draw(); fetch_missing_covers()
    pvpump()
    win._ed = {"pk": pk, "pack_set": pack_set, "div_x": div_x, "back_xy": back_xy, "EX": EX, "ER": ER, "PACK": PACK, "glow_spots": glow_spots, "record": record, "undo_redo": undo_redo, "pv": pv, "cv": cv, "st": st, "pools": pools, "tray_xy": tray_xy, "chip_xy": chip_xy, "row_y": row_y, "S": S, "draw": draw,
               "ed": ed, "ages_on": ages_on, "add_custom": add_custom, "remove_custom": remove_custom, "add_dialog": add_dialog, "hist": hist, "glow_kick": glow_kick,
               "open_page": open_page, "set_age_on": set_age_on, "tray_rad": tray_rad, "CARD_Y": CARD_Y,
               "W": W, "H": H, "H_MIN": H_MIN, "OV_CARD": OV_CARD, "switch_preset": switch_preset, "save_preset": save_preset, "share": share, "import_preset": import_preset,
               "import_dialog": import_dialog, "dirty": dirty, "toast": toast, "song_tip": song_tip, "hit": hit, "BAR_Y": BAR_Y}  # tests
    win._close = close_editor                          # (host + tests)
    if inline: return win                              # the host swaps it in (already drawn: no blank frame)
    reveal(win, over=parent); note_window("editor", win); win.lift(); win.focus_force()
    return win
