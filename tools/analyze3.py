"""Per switch: in-between frames inside the NEW window frame rect (live wallpaper outside is ignored),
plus 'old content left outside' check: after 150 ms, the strip outside the new frame must not still show the old page."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import numpy as np
from PIL import Image
D = sys.argv[1]; F = np.load(os.path.join(D, "frames.npy")); T = np.load(os.path.join(D, "times.npy")); ev = json.load(open(os.path.join(D, "events.json")))
_o = json.load(open(os.path.join(D, "origin.json"))); _r = json.load(open(os.path.join(D, "rect.json"))); OX, OY = _r["x"] - _o["L"], _r["y"] - _o["T"]; SH = 16; TB = 32
def rect(w, h): fw = w + 2; x = OX + SH + (522 - fw) / 2; return [int(v) // 2 for v in (x, OY + SH, x + fw, OY + SH + h + TB)]
R = {"open": rect(520, 586), "close": rect(430, 586)}
def diff(a, b): return float((np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > 40).mean())
tot = 0; saved = 0
for k in range(0, len(ev), 2):
    name, t0 = ev[k]; x0, y0, x1, y1 = R[name]
    i0 = max(0, int(np.searchsorted(T, t0)) - 1); j = int(np.searchsorted(T, t0 + 0.40)) - 1
    A, B = F[i0][y0:y1, x0:x1], F[j][y0:y1, x0:x1]; mids = []
    for i in range(i0 + 1, j):
        f = F[i][y0:y1, x0:x1]; da, db = diff(f, A), diff(f, B)
        if da > 0.003 and db > 0.003: mids.append((i, round(T[i] - t0, 3), round(da, 3), round(db, 3)))
    tot += len(mids)
    if mids:
        print(name, "in-between:", len(mids), mids[:3], flush=True)
        if saved < 4: Image.fromarray(np.concatenate([F[i0], F[mids[0][0]], F[j]], axis=1)[:, :, ::-1]).save(os.path.join(D, "bad3_%s_%d.png" % (name, mids[0][0]))); saved += 1
print("switches", len(ev) // 2, "TOTAL in-between frames:", tot)


