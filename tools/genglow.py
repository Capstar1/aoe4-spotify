"""1.0.9 'now playing' glow + badge frames (render_glow / render_badge, env=1) as sprite sheets -> ui/img/age/glow_<r>@S.png"""
import os, sys, json
sys.path.insert(0, r"C:\Users\Capstar\Tools\aoe4-spotify-src")
from PIL import Image
from aoe4spotify.core.ui.glow import GLOW_N, render_glow, render_badge
out = os.path.join(os.path.dirname(__file__), "..", "ui", "img", "age"); meta = {}
for r in (19, 14):
    for S, suf in ((1.0, "@1"), (1.5, "@1.5")):
        for kind, fn in (("glow", lambda ph: render_glow(r, S, ph, 1.0, badge=False)), ("eq", lambda ph: render_badge(r, S, ph, 1.0))):
            fr = [fn(ph) for ph in range(GLOW_N)]; D = fr[0].size[0]
            sh = Image.new("RGBA", (D * GLOW_N, D)); [sh.paste(f, (i * D, 0)) for i, f in enumerate(fr)]
            sh.save(os.path.join(out, "%s%d%s.png" % (kind, r, suf)))
            if S == 1.0: meta["%s%d" % (kind, r)] = D
json.dump({"n": GLOW_N, **meta}, open(os.path.join(out, "glow.json"), "w")); print(meta)
