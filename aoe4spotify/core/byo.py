"""Bring-your-own Spotify app: the user creates a dashboard app and pastes its Client ID.

The shared client id shipped with the installer stays the default. A saved id lives in
the per-user settings overlay, so an update does not wipe it.
"""

from aoe4spotify.core.access import ACCESS_THEMES, ACCOUNT_URL
from aoe4spotify.core.runtime import REDIRECT, dark_window, log, release_window, reveal, set_titlebar, single_window, test_env, windows_light
from aoe4spotify.core.settings import clear_own_client, client_id_ok, load_user_settings, save_own_client, using_own_app

def _g_gui():
    import aoe4spotify.core.gui as _m
    return _m

DASHBOARD_URL = "https://developer.spotify.com/dashboard"
APP_DOCS_URL = "https://developer.spotify.com/documentation/web-api/concepts/apps"

def byo_dialog(parent=None, on_saved=None, on_shared=None, problem=False):
    from aoe4spotify.core import settings as _s
    if not _s.OWN_APP_ENABLED: return None
    """One screen: create a Spotify app, allow yourself, paste the Client ID.

    on_saved runs after a client id is stored. on_shared runs after switching back
    to the shared app. Either way the previous Spotify login is dropped when the
    id actually changes, and the caller logs in again.
    """
    if not single_window("byo", "AoE4 Spotify - Your Spotify app"): return None
    import tkinter as tk, webbrowser as wb
    own = parent is None
    win = tk.Tk() if own else tk.Toplevel(parent)
    if own: _g_gui().install_edit_menu(win)
    th = {"light": windows_light()}
    P = lambda: ACCESS_THEMES["light" if th["light"] else "dark"]
    p0 = P()
    dark_window(win, p0["bg"]); win.title("AoE4 Spotify"); win.resizable(False, False)
    win.bind("<Destroy>", lambda e: release_window("byo") if e.widget is win else None, add="+")
    S = win.winfo_fpixels("1i") / 96.0
    F = lambda sz, b=True: ("Segoe UI", -int(round(sz * S)), "bold" if b else "normal")
    st = {"clip": None, "note": "", "copied": False}
    ev = tk.StringVar()
    root = tk.Frame(win, bg=p0["bg"])
    root.pack(fill="both", expand=True)
    groups = []

    def num(parent_, n):
        b = tk.Label(parent_, text=str(n), font=F(12), width=2, padx=0, pady=0)
        b._kind = "num"; return b

    def title(parent_, s):
        w = tk.Label(parent_, text=s, font=F(13), anchor="w")
        w._kind = "title"; return w

    def body(parent_, s):
        w = tk.Label(parent_, text=s, font=F(11, False), anchor="w", justify="left", wraplength=int(430 * S))
        w._kind = "body"; return w

    def ghost(parent_, s, cmd):
        w = tk.Button(parent_, text=s, font=F(11), relief="flat", bd=0, padx=int(12 * S), pady=int(6 * S),
                      cursor="hand2", command=cmd)
        w._kind = "ghost"; return w

    def card():
        g = tk.Frame(root, padx=int(14 * S), pady=int(10 * S))
        g.pack(fill="x", padx=int(16 * S), pady=(0, int(8 * S)))
        groups.append(g); return g

    head = tk.Frame(root, bg=p0["bg"]); head.pack(fill="x", padx=int(18 * S), pady=(int(16 * S), int(8 * S)))
    h1 = tk.Label(head, text="Use your own Spotify app", font=F(18), anchor="w"); h1.pack(anchor="w")
    sub = tk.Label(head, text="One-time setup. You won't need an allowlist spot.", font=F(11, False), anchor="w", justify="left")
    sub._kind = "sub"; sub.pack(anchor="w", pady=(int(2 * S), 0))
    err = tk.Label(root, text="", font=F(11, False), anchor="w", justify="left", wraplength=int(460 * S))
    err._kind = "err"; err.pack(fill="x", padx=int(18 * S), pady=(0, int(8 * S)))

    def paint():
        p = P()
        win.configure(bg=p["bg"]); root.configure(bg=p["bg"]); head.configure(bg=p["bg"])
        h1.configure(bg=p["bg"], fg=p["tx"]); sub.configure(bg=p["bg"], fg=p["mu"])
        msg = st["note"] or ("Spotify doesn't list this account on your app yet. Add your email under User Management, then save again." if problem and not st["note"] else "")
        err.configure(text=msg, bg=p["bg"], fg=p["err"])
        if not msg: err.pack_forget()
        else: err.pack(fill="x", padx=int(18 * S), pady=(0, int(8 * S)), before=groups[0])
        def apply(c, bg):
            kind = getattr(c, "_kind", "")
            if kind == "title": c.configure(bg=bg, fg=p["tx"])
            elif kind == "row": c.configure(bg=bg)
            elif kind == "body": c.configure(bg=bg, fg=p["mu"])
            elif kind == "entry": c.configure(bg=p["ent"], fg=p["enttx"], insertbackground=p["enttx"], readonlybackground=p["ent"])
            elif kind == "ph": c.configure(bg=p["ent"], fg=p["dis"])
            elif kind == "ghost": c.configure(bg=p["b2"], fg=p["b2tx"], activebackground=p["b2a"], activeforeground=p["b2tx"])
            elif kind == "go":
                on = client_id_ok(ev.get().strip())
                c.configure(state="normal" if on else "disabled", bg=p["g"] if on else p["gdis"],
                            fg=p["gtx"] if on else p["gdtx"], activebackground=p["gact"] if on else p["gdis"],
                            activeforeground=p["gtx"] if on else p["gdtx"], disabledforeground=p["gdtx"])
            elif kind == "num": c.configure(bg=p["g"], fg=p["gtx"])
            for ch in c.winfo_children(): apply(ch, p["card"] if kind in ("title", "row") else bg)
        for group in groups:
            group.configure(bg=p["card"])
            for c in group.winfo_children(): apply(c, p["card"])
        link.configure(bg=p["bg"], fg=p["g"], activebackground=p["bg"], activeforeground=p["gact"])
        foot.configure(bg=p["bg"])
        docs_link.configure(bg=p["bg"], fg=p["g"])
        set_titlebar(win, not th["light"])

    c1 = card(); num(c1, 1).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, int(10 * S)))
    title(c1, "Create an app").grid(row=0, column=1, sticky="w")
    body(c1, "Open the dashboard and log in with the Spotify account you play with. Click Create app, name it AoE4 Spotify, tick Web API, and save.").grid(row=1, column=1, sticky="w")
    ghost(c1, "Open Spotify Dashboard", lambda: wb.open(DASHBOARD_URL)).grid(row=2, column=1, sticky="w", pady=(int(8 * S), 0))

    c2 = card(); num(c2, 2).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, int(10 * S)))
    title(c2, "Add this redirect").grid(row=0, column=1, sticky="w")
    body(c2, "In the app (on the create form, or under Settings), add this address and click Add. It has to match exactly.").grid(row=1, column=1, sticky="w")
    row2 = tk.Frame(c2); row2._kind = "row"; row2.grid(row=2, column=1, sticky="w", pady=(int(8 * S), 0))
    uri = tk.Entry(row2, font=F(11, False), relief="flat", width=34, bd=0)
    uri._kind = "entry"; uri.insert(0, REDIRECT); uri.configure(state="readonly"); uri.pack(side="left", ipady=int(6 * S), ipadx=int(6 * S))
    def copy_uri():
        try:
            win.clipboard_clear(); win.clipboard_append(REDIRECT); st["clip"] = REDIRECT; st["copied"] = True
            copy_btn.configure(text="Copied")
            win.after(1200, lambda: copy_btn.configure(text="Copy"))
        except Exception: pass
    copy_btn = ghost(row2, "Copy", copy_uri); copy_btn.pack(side="left", padx=(int(8 * S), 0))

    c3 = card(); num(c3, 3).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, int(10 * S)))
    title(c3, "Add yourself").grid(row=0, column=1, sticky="w")
    body(c3, "Open Settings, then User Management, then Add user. Use the email on your Spotify account. If you're already on the list, this step is done.").grid(row=1, column=1, sticky="w")
    ghost(c3, "Open your Spotify email", lambda: wb.open(ACCOUNT_URL)).grid(row=2, column=1, sticky="w", pady=(int(8 * S), 0))

    c4 = card(); num(c4, 4).grid(row=0, column=0, rowspan=2, sticky="n", padx=(0, int(10 * S)))
    title(c4, "Paste the Client ID").grid(row=0, column=1, sticky="w")
    body(c4, "On the app page, copy Client ID. Not the Client Secret. Copying it fills this box.").grid(row=1, column=1, sticky="w")
    box = tk.Frame(c4); box._kind = "row"; box.grid(row=2, column=1, sticky="ew", pady=(int(8 * S), 0))
    e_ = tk.Entry(box, textvariable=ev, font=F(13, False), relief="flat", width=34, bd=0)
    e_._kind = "entry"; e_.pack(side="left", ipady=int(6 * S), ipadx=int(6 * S))
    ph = tk.Label(e_, text="paste the Client ID", font=F(12, False), cursor="xterm"); ph._kind = "ph"
    def ph_upd(*_):
        if ev.get(): ph.place_forget()
        else: ph.place(x=int(2 * S), rely=0.5, anchor="w")
        paint()
    ph.bind("<Button-1>", lambda e: e_.focus_set())
    def save():
        r = save_own_client(ev.get())
        if r != "saved":
            st["note"] = "That isn't a Client ID. Copy the 32-character Client ID, not the Client Secret."
            paint(); return
        done("saved")
    go = tk.Button(box, text="Save and log in", font=F(11), relief="flat", bd=0, padx=int(12 * S), pady=int(6 * S),
                   cursor="hand2", command=save)
    go._kind = "go"; go.pack(side="left", padx=(int(8 * S), 0))

    def use_shared():
        clear_own_client(); done("shared")
    foot = tk.Frame(root, bg=p0["bg"]); foot.pack(fill="x", padx=int(18 * S), pady=(int(2 * S), int(14 * S)))
    link = tk.Button(foot, text="Use the shared app instead", font=F(11, False), relief="flat", bd=0,
                     cursor="hand2", command=use_shared)
    link._kind = "link"; link.pack(anchor="w")
    def open_docs(_=None): wb.open(APP_DOCS_URL)
    docs_link = tk.Label(foot, text="Spotify's app guide", font=F(10, False), cursor="hand2")
    docs_link._kind = "link"; docs_link.pack(anchor="w", pady=(int(4 * S), 0))
    docs_link.bind("<Button-1>", open_docs)

    def done(which):
        try: win.destroy()
        except Exception: pass
        cb = on_saved if which == "saved" else on_shared
        if cb:
            try: cb()
            except Exception as ex: log("Own-app setup: %r" % ex)

    def poll():
        try:
            c = win.clipboard_get().strip()
            if c != st["clip"] and client_id_ok(c) and not ev.get():
                st["clip"] = c; ev.set(c)
            elif c != st["clip"]:
                st["clip"] = c
        except Exception: pass
        try:
            lt = windows_light()
            if lt != th["light"]:
                th["light"] = lt; paint()
        except Exception: pass
        try: win.after(250, poll)
        except Exception: pass

    # header labels aren't in a card; paint() sets them. Fix kinds used above.
    ev.trace_add("write", lambda *_: ph_upd())
    cur = (load_user_settings().get("client_id") or "") if using_own_app() else ""
    if client_id_ok(cur): ev.set(cur)
    ph_upd(); paint(); poll()
    reveal(win, over=parent) if parent is not None else reveal(win)
    try: e_.focus_set()
    except Exception: pass
    win._byo = {"entry": e_, "save": save, "ev": ev, "go": go}
    if own and not test_env("AOE4SPOTIFY_TEST_NOLOOP"): win.mainloop()
    return win
