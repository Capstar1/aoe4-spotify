"""M3 add test: run debug app with fake Spotify, grab main + Add a song windows on SHOT markers in aoe4s_dbg.txt."""
import os, sys, time, ctypes, subprocess, importlib.util
from ctypes import wintypes as wt
spec = importlib.util.spec_from_file_location("s", os.path.join(os.path.dirname(os.path.abspath(__file__)), "grab.py")); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
out = sys.argv[1]; os.makedirs(out, exist_ok=True); ctypes.windll.shcore.SetProcessDpiAwareness(2)
dbg = os.path.join(os.environ["TEMP"], "aoe4s_dbg.txt")
if os.path.exists(dbg): os.remove(dbg)
env = dict(os.environ, APPDATA=os.path.join(os.environ["TEMP"], "cshot", "cmp", os.environ.get("APPSET", "appmenu")), AOE4S_OPEN=sys.argv[2] if len(sys.argv) > 2 else "age:imperial:yours", AOE4S_FAKESP="1", AOE4S_ADDTEST="1")
p = subprocess.Popen([os.path.join(os.path.dirname(__file__), "..", "target", "debug", "aoe4spotify.exe")], env=env)
u = ctypes.windll.user32
def wins():
    r = []
    def cb(h, _):
        pid = wt.DWORD(); u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == p.pid and u.IsWindowVisible(h):
            rc = wt.RECT(); u.GetClientRect(h, ctypes.byref(rc)); r.append((h, rc.right, rc.bottom))
        return True
    u.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)(cb), 0); return r
seen = set(); t0 = time.time(); res = ""
while time.time() - t0 < 30:
    time.sleep(0.1)
    try: s = open(dbg).read().split("\n")[0]
    except Exception: continue
    if s.startswith("SHOT ") and s not in seen:
        seen.add(s); n = s[5:]
        for h, w, hh in wins():
            if w > 500 and hh > 800: g.grab(h, os.path.join(out, n + "_main.png"))
            elif 300 < w < 500: g.grab(h, os.path.join(out, n + "_add.png"))
    if s.startswith("ADDTEST"): res = s; break
time.sleep(0.3); p.kill(); print(res)
import shutil; b = os.path.join(env["APPDATA"], "AoE4Spotify-1.1", "intros.json"); shutil.copy(b + ".base", b) if os.path.exists(b + ".base") else None
