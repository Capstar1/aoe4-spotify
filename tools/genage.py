"""Render the age-page sprites with 1.0.9's own Art code (core/ui/library.py) at 1x and 1.5x -> ui/img/age/."""
import os, sys
src = r"C:\Users\Capstar\Tools\aoe4-spotify-src"; sys.path.insert(0, src)
from PIL import ImageTk, Image
ImageTk.PhotoImage = lambda im, master=None: im            # keep the PIL image
from aoe4spotify.core.ui.library import Art, CIV_LIST, SONGS
from aoe4spotify.games.registry import active as game
from aoe4spotify.core.ui.glow import render_glow, render_badge
out = os.path.join(os.path.dirname(__file__), "..", "ui", "img", "age"); os.makedirs(out, exist_ok=True)
PACK = game().intro_pack; C = dict(card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954")
for S, suf in ((1.0, "@1"), (1.5, "@1.5")):
    a = Art(None, S); put = lambda n, im: im.save(os.path.join(out, n + suf + ".png"))
    put("emblem", a.emblem(PACK, 23)); put("emblem_h", a.emblem(PACK, 23, hover=True))
    put("plus", a.plus(19)); put("plus_h", a.plus(19, hover=True))
    put("back", a.chevron(32, C["tx"], True, C["card"], w=6, h=12)); put("back_h", a.chevron(32, C["tx"], True, "#2a2a2a", w=6, h=12))
    put("packx", a.chevron(22, "#bdbdbd", True, "#2a2a2a", w=4, h=8, lw=1.8)); put("packx_h", a.chevron(22, C["tx"], True, "#3a3a3a", w=4, h=8, lw=1.8))
    put("ring22", a.ring(22, C["acc"])); put("ring15", a.ring(15, C["acc"]))
    put("xbadge", a.disc(14, "#3a3a3a", fg=C["tx"], cross=2.6, outline="#121212", ow=1.5)); put("xbadge_h", a.disc(14, C["acc"], fg=C["tx"], cross=2.6, outline="#121212", ow=1.5))
    for civ, _ in CIV_LIST: put("flag_" + civ, a.flag(civ))
    for k, (r_on) in (("on", True), ("off", False)):
        from aoe4spotify.core.ui.library import ROMAN
        for i, rn in enumerate(ROMAN): put("badge%d_%s" % (i, k), a.disc(30, "#1e3c28" if r_on else "#2c2c2c", rn, C["acc"] if r_on else C["mu"], 15 * 0.62))
    from PIL import ImageDraw
    for nm, c in (("undo_mu", C["mu"]), ("undo_tx", C["tx"])):
        Q = 4; Z = int(18 * S); im = Image.new("RGBA", (Z * Q, Z * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im); m = Z * Q
        lw = max(2, int(2 * S * Q)); d.arc([m*.2, m*.2, m*.86, m*.86], 200, 470, fill=c, width=lw)
        d.polygon([(m*.06, m*.4), (m*.38, m*.4), (m*.2, m*.64)], fill=c); put(nm, im.resize((Z, Z), Image.LANCZOS))
import json
json.dump({f[:-6]: Image.open(os.path.join(out, f)).size for f in os.listdir(out) if f.endswith("@1.png")}, open(os.path.join(out, "sizes.json"), "w"))
print("ok", len(os.listdir(out)))

