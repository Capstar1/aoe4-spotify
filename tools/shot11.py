"""usage: shot11.py OUTDIR PREFIX  (app started with AOE4S_SWITCHTEST=OUTDIR, N=1)"""
import os, sys, time, ctypes, importlib.util
spec = importlib.util.spec_from_file_location("s", os.path.join(os.path.dirname(os.path.abspath(__file__)), "grab.py")); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
d, pre = sys.argv[1], sys.argv[2]
ctypes.windll.shcore.SetProcessDpiAwareness(2)
t0 = time.time()
while not os.path.exists(os.path.join(d, "ready")):
    if time.time() - t0 > 30: sys.exit("no ready")
    time.sleep(0.05)
u = ctypes.windll.user32
h = u.FindWindowW(None, "AoE4 Spotify")
time.sleep(0.8); g.grab(h, pre + "_main.png")
time.sleep(1.4); g.grab(h, pre + "_intros.png")
