"""Anti-aliased replacements for Tk's jagged create_line / create_oval / create_polygon (Tk on Windows never anti-aliases).

Every shape is drawn as an 8x supersampled coverage MASK, BOX-downscaled (area average: no ringing, no off-shades) and
filled with ONE solid colour, so edges differ only in alpha. Geometry is in canvas pixels exactly as the Tk call would
have used, including the fractional offset, and images are cached per (shape, colour, sub-pixel offset).
"""
import math
from PIL import Image, ImageDraw, ImageTk, ImageColor
Q = 8
_cache = {}

def _rgb(c):
    try: return ImageColor.getrgb(c)[:3]
    except Exception: return (255, 255, 255)

def _put(cv, key, x0, y0, w, h, layers, tags):
    """layers: [(colour, paint(draw, ox, oy))] painted bottom-up; ox/oy map canvas px -> mask px."""
    k = (id(cv.tk), key, w, h)
    ph = _cache.get(k)
    if ph is None:
        out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for col, paint in layers:
            m = Image.new("L", (w * Q, h * Q), 0); paint(ImageDraw.Draw(m)); m = m.resize((w, h), Image.BOX)
            lay = Image.new("RGBA", (w, h), _rgb(col) + (255,)); lay.putalpha(m)
            out = Image.alpha_composite(out, lay)
        ph = _cache[k] = ImageTk.PhotoImage(out, master=cv)
    return cv.create_image(x0, y0, image=ph, anchor="nw", tags=tags)

def _frame(xs, ys, pad):
    x0, y0 = math.floor(min(xs) - pad), math.floor(min(ys) - pad)
    x1, y1 = math.ceil(max(xs) + pad), math.ceil(max(ys) + pad)
    return x0, y0, max(1, x1 - x0), max(1, y1 - y0)

def _stroke(d, pts, lw):
    """Polyline with round caps and round joins (uniform stroke width) on a mask."""
    r = lw / 2.0
    for a, b in zip(pts, pts[1:]): d.line([a, b], fill=255, width=max(1, int(round(lw))))
    for x, y in pts: d.ellipse([x - r, y - r, x + r, y + r], fill=255)

def line(cv, coords, fill, width=1.0, tags=None):
    """create_line(..., capstyle='round', joinstyle='round') replacement. coords in canvas px."""
    xs, ys = coords[0::2], coords[1::2]; x0, y0, w, h = _frame(xs, ys, width / 2 + 1)
    rel = [((x - x0) * Q, (y - y0) * Q) for x, y in zip(xs, ys)]
    key = ("line", tuple(round(v, 2) for v in sum(rel, ())), round(width, 2), fill)
    return _put(cv, key, x0, y0, w, h, [(fill, lambda d: _stroke(d, rel, width * Q))], tags)

def polygon(cv, coords, fill, tags=None):
    xs, ys = coords[0::2], coords[1::2]; x0, y0, w, h = _frame(xs, ys, 1)
    rel = [((x - x0) * Q, (y - y0) * Q) for x, y in zip(xs, ys)]
    key = ("poly", tuple(round(v, 2) for v in sum(rel, ())), fill)
    return _put(cv, key, x0, y0, w, h, [(fill, lambda d: d.polygon(rel, fill=255))], tags)

def oval(cv, x0_, y0_, x1_, y1_, fill=None, outline=None, width=1.0, dash=None, tags=None):
    """create_oval replacement: optional fill, optional outline (stroke centred on the box edge like Tk), optional dash."""
    width = max(1, int(width))                                    # Tk draws oval outlines at whole-pixel widths: keep that weight
    x0, y0, w, h = _frame((x0_, x1_), (y0_, y1_), width / 2 + 1)
    bx = [(x0_ - x0) * Q, (y0_ - y0) * Q, (x1_ - x0) * Q, (y1_ - y0) * Q]; lw = width * Q
    layers = []
    if fill: layers.append((fill, lambda d: d.ellipse(bx, fill=255)))
    if outline:
        def ring(d):
            o = [bx[0] - lw / 2, bx[1] - lw / 2, bx[2] + lw / 2, bx[3] + lw / 2]
            i = [bx[0] + lw / 2, bx[1] + lw / 2, bx[2] - lw / 2, bx[3] - lw / 2]
            full = Image.new("L", d.im.size, 0); ImageDraw.Draw(full).ellipse(o, fill=255)
            if i[2] > i[0]: ImageDraw.Draw(full).ellipse(i, fill=0)
            if dash:                                              # dash lengths in canvas px along the circumference
                rx, ry = (bx[2] - bx[0]) / 2 / Q, (bx[3] - bx[1]) / 2 / Q; circ = 2 * math.pi * math.sqrt((rx * rx + ry * ry) / 2)
                on, off = dash[0], dash[1] if len(dash) > 1 else dash[0]; n = max(1, round(circ / (on + off)))
                keep = Image.new("L", d.im.size, 0); kd = ImageDraw.Draw(keep); big = [bx[0] - lw * 2, bx[1] - lw * 2, bx[2] + lw * 2, bx[3] + lw * 2]
                for j in range(n):
                    a = j * 360.0 / n - 90; kd.pieslice(big, a, a + 360.0 / n * on / (on + off), fill=255)
                from PIL import ImageChops
                full = ImageChops.multiply(full, keep)
            d.bitmap((0, 0), full, fill=255)
        layers.append((outline, ring))
    key = ("oval", tuple(round(v, 2) for v in bx), fill, outline, round(width, 2), tuple(dash or ()))
    return _put(cv, key, x0, y0, w, h, layers, tags)

def check_pts(cx, cy, w):
    """A well-proportioned check centred on (cx, cy), w wide: 45 deg short arm, long arm ~1.9x, visually centred."""
    u = w / 14.0
    return [cx - 6.2 * u, cy + 0.2 * u, cx - 2.0 * u, cy + 4.4 * u, cx + 6.2 * u, cy - 4.1 * u]

def check(cv, cx, cy, w, fill, width, tags=None):
    """The app's one checkmark: round caps/joins, uniform stroke, single solid colour, anti-aliased. All canvas px."""
    return line(cv, check_pts(cx, cy, w), fill, width, tags)
