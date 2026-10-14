"""wall-clock variant of capture.py for the Tauri test"""
import os, sys, time, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import numpy as np, mss
out = sys.argv[1]
while not os.path.exists(os.path.join(out, "ready")): time.sleep(0.02)
r = json.load(open(os.path.join(out, "rect.json")))
L, T = max(0, r["x"] - 160), r["y"] - 50; json.dump({"L": L, "T": T}, open(os.path.join(out, "origin.json"), "w"))
mon = {"left": L, "top": T, "width": 860, "height": 1000}
frames, times, last, t_end = [], [], None, None
with mss.mss() as s:
    while True:
        f = np.asarray(s.grab(mon))[::2, ::2, :3]; t = time.time()
        if last is None or not np.array_equal(f, last): frames.append(f.copy()); times.append(t); last = f
        if os.path.exists(os.path.join(out, "done")):
            t_end = t_end or t
            if t - t_end > 0.4: break
np.save(os.path.join(out, "times.npy"), np.array(times)); np.save(os.path.join(out, "frames.npy"), np.stack(frames))
print("captured", len(frames), flush=True)

