"""Paths, logging, process checks, and window helpers shared by every game.
"""

import re


import os, sys, threading, time

def _entry_file():
    """aoe4_spotify.py, whether it was imported or started as the program."""
    mod = sys.modules.get("aoe4_spotify")
    path = getattr(mod, "__file__", None) if mod is not None else None
    if not path:
        main = sys.modules.get("__main__")
        cand = getattr(main, "__file__", "") or ""
        if os.path.basename(cand).lower() in ("aoe4_spotify.py", "aoe4_spotify.pyw"):
            path = cand
    if not path:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "aoe4_spotify.py")
    return os.path.abspath(path)

def entry_py():
    """Source entry to relaunch. The installed exe does not use this."""
    return _entry_file()

FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(sys.executable if FROZEN else _entry_file())
VERSION = "1.0.9"
from aoe4spotify.core.branding import APP_ID, GITHUB_URL
ASSETS = getattr(sys, "_MEIPASS", HERE)
def _find_config():
    """Install config.json next to the exe (installer); else the copy bundled into the build (_MEIPASS)."""
    for d in (HERE, ASSETS):
        p = os.path.join(d, "config.json")
        if os.path.isfile(p): return p
    return os.path.join(HERE, "config.json")
CONFIG = _find_config()

def child_env():
    """Environment for processes we start: never pass PyInstaller's bootloader variables on."""
    env = {k: v for k, v in os.environ.items() if not (k.startswith("_PYI") or k.startswith("_MEI") or k in ("TCL_LIBRARY", "TK_LIBRARY"))}
    if FROZEN: env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env

# Steam marks the game's process tree with these (SteamGameId, SteamAppId, SteamOverlayGameId, ...): Steam then injects
# its overlay into, and counts as "the game", every process that carries them. Only the game itself may get them.
_STEAM_GAME_ENV = ("steam", "enable_vk_layer_valve")
def clean_env():
    """child_env() minus the Steam game-launch variables: for everything we start that is NOT the game (Spotify, explorer...)."""
    return {k: v for k, v in child_env().items() if not k.lower().startswith(_STEAM_GAME_ENV)}

DATA = os.path.join(os.environ.get("APPDATA") or HERE, APP_ID)
os.makedirs(DATA, exist_ok=True)
TOKEN = os.path.join(DATA, "token.json")
LOGFILE = os.path.join(DATA, "aoe4_spotify.log")
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-modify-playback-state user-read-playback-state playlist-read-private playlist-read-collaborative user-library-read"
_GROW = threading.local()


def documents_dir():
    """The real Documents folder (handles OneDrive / moved Documents)."""
    try:
        import ctypes, ctypes.wintypes as wt
        buf = ctypes.create_unicode_buffer(wt.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value: return buf.value  # CSIDL_PERSONAL
    except Exception: pass
    return os.path.join(os.path.expanduser("~"), "Documents")
def atomic_write(path, text, mode="w"):
    """Write-then-rename (never a half-written file). Retries os.replace: on Windows it fails while another
    process has the target open for a moment (PermissionError)."""
    tmp = "%s.%d.%d.tmp" % (path, os.getpid(), threading.get_ident())
    with open(tmp, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f: f.write(text)
    for i in range(20):
        try: os.replace(tmp, path); return True
        except PermissionError:
            if i == 19:
                try: os.remove(tmp)
                except OSError: pass
                raise
            time.sleep(0.05)
class FileLock:
    """Cross-process lock (a byte-range lock on <path>.lock) - also excludes threads of this process."""
    _tl = threading.Lock()
    def __init__(self, path, timeout=20.0): self.path, self.timeout, self.f = path + ".lock", timeout, None
    def __enter__(self):
        FileLock._tl.acquire(); t0 = time.time()
        try:
            self.f = open(self.path, "a+b")
            while True:
                try:
                    if sys.platform == "win32":
                        import msvcrt; self.f.seek(0); msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl; fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return self
                except OSError:
                    if time.time() - t0 > self.timeout: return self      # never deadlock: proceed unlocked
                    time.sleep(0.05)
        except Exception:
            FileLock._tl.release(); raise
    def __exit__(self, *a):
        try:
            if sys.platform == "win32":
                import msvcrt; self.f.seek(0); msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl; fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        except Exception: pass
        try: self.f.close()
        except Exception: pass
        FileLock._tl.release()
_LOG_TL = threading.local()
_SECRET_RE = re.compile(r"""(?i)\b(code|state|ubi|access_token|refresh_token|code_verifier|code_challenge)(['"]?\s*[:=]\s*['"]?)[A-Za-z0-9_\-\.~%+/]{6,}""")
def redact(msg):
    """Strip OAuth codes / states / tokens from anything that could reach the log."""
    return _SECRET_RE.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", str(msg))
def log(msg):
    line = time.strftime("%H:%M:%S ") + redact(msg)
    if getattr(_LOG_TL, "busy", False): return       # never re-enter (a stdout sink that logs would recurse)
    _LOG_TL.busy = True
    try:
        if not getattr(sys.stdout, "_aoe4_sink", False):   # windowed exe: stdout is our sink -> file only
            try: print(line, flush=True)
            except Exception: pass  # pythonw has no console
        _log_write(line)
    finally: _LOG_TL.busy = False
def _log_write(line):
    try:
        if os.path.exists(LOGFILE) and os.path.getsize(LOGFILE) > 1_000_000:   # keep the log small
            os.replace(LOGFILE, LOGFILE + ".old")
        with open(LOGFILE, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass
def proc_running(exe):
    """Is a process with this image name running? In-process Toolhelp snapshot (~1 ms) instead of spawning
    tasklist.exe (~40 ms CPU + a process launch). Falls back to tasklist off Windows / on error."""
    exe = exe.lower()
    if sys.platform == "win32":
        try:
            import ctypes, ctypes.wintypes as wt
            class PE(ctypes.Structure):
                _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                            ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                            ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                            ("szExeFile", ctypes.c_wchar * 260)]
            k = ctypes.windll.kernel32
            k.CreateToolhelp32Snapshot.restype = wt.HANDLE
            h = k.CreateToolhelp32Snapshot(2, 0)              # TH32CS_SNAPPROCESS
            if h in (None, wt.HANDLE(-1).value): raise OSError("snapshot failed")
            try:
                pe = PE(); pe.dwSize = ctypes.sizeof(PE); ok = k.Process32FirstW(wt.HANDLE(h), ctypes.byref(pe))
                while ok:
                    if pe.szExeFile.lower() == exe: return True
                    ok = k.Process32NextW(wt.HANDLE(h), ctypes.byref(pe))
                return False
            finally: k.CloseHandle(wt.HANDLE(h))
        except Exception: pass
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq %s" % exe, "/nh"], capture_output=True,
                             text=True, creationflags=0x08000000).stdout
        return exe in out.lower()
    except Exception:
        return False
NOWIN = 0x08000000  # CREATE_NO_WINDOW
_WINDOW_MUTEXES = {}
def single_window(name, title):
    """One window of each kind (panel, good-to-go, editor) per user. Returns True if this process may open it.
    Otherwise brings the existing window to the front (restoring it if minimized) and returns False.
    Separate from the switcher's single-instance guard."""
    try:
        import ctypes
        k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
        k32.CreateMutexW.restype = ctypes.c_void_p
        nm = "Local\\%s_window_%s%s" % (APP_ID, name, os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX", ""))  # suffix: tests only
        h = k32.CreateMutexW(None, False, nm)
        if k32.GetLastError() == 183:             # ERROR_ALREADY_EXISTS
            if h: k32.CloseHandle(ctypes.c_void_p(h))
            u32.FindWindowW.restype = ctypes.c_void_p
            w = None
            try:                                   # exact window recorded by the owner (titles can repeat)
                w = int(open(_hwnd_file(name)).read()) or None
                if not u32.IsWindow(ctypes.c_void_p(w)): w = None
            except Exception: w = None
            if not w and not os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX"):   # tests never touch a real window by title
                w = u32.FindWindowW(None, title)
            if w:
                if u32.IsIconic(ctypes.c_void_p(w)): u32.ShowWindow(ctypes.c_void_p(w), 9)   # SW_RESTORE
                u32.SetForegroundWindow(ctypes.c_void_p(w))
            log("%s is already open - brought it to the front" % title)
            return False
        _WINDOW_MUTEXES[name] = h
        return True
    except Exception:
        return True                               # not Windows / no ctypes: no guard
def _hwnd_file(name):
    return os.path.join(os.environ.get("TEMP", HERE), "%s_window_%s%s.hwnd" % (APP_ID, name, os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX", "")))
def note_window(name, win):
    """Remember our top-level window handle so a second launch focuses exactly this window."""
    try:
        if sys.platform == "win32": open(_hwnd_file(name), "w").write(str(int(win.wm_frame(), 16)))
    except Exception: pass
def release_window(name):
    try: os.remove(_hwnd_file(name))
    except OSError: pass
    h = _WINDOW_MUTEXES.pop(name, None)
    if h:
        try: import ctypes; ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))
        except Exception: pass
def _switcher_mutex(): return APP_ID + "SwitcherMutex" + os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX", "")
def single_instance():
    import ctypes; k = ctypes.windll.kernel32; k.CreateMutexW.restype = ctypes.c_void_p
    h = k.CreateMutexW(None, False, _switcher_mutex())
    if k.GetLastError() != 183: return True                  # ours (kept open for the life of this process)
    if h: k.CloseHandle(ctypes.c_void_p(h))                    # another switcher: don't keep its name alive
    return False
def wait_single_instance(secs=20):
    """Game restarted right after closing: the old switcher may still be finishing (~15 s). Wait for it."""
    t0 = time.time()
    while not single_instance():
        if time.time() - t0 > secs: return False
        time.sleep(1)
    return True
def switcher_running():
    import ctypes; k = ctypes.windll.kernel32; k.OpenMutexW.restype = ctypes.c_void_p
    h = k.OpenMutexW(0x00100000, False, _switcher_mutex())   # SYNCHRONIZE
    if h: k.CloseHandle(ctypes.c_void_p(h))
    return bool(h)
def test_env(name):
    """Test-only overrides (fake Steam etc.): honoured from source, or in the exe only with AOE4SPOTIFY_TEST=1,
    so a stray variable can never redirect a real install."""
    if FROZEN and os.environ.get("AOE4SPOTIFY_TEST") != "1": return None
    return os.environ.get(name) or None
def set_canvas_height(cv, px):
    """Resize a canvas without an unpainted (white) strip. Growing a shown window exposes new client area that
    Windows shows unpainted until Tk redraws at idle; first expands are slowest (new images, fonts). So: paint the
    new items at the old size, then grow and paint in the same pass."""
    px = int(px)
    if px == int(cv.cget("height")): return
    live = False
    try: live = bool(cv.winfo_toplevel().winfo_viewable()) and not getattr(_GROW, "busy", False)
    except Exception: pass
    if not live: cv.config(height=px); return
    _GROW.busy = True
    try:
        top = cv.winfo_toplevel()
        if px > int(cv.cget("height")): top.update_idletasks()
        cv.config(height=px); top.update_idletasks()
    except Exception: pass
    finally: _GROW.busy = False
def focus_window(w):
    """Front + keyboard focus, also when another app was in front (brief topmost pulse, then normal)."""
    try:
        if not w.winfo_exists(): return
        if w.state() == "iconic": w.deiconify()
        w.lift(); w.attributes("-topmost", True); w.focus_force()
        if sys.platform == "win32":
            try:
                import ctypes; ctypes.windll.user32.SetForegroundWindow(int(w.wm_frame(), 16))
            except Exception: pass
        w.after(60, lambda: w.winfo_exists() and w.attributes("-topmost", False))
    except Exception as e: log("Focus window: %r" % e)
def dark_window(win, bg):
    """Start hidden with the dark background, so a window never flashes white while it is built."""
    try: win.withdraw()
    except Exception: pass
    win.configure(bg=bg)
def place_centered(win, over=None):
    """Centre on the primary monitor's work area, or over a visible parent window."""
    try:
        if test_env("AOE4SPOTIFY_OFFSCREEN"):            # tests: map windows far off every monitor, never on screen
            win.geometry("+-30000+-30000"); return
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        wa = None
        if sys.platform == "win32":
            import ctypes, ctypes.wintypes as wt
            class MI(ctypes.Structure):
                _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
            u32 = ctypes.windll.user32; pt = wt.POINT(0, 0); flag = 1        # (0,0) + DEFAULTTOPRIMARY = primary monitor
            if over is not None and over.winfo_viewable():
                pt = wt.POINT(over.winfo_rootx() + over.winfo_width() // 2, over.winfo_rooty() + over.winfo_height() // 2); flag = 2
            u32.MonitorFromPoint.restype = ctypes.c_void_p
            mon = u32.MonitorFromPoint(pt, flag)
            mi = MI(); mi.cbSize = ctypes.sizeof(MI)
            if mon and u32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
                r = mi.rcWork; wa = (r.left, r.top, r.right, r.bottom)
        if wa is None: wa = (0, 0, win.winfo_screenwidth(), win.winfo_screenheight())
        if over is not None and over.winfo_viewable():
            cx, cy = over.winfo_rootx() + over.winfo_width() // 2, over.winfo_rooty() + over.winfo_height() // 2
        else:
            cx, cy = (wa[0] + wa[2]) // 2, (wa[1] + wa[3]) // 2
        tb = int(32 * win.winfo_fpixels("1i") / 96.0)                # title bar height
        x = max(wa[0], min(cx - w // 2, wa[2] - w)); y = max(wa[1], min(cy - (h + tb) // 2, wa[3] - h - tb))
        win.geometry("+%d+%d" % (x, y))
    except Exception as e:
        log("Window placement: %r" % e)
def reveal(win, fade=True, over=None, warm=None):
    """Show a window built hidden in one step: final position, dark title bar and first frame are set while withdrawn."""
    try:
        place_centered(win, over)
        win.update_idletasks()
        if sys.platform == "win32":
            import ctypes
            hwnd = ctypes.c_void_p(int(win.wm_frame(), 16)); on = ctypes.c_int(1)
            for attr in (20, 19):                          # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Win10)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0: break
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(on), 4)   # DWMWA_TRANSITIONS_FORCEDISABLED: no zoom/fade-in animation
        # Map it invisible, let Tk paint the first frame, then show it in one step. (Windows paints a new
        # window's client area white before Tk draws; the DWM open animation and our old fade made that a blink.)
        win.attributes("-alpha", 0.0); win.deiconify(); win.update()
        if warm:                                       # first-time work for later states, done while invisible
            try: warm(); win.update()
            except Exception as e: log("Window warm-up: %r" % e)
        def show():
            try: win.attributes("-alpha", 1.0)
            except Exception: pass
        win.after(40, show)
    except Exception as e:
        log("Window reveal: %r" % e)
        try: win.deiconify(); win.attributes("-alpha", 1.0)
        except Exception: pass
def windows_light():
    """True when Windows apps use the light theme (HKCU ...\\Themes\\Personalize AppsUseLightTheme = 1)."""
    if test_env("AOE4SPOTIFY_THEME") in ("light", "dark"): return test_env("AOE4SPOTIFY_THEME") == "light"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except Exception: return False
def set_titlebar(win, dark):
    if sys.platform != "win32": return
    try:
        import ctypes
        hwnd = ctypes.c_void_p(int(win.wm_frame(), 16)); v = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4) == 0: break
    except Exception: pass
def _redraw_canvases(w):
    """A freshly mapped Tk canvas only paints when its Expose event is handled (a frame later); configuring it
    schedules a full redraw that update_idletasks performs right away."""
    import tkinter
    todo = [w]
    while todo:
        c = todo.pop()
        if isinstance(c, tkinter.Canvas):
            try: c.configure(bg=c.cget("bg"))
            except Exception: pass
        todo.extend(c.winfo_children())
def swap_pages(top, old, new, w, h, x, y):
    """Replace packed `old` by the already-built `new` in `top`, resized/moved to w x h at x,y (one geometry call)."""
    top.geometry("%dx%d+%d+%d" % (w, h, x, y))
    old.pack_forget(); new.pack()
    top.update_idletasks(); _redraw_canvases(new); top.update_idletasks()
    top.geometry("")
def cover(top, grow, fn, done=None):
    """Run fn() (a page swap that resizes/moves `top`) behind a still picture of the screen, so nobody sees the
    in-between frames Windows produces: DWM composes a moved/resized window once with its OLD pixels before the
    app repaints, and a freshly shown Tk canvas paints a frame late (blank). The picture is a screen grab of the
    window area grown by grow=(l,t,r,b) px, shown in a borderless window that is painted while fully transparent
    and then made opaque (an atomic DWM change, identical pixels: invisible). fn() runs underneath; the picture is
    dropped once the new page has painted - the user sees one clean cut. Returns True if deferred (fn runs later)."""
    if sys.platform != "win32" or test_env("AOE4SPOTIFY_OFFSCREEN"):
        fn(); done and done(); return False
    try:
        import tkinter
        from PIL import ImageGrab, ImageTk
        top.update_idletasks()
        l, t, r, b = _vis_rect(top)
        gl, gt, gr, gb = grow; m = 24                       # + room for the window shadow
        L, T, R, B_ = l - gl - m, t - gt - m, r + gr + m, b + gb + m
        img = ImageGrab.grab(bbox=(L, T, R, B_), all_screens=True)
        ov = tkinter.Toplevel(top); ov.withdraw(); ov.overrideredirect(True)
        ov.attributes("-alpha", 0.0); ov.attributes("-topmost", True)
        ph = ImageTk.PhotoImage(img, master=ov); ov._ph = ph
        tkinter.Label(ov, image=ph, bd=0, highlightthickness=0).pack()
        ov.geometry("%dx%d+%d+%d" % (R - L, B_ - T, L, T)); ov.deiconify()
    except Exception:
        fn(); done and done(); return False
    def drop():
        try: ov.destroy()
        except Exception: pass
        done and done()
    def swap():
        try: fn()
        finally: top.after(70, drop)                        # new page painted underneath
    def show():
        try: ov.attributes("-alpha", 1.0)
        except Exception: pass
        top.after(25, swap)                                 # picture composed on screen
    top.after(30, show)                                     # picture painted while invisible
    return True
def _vis_rect(top):
    try:
        import ctypes, ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetParent(top.winfo_id()) or top.winfo_id()
        rc = wt.RECT()
        if ctypes.windll.dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 9, ctypes.byref(rc), ctypes.sizeof(rc)) == 0:
            return rc.left, rc.top, rc.right, rc.bottom
    except Exception: pass
    x, y = top.winfo_rootx(), top.winfo_rooty()
    return x, y, x + top.winfo_width(), y + top.winfo_height()
def fit_shift(vis, work):
    """(dx, dy) that brings the visible window rect (l, t, r, b) inside the work area: no move if it already
    fits; up only when the bottom would leave the screen (and never above the top)."""
    l, t, r, b = vis; L, T, R, B_ = work
    dx = max(L - l, min(0, R - r)); dy = max(T - t, min(0, B_ - b))
    return dx, dy
def keep_on_screen(win):
    """The window just grew (a wider page): nudge it back inside its monitor's work area. Returns the (dx, dy) moved."""
    try:
        if test_env("AOE4SPOTIFY_OFFSCREEN") or sys.platform != "win32": return (0, 0)
        import ctypes, ctypes.wintypes as wt
        class MI(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        win.update_idletasks(); u32 = ctypes.windll.user32; u32.MonitorFromWindow.restype = ctypes.c_void_p
        h = u32.GetParent(win.winfo_id()) or win.winfo_id(); r = wt.RECT(); u32.GetWindowRect(h, ctypes.byref(r))
        try:                                           # the VISIBLE frame: GetWindowRect includes Windows 10/11's
            v = wt.RECT()                              # invisible ~7 px resize borders (left/right/bottom), which
            if ctypes.windll.dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(v), ctypes.sizeof(v)) == 0: r = v   # made a window snapped
        except Exception: pass                         # to the taskbar / screen edge 'nudge' itself on every open
        mon = u32.MonitorFromWindow(ctypes.c_void_p(h), 2); mi = MI(); mi.cbSize = ctypes.sizeof(MI)
        if not (mon and u32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi))): return (0, 0)
        dx, dy = fit_shift((r.left, r.top, r.right, r.bottom), (mi.rcWork.left, mi.rcWork.top, mi.rcWork.right, mi.rcWork.bottom))
        if dx or dy: win.geometry("+%d+%d" % (win.winfo_x() + dx, win.winfo_y() + dy))
        return (dx, dy)
    except Exception as e:
        log("Keep on screen: %r" % e); return (0, 0)
_ONCE = set()
def log_once(where, exc):
    """Log an error the first time each (place, error type) happens; repeats stay quiet (no log spam in loops)."""
    k = (where, type(exc).__name__)
    if k in _ONCE: return False
    _ONCE.add(k); log("%s failed: %r (repeats of this %s not logged)" % (where, exc, k[1])); return True
def win_hidden(w):
    """Minimized or withdrawn: animations and polling can sleep."""
    try: return w.state() in ("iconic", "withdrawn") or not w.winfo_viewable()
    except Exception: return True
def ImageColor_rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
def install_crash_log():
    """Every unhandled error (main thread, worker threads, Tk callbacks) goes to the log with a traceback.
    Windowed builds have no stderr; Tk's default handler would fail writing there."""
    import traceback
    def _w(where, et, ev, tb):
        try: log("CRASH in %s:\n%s" % (where, "".join(traceback.format_exception(et, ev, tb)).rstrip()))
        except Exception: pass
    class _Sink:
        _aoe4_sink = True
        def write(self, t_):
            t_ = (t_ or "").rstrip()
            if t_ and not getattr(_LOG_TL, "busy", False): log("stderr: " + t_)
        def flush(self): pass
    if sys.stderr is None: sys.stderr = _Sink()
    if sys.stdout is None: sys.stdout = _Sink()
    sys.excepthook = lambda et, ev, tb: _w("main", et, ev, tb)
    threading.excepthook = lambda h: _w("thread %s" % getattr(h.thread, "name", "?"), h.exc_type, h.exc_value, h.exc_traceback)
    try:
        import tkinter as _tk
        _tk.Tk.report_callback_exception = lambda self, et, ev, tb: _w("UI callback", et, ev, tb)
    except Exception: pass
