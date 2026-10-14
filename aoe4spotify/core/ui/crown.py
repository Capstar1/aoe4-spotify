"""The one crown icon used everywhere (main panel 'Age Intros' row, Age Intros header).

Drawn 4x supersampled from mirrored geometry as a coverage mask, BOX-downscaled to an EVEN square (so Tk centres it exactly
on its coordinate), then the left half is mirrored onto the right AFTER the downscale: pixel-perfectly symmetric
at every size / DPI scale. On even widths the 1px apex becomes a 2px apex sitting on the true centre line."""
from PIL import Image, ImageDraw, ImageOps

# left half of the outline in units of the crown width (24 wide, 20 tall), origin = image centre; mirrored for the right
_HALF = [(-12, 9), (-12, -7), (-5, 0), (0, -11)]
_W = 24.0
Q = 4
GREEN = "#1DB954"       # the app accent
GREY_ACC = "#6e6e6e"    # THE disabled grey (main panel accents when the app is Disabled); the crown's only other look


def crown_color(feature_on, app_on):
    """Exactly two looks: green when the intro feature AND the app are on, else the single disabled grey (never stacked)."""
    return GREEN if (feature_on and app_on) else GREY_ACC
_cache = {}


def crown_px(logical_w, S):
    """Even pixel size of the square crown image for a crown `logical_w` wide at scale S (1px margin each side)."""
    n = int(round((logical_w + 2) * S)); return max(2, n + (n % 2))


def crown_image(logical_w, S, color):
    """PIL RGBA crown, square, even side crown_px(); geometry centred on the image centre. Cached."""
    k = (logical_w, round(S, 4), color)
    if k in _cache: return _cache[k]
    Z = crown_px(logical_w, S); B = Z * Q; c = B / 2; u = logical_w / _W * S * Q
    pts = _HALF + [(-x, y) for x, y in reversed(_HALF[:-1])]
    m = Image.new("L", (B, B), 0)                                        # coverage mask only
    ImageDraw.Draw(m).polygon([(c + x * u, c + y * u) for x, y in pts], fill=255)
    m = m.resize((Z, Z), Image.BOX)                                       # area average: no ringing, no off-shades
    m.paste(ImageOps.mirror(m.crop((0, 0, Z // 2, Z))), (Z // 2, 0))     # enforce exact symmetry after downscale
    im = Image.new("RGBA", (Z, Z), color); im.putalpha(m)                 # every pixel is exactly `color`, only alpha varies
    _cache[k] = im
    return im
