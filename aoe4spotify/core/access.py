"""Shared-app access request (capstar.app) and the not-invited guide.
"""

import json, os, re, threading, time, urllib.error, urllib.parse, urllib.request
from aoe4spotify.core.runtime import VERSION, dark_window, log, release_window, reveal, set_canvas_height, set_titlebar, single_window, test_env, windows_light
from aoe4spotify.core.settings import load_config, load_user_settings, merge_user
from aoe4spotify.core.spotify import Spotify

def _own_on():
    from aoe4spotify.core import settings as _s
    return bool(_s.OWN_APP_ENABLED)
def _g_byo():
    import aoe4spotify.core.byo as _m
    return _m

def _g_gui():
    import aoe4spotify.core.gui as _m
    return _m

ACCOUNT_URL = "https://www.spotify.com/account/overview/"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
def clean_email(e):
    """One plain address (no spaces / newlines / lists), at most 100 characters - else None."""
    e = (e or "").strip()
    return e if len(e) <= 100 and EMAIL_RE.fullmatch(e) else None
def clean_name(n):
    """Display name for the request: letters, digits, space . _ - only, at most 40 characters (None if empty)."""
    n = re.sub(r"[^\w .-]", "", re.sub(r"\s", " ", str(n or "")))
    n = re.sub(r"\s+", " ", n).strip()[:40].strip()
    return n or None
ACCESS_GAP = 600                                       # one request per 10 min per install
def not_invited(code, body):
    """True when Spotify refuses this account because it isn't on the app's user list (dev-mode 403)."""
    if code != 403: return False
    t = json.dumps(body).lower() if not isinstance(body, str) else body.lower()
    return "not registered" in t or "developer dashboard" in t or "user may not be registered" in t
def access_status(sp):
    """'ok', 'blocked' or None (offline / not logged in)."""
    if not (sp and sp.tok): return None
    c, r = sp._api("GET", "/me")
    if c == 200: return "ok"
    return "blocked" if not_invited(c, r) else None
ACCESS_URL = "https://capstar.app/api/aoe4-spotify/access-request"     # capstar.app relay; holds the routine key server-side
ACCESS_PREFIX = "https://capstar.app/api/aoe4-spotify/"
def webhook_ok(url):
    """Only the capstar.app relay (test mode may also use a local fake server)."""
    if not isinstance(url, str) or not url: return False
    if url.startswith(ACCESS_PREFIX): return True
    return bool(test_env("AOE4SPOTIFY_TEST")) and (url.startswith("http://127.0.0.1:") or url.startswith("http://localhost:"))
def access_url():
    """The access-request endpoint. Test mode can override it via AOE4SPOTIFY_ACCESS_URL ('' = not set up)."""
    if test_env("AOE4SPOTIFY_TEST") and os.environ.get("AOE4SPOTIFY_ACCESS_URL") is not None:
        return os.environ["AOE4SPOTIFY_ACCESS_URL"]
    return ACCESS_URL
ACCESS_MSG = {"bad": "That email wasn't accepted, check it and try again",
              "busy": "Too many requests, try again later",
              "down": "Couldn't reach the server, try later",
              "error": "Couldn't send, try again"}
def send_access_request(cfg=None, email=None, name=None, now=None):
    """POST one request to the capstar.app relay (no key in the app).
    Returns 'sent', 'wait', 'off', 'bad' (invalid email / HTTP 400), 'busy' (429), 'down' (502/503/network) or 'error'.
    Only ever called from the 'Send request' button."""
    url = access_url(); now = now or time.time()
    if not webhook_ok(url): return "off"
    email = clean_email(email); name = clean_name(name)
    if not email: return "bad"
    u = load_user_settings()
    if now - float(u.get("access_last") or 0) < ACCESS_GAP: return "wait"
    hdr = {"Content-Type": "application/json", "User-Agent": "AoE4Spotify/" + VERSION}
    body = {"email": email}
    if name: body["name"] = name
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r: code = r.status
    except urllib.error.HTTPError as e: code = e.code
    except Exception as e: log("Access request failed: %s" % type(e).__name__); return "down"     # never logs the URL
    if not 200 <= code < 300:
        log("Access request failed: HTTP %s" % code)
        return {400: "bad", 429: "busy", 502: "down", 503: "down"}.get(code, "error")
    merge_user({"access_last": now, "access_pending": True}); log("Access request sent")
    return "sent"
ACCESS_THEMES = {   # soft, no pure white / pure black; same Spotify green family in both
    "dark":  dict(bg="#171717", card="#222222", tx="#e6e6e3", mu="#a3a29f", g="#1db954", gtx="#0e1a12", gact="#2fcf68", gdis="#35503f",
                  gdtx="#5f7a68", b2="#303030", b2a="#3a3a3a", b2tx="#e6e6e3", dis="#6c6c6c", ent="#2c2c2c", enttx="#ececea", err="#e8958c",
                  pg=(46, 46, 46), pgbar=(34, 34, 34), pglab=(170, 170, 166), pgline=(78, 78, 78), hl=(30, 66, 44), hlo=(29, 185, 84), hltx=(232, 232, 228)),
    "light": dict(bg="#efeeea", card="#e3e1dc", tx="#2b2b2a", mu="#62615d", g="#1a9f4a", gtx="#f4f3ef", gact="#178c41", gdis="#a9c8b3",
                  gdtx="#e8efe9", b2="#d4d2cc", b2a="#c9c7c1", b2tx="#2b2b2a", dis="#9a9893", ent="#f6f5f1", enttx="#262625", err="#b4473c",
                  pg=(240, 239, 235), pgbar=(204, 202, 197), pglab=(88, 88, 85), pgline=(206, 204, 199), hl=(208, 232, 214), hlo=(26, 159, 74), hltx=(36, 36, 34)),
}
def access_dialog(parent=None, on_allowed=None, name=None, recheck_ms=60000, on_own=None):
    """Simple 3-step 'Not invited yet' guide. Everything is drawn on one canvas from 4x-supersampled images on a
    strict grid (cards r=12, pill buttons, box r=8); follows the Windows light/dark theme live.
    Rechecks every minute; closes and calls on_allowed() once access works."""
    if not single_window("access", "AoE4 Spotify - Get access"): return None
    import tkinter as tk, webbrowser as wb
    from PIL import Image, ImageDraw, ImageTk, ImageFont
    own = parent is None
    win = tk.Tk() if own else tk.Toplevel(parent)
    if own: _g_gui().install_edit_menu(win)
    if own: win.withdraw()
    th = {"light": windows_light()}; P = lambda: ACCESS_THEMES["light" if th["light"] else "dark"]
    dark_window(win, P()["bg"]); win.title("AoE4 Spotify"); win.resizable(False, False)
    win.bind("<Destroy>", lambda e: release_window("access") if e.widget is win else None, add="+")
    S = win.winfo_fpixels("1i") / 96.0; F = lambda sz, b=True: ("Segoe UI", -int(round(sz * S)), "bold" if b else "normal")
    cfg = load_config(); st = {"sent": False, "job": None, "clip": None, "allowed": False, "hov": None, "focus": False, "b3": "disabled", "b3t": "Send request", "note": None}
    on = webhook_ok(access_url())
    st["note"] = ("" if on else "Requests not set up yet", "mu")
    # ---- grid (logical px)
    W = 500; M = 20; PAD = 18; BD = 36; GAP = 12
    BX = M + PAD + BD / 2                               # badge centre x (all steps)
    CX = M + PAD + BD + 14                              # card content left edge (titles, buttons, picture, box)
    CR = W - M - PAD                                    # card content right edge
    HDR = 114                                           # cards start below the own-app link
    H1, H2, H3 = 114, 233, 196                          # card heights: 18 px below the last content in every card
    Y1 = HDR; Y2 = Y1 + H1 + GAP; Y3 = Y2 + H2 + GAP; HH = Y3 + H3 + M
    TY = 30                                             # step title centre, from the card top (= badge centre)
    IW, IH = W - M - PAD - CX, 118                      # illustration box
    BOXW, BOXH = 300, 44
    G = {"lay": dict(W=W, BX=BX, CX=CX, CR=CR, Y=(Y1, Y2, Y3), H=(H1, H2, H3), TY=TY, GAP=GAP, BOXW=BOXW, BOXH=BOXH, IW=IW, IH=IH)}
    cv = tk.Canvas(win, width=_g_gui().even_px(W, S), height=_g_gui().even_px(HH, S), highlightthickness=0, bd=0, bg=P()["bg"]); cv.pack()
    imgs = {}
    def rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    def rr_img(w, h, r, fill, outline=None, ow=0.0):
        k = ("rr", w, h, r, fill, outline, ow)
        if k not in imgs:
            Q = 4; Wp, Hp = _g_gui().even_px(w, S), _g_gui().even_px(h, S); im = Image.new("RGBA", (Wp * Q, Hp * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
            if outline and ow:
                d.rounded_rectangle([0, 0, Wp * Q - 1, Hp * Q - 1], r * S * Q, fill=rgb(outline))
                o = ow * S * Q; d.rounded_rectangle([o, o, Wp * Q - 1 - o, Hp * Q - 1 - o], max(0, r * S * Q - o), fill=rgb(fill))
            else: d.rounded_rectangle([0, 0, Wp * Q - 1, Hp * Q - 1], r * S * Q, fill=rgb(fill))
            imgs[k] = ImageTk.PhotoImage(im.resize((Wp, Hp), Image.LANCZOS), master=win)
        return imgs[k]
    def badge_img(n, fill, fg):
        k = ("badge", n, fill, fg)
        if k not in imgs:
            Q = 4; D = _g_gui().even_px(BD, S); B = D * Q; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse([0, 0, B - 1, B - 1], fill=rgb(fill))
            tl = Image.new("RGBA", (B, B), (0, 0, 0, 0))
            try: fnt = ImageFont.truetype("segoeuib.ttf", int(17 * S * Q))
            except Exception: fnt = None
            ImageDraw.Draw(tl).text((B / 2, B / 2), str(n), font=fnt, fill=rgb(fg), anchor="mm")
            im = Image.alpha_composite(im, _g_gui().ink_centre(tl)); imgs[k] = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=win)
        return imgs[k]
    def check_img(fill, fg):
        k = ("check", fill, fg)
        if k not in imgs:
            Q = 4; D = _g_gui().even_px(26, S); B = D * Q; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
            d.ellipse([0, 0, B - 1, B - 1], fill=rgb(fill)); u = B / 26.0
            d.line([(7.5 * u, 13.5 * u), (11.2 * u, 17.2 * u), (18.5 * u, 9.3 * u)], fill=rgb(fg), width=int(2.6 * u), joint="curve")
            for x, y in ((7.5, 13.5), (18.5, 9.3)): d.ellipse([(x - 1.3) * u, (y - 1.3) * u, (x + 1.3) * u, (y + 1.3) * u], fill=rgb(fg))
            imgs[k] = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=win)
        return imgs[k]
    def illustration():
        p = P(); k_ = ("illu", th["light"])
        if k_ in imgs: return imgs[k_]
        Q = 4; Wp, Hp = _g_gui().even_px(IW, S), _g_gui().even_px(IH, S); u = Wp * Q / IW; L = lambda v: v * u; SW = 1.8                # one stroke width everywhere
        im = Image.new("RGBA", (Wp * Q, Hp * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        try:
            fb = ImageFont.truetype("segoeuib.ttf", int(L(10.5))); fr = ImageFont.truetype("segoeui.ttf", int(L(10))); fh = ImageFont.truetype("segoeuib.ttf", int(L(11.5)))
        except Exception: fb = fr = fh = None
        def line(pts, c, w=SW):
            d.line([(L(x), L(y)) for x, y in pts], fill=c, width=int(round(L(w))), joint="curve")
            for x, y in (pts[0], pts[-1]): r = w / 2; d.ellipse([L(x - r), L(y - r), L(x + r), L(y + r)], fill=c)   # round caps
        pw = (IW - 24) / 2                                   # two equal mini pages, 24 px gutter for the arrow
        lx0, lx1, rx0, rx1 = 0, pw, IW - pw, IW
        for x0, x1 in ((lx0, lx1), (rx0, rx1)): d.rounded_rectangle([L(x0), 0, L(x1) - 1, Hp * Q - 1], L(10), fill=p["pg"])
        # left page: Account -> pencil row
        d.text((L(lx0 + 12), L(18)), "Account", fill=p["pglab"], font=fh, anchor="lm")
        ry0, ry1 = 34, 62; cy = (ry0 + ry1) / 2
        d.rounded_rectangle([L(lx0 + 8), L(ry0), L(lx1 - 8), L(ry1)], L(8), fill=p["hl"], outline=p["hlo"], width=int(round(L(SW))))
        d.rounded_rectangle([L(lx0 + 14), L(cy - 8), L(lx0 + 30), L(cy + 8)], L(4), fill=p["pgline"])
        pc = (lx0 + 22, cy)                                   # pencil: shaft + tip, 45 degrees, crisp
        line([(pc[0] - 3.2, pc[1] + 3.2), (pc[0] + 3.6, pc[1] - 3.6)], p["hltx"], 2.2)
        d.polygon([(L(pc[0] - 5.2), L(pc[1] + 5.2)), (L(pc[0] - 4.6), L(pc[1] + 2.4)), (L(pc[0] - 2.4), L(pc[1] + 4.6))], fill=p["hltx"])
        d.text((L(lx0 + 37), L(cy)), "Edit personal info", fill=p["hltx"], font=fb, anchor="lm")
        line([(lx1 - 20, cy - 4), (lx1 - 16, cy), (lx1 - 20, cy + 4)], p["hltx"])
        for i, w_ in enumerate((0.62, 0.45)): d.rounded_rectangle([L(lx0 + 12), L(78 + i * 15), L(lx0 + 12 + (pw - 24) * w_), L(84 + i * 15)], L(3), fill=p["pgline"])
        # pointer (classic proportions: 12 x 18), tip on the row, white-ish edge so it reads on both themes
        px, py = lx1 - 44, cy + 2
        ptr = [(0, 0), (0, 15.5), (3.8, 12.2), (6.6, 18), (9.2, 16.8), (6.5, 11.2), (11.4, 11.2)]
        d.polygon([(L(px + x), L(py + y)) for x, y in ptr], fill=p["hltx"], outline=p["pg"], width=int(round(L(1.2))))
        # arrow between the pages
        ax0, ax1, ay = lx1 + 6, rx0 - 6, IH / 2
        line([(ax0, ay), (ax1, ay)], p["hlo"], 2.0); line([(ax1 - 4.5, ay - 4.5), (ax1, ay), (ax1 - 4.5, ay + 4.5)], p["hlo"], 2.0)
        # right page: Email field
        d.rounded_rectangle([L(rx0 + 12), L(15), L(rx0 + 12 + (pw - 24) * 0.55), L(21)], L(3), fill=p["pgline"])
        d.text((L(rx0 + 12), L(42)), "Email", fill=p["pglab"], font=fb, anchor="lm")
        d.rounded_rectangle([L(rx0 + 8), L(52), L(rx1 - 8), L(78)], L(8), fill=p["hl"], outline=p["hlo"], width=int(round(L(SW))))
        d.text((L(rx0 + 16), L(65)), "you@example.com", fill=p["hltx"], font=fr, anchor="lm")
        d.rounded_rectangle([L(rx0 + 12), L(92), L(rx0 + 12 + (pw - 24) * 0.7), L(98)], L(3), fill=p["pgline"])
        imgs[k_] = ImageTk.PhotoImage(im.resize((Wp, Hp), Image.LANCZOS), master=win); return imgs[k_]
    # ---- live widgets: email box (Entry on a rounded image), placeholder, check
    ev = tk.StringVar()
    e_ = tk.Entry(cv, textvariable=ev, font=F(15, False), relief="flat", bd=0, highlightthickness=0, bg=P()["ent"], fg=P()["enttx"])
    ph = tk.Label(e_, text="your Spotify email", font=F(15, False), cursor="xterm", bd=0, bg=P()["ent"], fg=P()["dis"])
    ck = tk.Label(cv, text="", bd=0, bg=P()["card"])                      # text kept for tests; shows the drawn check image
    def ph_upd(*_):
        if ev.get(): ph.place_forget()
        else: ph.place(x=0, rely=0.5, anchor="w")
    ph.bind("<Button-1>", lambda e: (e_.focus_set(), e_.icursor("end")))
    e_.bind("<FocusIn>", lambda e: (st.update(focus=True), draw())); e_.bind("<FocusOut>", lambda e: (st.update(focus=False), draw()))
    done = tk.Frame(win, bg=P()["bg"])
    class Btn:                                          # pill button drawn on the canvas; Tk-button-like config/state for callers
        def __init__(s, key): s.key = key
        def __getitem__(s, o): return st["b3"] if o == "state" else st["b3t"]
        def config(s, state=None, text=None, **_):
            if state: st["b3"] = state
            if text: st["b3t"] = text
            draw()
        configure = config
    class Note:
        def __getitem__(s, o): return st["note"][0]
        def config(s, text=None, fg=None, **_): st["note"] = (text if text is not None else st["note"][0], "err" if fg else st["note"][1]); draw()
        configure = config
    b3, note = Btn("b3"), Note()
    def valid(): return bool(EMAIL_RE.match(ev.get().strip()))
    def text(x, y, s_, sz, key, bold=True, anchor="w", tags=()):
        return cv.create_text(x * S, y * S, text=s_, fill=P()[key], font=F(sz, bold), anchor=anchor, tags=tags)
    def pill(x, y, w, h, label, kind, tag, enabled=True):
        p = P(); hv = st["hov"] == tag and enabled
        if kind == "g": fill, fg = (p["gact"] if hv else p["g"]) if enabled else p["gdis"], "gtx" if enabled else "gdtx"
        else: fill, fg = p["b2a"] if hv else p["b2"], "b2tx"
        cv.create_image(x * S, y * S, anchor="nw", image=rr_img(w, h, h / 2, fill), tags=(tag,))
        text(x + w / 2, y + h / 2, label, 15, fg, True, "center", (tag,))
    def draw():
        p = P()
        for i in cv.find_all():
            if "win" not in cv.gettags(i): cv.delete(i)
        cv.configure(bg=p["bg"]); win.configure(bg=p["bg"])
        e_.configure(bg=p["ent"], fg=p["enttx"], insertbackground=p["enttx"], disabledbackground=p["ent"]); ph.configure(bg=p["ent"], fg=p["dis"])
        ok_ = valid(); ck.configure(bg=p["card"], image=check_img(p["g"], p["gtx"]) if ok_ else "", text="\u2714" if ok_ else "")
        st["b3"] = "normal" if (on and ok_ and not st["sent"] and st["b3t"] == "Send request") else "disabled"
        text(M + 8, 38, "Not invited yet", 26, "tx", tags=("hdr",)); text(M + 8, 70, "Ask for access in 3 easy steps.", 15, "mu", False, tags=("hdr",))
        if _own_on(): text(M + 8, 92, "Or use your own Spotify app", 13, "g", False, tags=("byo",))
        if st.get("donev"):                            # Done: same canvas, same header, same window size
            for i in cv.find_withtag("win"): cv.itemconfigure(i, state="hidden")
            if not cv.find_withtag("dwin"): cv.create_window((M + 8) * S, HDR * S, anchor="nw", window=done, tags=("dwin",))
            return
        titles = ("Open your Spotify page", "Find your email and copy it", "Paste or type your Spotify email")
        h3 = H3 if st["note"][0] else H3 - 24              # no note line: card 3 ends 18 px under the button
        hh = Y3 + h3 + M
        set_canvas_height(cv, _g_gui().even_px(hh, S))
        G["lay"]["H"] = (H1, H2, h3)
        for i, (y0, h) in enumerate(zip((Y1, Y2, Y3), (H1, H2, h3))):
            cv.create_image(M * S, y0 * S, anchor="nw", image=rr_img(W - 2 * M, h, 12, p["card"]))
            cv.create_image(BX * S, (y0 + TY) * S, image=badge_img(i + 1, p["g"], p["gtx"]), tags=("badge",))
            text(CX, y0 + TY, titles[i], 17, "tx", tags=("title",))
        pill(CX, Y1 + 52, 200, 44, "Open Spotify page", "b2", "b1")
        cv.create_image(CX * S, (Y2 + 52) * S, anchor="nw", image=illustration(), tags=("illu",))
        text(CX, Y2 + 52 + IH + 16, "Click \u201cEdit personal info\u201d (the row with the pencil).", 14, "mu", False)
        text(CX, Y2 + 52 + IH + 36, "Then select your Email and press Ctrl + C.", 14, "mu", False)
        by = Y3 + 52
        cv.create_image(CX * S, by * S, anchor="nw", image=rr_img(BOXW, BOXH, 8, p["ent"], p["g"] if st["focus"] else p["b2"], 1.5), tags=("box",))
        if not cv.find_withtag("win"):                  # embedded widgets are created once and kept on top
            cv.create_window((CX + 14) * S, (by + BOXH / 2) * S, anchor="w", window=e_, width=int((BOXW - 28) * S), height=int(26 * S), tags=("win",))
            cv.create_window((CX + BOXW + 14) * S, (by + BOXH / 2) * S, anchor="w", window=ck, tags=("win",))
        cv.tag_raise("win")
        pill(CX, by + BOXH + 14, 200, 44, st["b3t"], "g", "b3", st["b3"] == "normal")
        if st["note"][0]: text(CX, by + BOXH + 14 + 44 + 16, st["note"][0], 13, st["note"][1], False)
    def hit(e):
        it = cv.find_overlapping(e.x, e.y, e.x, e.y)
        for i in reversed(it):
            for t in cv.gettags(i):
                if t in ("b1", "b3", "byo"): return t
    def motion(e):
        h = hit(e)
        if h != st["hov"]:
            st["hov"] = h; cv.config(cursor="hand2" if h in ("b1", "byo") or (h == "b3" and st["b3"] == "normal") else ""); draw()
    def open_own():
        def after():
            try: win.destroy()
            except Exception: pass
            if on_own: on_own()
        _g_byo().byo_dialog(win, on_saved=after, on_shared=after)
    def click(e):
        h = hit(e)
        if h == "b1": wb.open(ACCOUNT_URL)
        elif h == "b3": send()
        elif h == "byo" and _own_on(): open_own()
    cv.bind("<Motion>", motion); cv.bind("<ButtonRelease-1>", click); cv.bind("<Leave>", lambda e: motion(e) if False else (st.update(hov=None), draw()))
    def refresh(*_): ph_upd(); draw()
    ev.trace_add("write", refresh)
    def retheme(): imgs.clear(); set_titlebar(win, not th["light"]); draw(); show_done() if (st["sent"] or st.get("donev")) else None
    uiq = []
    def poll_clip():                                   # fills the box as soon as an email is copied; also follows the theme
        while uiq:
            uiq.pop(0)()
            if st["allowed"]: return
        try:
            c = win.clipboard_get().strip()
            if c != st["clip"]:
                st["clip"] = c
                if EMAIL_RE.match(c) and not st["sent"]: ev.set(c)
        except Exception: pass
        st["tick"] = st.get("tick", 0) + 1
        if st["tick"] % 8 == 0:                        # ~2 s: Windows light/dark switch while open
            lt = windows_light()
            if lt != th["light"]: th["light"] = lt; retheme()
        try: win.after(250, poll_clip)
        except Exception: pass
    def show_done():
        p = P(); st["donev"] = True; done.configure(bg=p["bg"])
        for w_ in done.winfo_children(): w_.destroy()
        for t_, sz, key, pady in (("\u2714  Done!", 30, "g", (14, 0)), ("You'll get access in about a minute.", 20, "tx", (8, 6)),
                                  ("Keep this window open or reopen the app later.\nIt continues by itself when it works.", 15, "mu", (0, 30))):
            tk.Label(done, text=t_, font=F(sz, sz != 15), bg=p["bg"], fg=p[key], justify="left").pack(anchor="w", pady=tuple(int(v * S) for v in pady))
        draw()
    def send():
        if not (on and valid()) or st["sent"] or st["b3t"] != "Send request": return
        b3.config(text="Sending\u2026"); em = ev.get().strip()
        def go():
            r = send_access_request(cfg, em, name)
            def fin():
                st["b3t"] = "Send request"
                if r in ("sent", "wait"): st["sent"] = True; show_done()     # 'wait': asked recently - same friendly end
                else: note.config(text=ACCESS_MSG.get(r, ACCESS_MSG["error"]), fg="err")
                win._res = r
            uiq.append(fin)                            # Tk is only touched on the UI thread
        threading.Thread(target=go, daemon=True).start()
    def recheck():
        def go():
            try: r = access_status(Spotify(load_config()))
            except Exception: r = None
            if r == "ok": uiq.append(allowed)
        threading.Thread(target=go, daemon=True).start()
        st["job"] = win.after(recheck_ms, recheck)
    def allowed():
        if st["allowed"]: return
        st["allowed"] = True; merge_user(remove=("access_pending",))
        try: win.destroy()
        except Exception: pass
        if on_allowed: on_allowed()
    ph_upd(); draw()
    if load_user_settings().get("access_pending") and time.time() - float(load_user_settings().get("access_last") or 0) < ACCESS_GAP:
        st["sent"] = True; show_done()
    poll_clip(); st["job"] = win.after(recheck_ms, recheck)
    reveal(win, over=parent) if parent is not None else reveal(win)
    set_titlebar(win, not th["light"])
    if not st["sent"]:
        try: win.focus_force(); e_.focus_set()                  # ready to type / Ctrl+V straight away
        except Exception: pass
    win._acc = {"ev": ev, "send": send, "b3": b3, "ck": ck, "st": st, "note": note, "done": done, "recheck": recheck, "allowed": allowed,
                "th": th, "retheme": retheme, "show_done": show_done, "P": P, "entry": e_, "ph": ph, "cv": cv, "G": G, "draw": draw}
    if own:
        win.mainloop() if not test_env("AOE4SPOTIFY_TEST_NOLOOP") else None
    return win
