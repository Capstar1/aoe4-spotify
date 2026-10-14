"""usage: shotage.py OUT.png ZOOM OPEN  - start the debug app (temp APPDATA copy) on a page, PrintWindow-grab its client, crop the drawn page."""
import os, sys, time, ctypes, subprocess, importlib.util, shutil
spec = importlib.util.spec_from_file_location("s", os.path.join(os.path.dirname(os.path.abspath(__file__)), "grab.py")); g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
out, z, op = sys.argv[1], float(sys.argv[2]), sys.argv[3]
ctypes.windll.shcore.SetProcessDpiAwareness(2)
env = dict(os.environ, APPDATA=os.path.join(os.environ["TEMP"], "cshot", "cmp", os.environ.get("APPSET","appmenu")), AOE4S_ZOOM=str(z), AOE4S_OPEN=op)
p = subprocess.Popen([os.path.join(os.path.dirname(__file__), "..", "target", "debug", "aoe4spotify.exe")], env=env)
time.sleep(5.5); u = ctypes.windll.user32; h = u.FindWindowW(None, "AoE4 Spotify")
tmp = out + ".full.png"; g.grab(h, tmp); p.kill()
from PIL import Image
im = Image.open(tmp); k = z; x0, y0 = round(17 * k), round(47 * k); w, hh = round(520 * k), round(586 * k)
im.crop((x0, y0, x0 + w, y0 + hh)).save(out); print(out, im.size)

