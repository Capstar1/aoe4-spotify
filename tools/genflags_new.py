"""Placeholder banners for civs whose game art isn't extracted yet (Scots, Vikings, patch 17.0).
Draws a plain heraldic banner with a cloth-ripple shade, same sizes as the other flag_*@1 / @1.5 PNGs.
Replace with the real banner art (extracted from the updated game, like the other flags) when available."""
import os, math, sys
from PIL import Image, ImageDraw
out = os.path.join(os.path.dirname(__file__), "..", "ui", "img", "age")
Q = 8  # supersample

def cloth(im):
    w, h = im.size; px = im.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            k = 1.0 + 0.16 * math.sin(x / w * 2 * math.pi * 1.5 + y / h * 1.2) + 0.05 * math.sin(x / w * 9)
            px[x, y] = (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)), a)
    return im

def scots(w, h):
    im = Image.new("RGBA", (w, h), (16, 62, 140, 255)); d = ImageDraw.Draw(im)
    t = h * 0.17
    d.line([(0, 0), (w, h)], fill=(240, 240, 240, 255), width=int(t)); d.line([(0, h), (w, 0)], fill=(240, 240, 240, 255), width=int(t))
    return im

def vikings(w, h):
    im = Image.new("RGBA", (w, h), (150, 28, 24, 255)); d = ImageDraw.Draw(im)
    cx, cy, s = w / 2, h / 2, h * 0.30
    c = (236, 214, 150, 255)
    # valknut: three interlocked triangles
    for k in range(3):
        ox, oy = cx + s * 0.55 * math.cos(math.radians(k * 120 - 90)), cy + s * 0.55 * math.sin(math.radians(k * 120 - 90))
        pts = [(ox + s * 0.95 * math.cos(math.radians(k * 120 + a + 90)), oy + s * 0.95 * math.sin(math.radians(k * 120 + a + 90))) for a in (0, 120, 240)]
        d.line(pts + [pts[0]], fill=c, width=max(2, int(h * 0.05)), joint="curve")
    return im

for name, fn in (("scots", scots), ("vikings", vikings)):
    for suf, (W, H) in (("@1", (30, 16)), ("@1.5", (45, 24))):
        im = cloth(fn(W * Q, H * Q)).resize((W, H), Image.LANCZOS)
        im.save(os.path.join(out, f"flag_{name}{suf}.png"))
print("ok")
