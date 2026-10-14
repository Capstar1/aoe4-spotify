"""Breathing glow images for the song chips.

Split out of core/gui.py in 1.0.9; behaviour unchanged.
"""


GLOW_N = 54                                        # frames per breathing cycle (54 x 33 ms = 1.8 s)
def ink_centre(layer):
    """Shift a glyph layer (RGBA, supersampled) so the centroid of its ink sits on the image centre."""
    from PIL import ImageChops
    al = layer.getchannel("A"); W_, H_ = al.size; data = al.load(); sx = sy = tot = 0
    for y in range(0, H_):
        for x in range(0, W_):
            v = data[x, y]
            if v: sx += x * v; sy += y * v; tot += v
    if not tot: return layer
    dx = int(round((W_ - 1) / 2 - sx / tot)); dy = int(round((H_ - 1) / 2 - sy / tot))
    return ImageChops.offset(layer, dx, dy)
def even_px(logical, S):
    """Pixel size rounded to an EVEN number: Tk centres images at coord - size//2, so even sizes put the
    image centre exactly on the coordinate (odd ones land half a pixel off)."""
    n = int(round(logical * S)); return n + (n % 2)
def chip_px(r, S): n = int(round((2 * r + 4) * S)); return n + (n % 2)   # always even: centred on whole pixels   # chip image size; the glow shares its parity
def render_glow(r, S, phase, env, Q=4, badge=True):
    """One frame of the 'now playing' glow around a round chip of logical radius r (RGBA PIL image).
    Feathered radial halo (opacity ~35%..75%, breathing scale), crisp thin inner ring, tiny equalizer badge."""
    import math
    from PIL import Image, ImageDraw
    t = 0.5 - 0.5 * math.cos(2 * math.pi * phase / GLOW_N)          # ease-in-out sine 0..1..0
    # Same parity as the chip image: Tk centres an image at coord - size//2, so an odd chip with an even
    # glow (or vice versa) lands half a pixel off. D = chip + 2*pad keeps both centres on the same pixel.
    D = chip_px(r, S) + 2 * int(round(16 * S)); B = D * Q; c = B / 2; k = S * Q
    im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    def box(rad):                         # integer, inclusive box symmetric about the image centre (PIL rounds otherwise)
        R = int(round(rad)); C = B // 2; return [C - R, C - R, C + R - 1, C + R - 1]
    g = (29, 185, 84)
    a_max = (0.35 + 0.40 * t) * env
    r0 = r * k; r1 = (r + 9 + 7 * t) * k                             # halo from chip edge out to r1 (breathes)
    steps = 48
    for s in range(steps, -1, -1):                                   # outer -> inner, each ring overwrites
        f = s / steps; rad = r0 + (r1 - r0) * f
        a = a_max * (1 - f) ** 2.2                                   # smooth falloff, no hard edge
        d.ellipse(box(rad), fill=g + (int(255 * a),))
    ri = (r - 0.5) * k; d.ellipse(box(ri), fill=(0, 0, 0, 0))   # keep the portrait clean
    br = 0.25 + 0.35 * t                                              # ring brightness modulation
    rc = tuple(int(g[i] + (255 - g[i]) * br * 0.6) for i in range(3))
    rr_ = (r + 1.6) * k; w = max(1, int(1.4 * k))
    d.ellipse(box(rr_), outline=rc + (int(235 * env),), width=w)
    if badge: _badge(d, c, r, k, phase, env)
    return im.resize((D, D), Image.LANCZOS)

def _badge(d, c, r, k, phase, env):
    """Tiny equalizer badge (bottom-right of the chip, off the face)."""
    import math
    g = (29, 185, 84)
    bx, by, br_ = c + r * 0.86 * k, c + r * 0.86 * k, 6.0 * k
    d.ellipse([bx - br_, by - br_, bx + br_, by + br_], fill=(18, 18, 18, int(255 * env)), outline=g + (int(255 * env),), width=max(1, int(1.2 * k)))
    for i in range(3):
        h = (1.8 + 3.6 * (0.5 + 0.5 * math.sin(2 * math.pi * (2 * phase / GLOW_N + i * 0.37) + i))) * k
        x = bx + (i - 1) * 2.6 * k; bw = 0.85 * k
        d.rounded_rectangle([x - bw, by + 2.7 * k - h, x + bw, by + 2.7 * k], bw, fill=g + (int(255 * env),))
def render_badge(r, S, phase, env, Q=4):
    """Just the equalizer badge, in an image the same size/centre as render_glow (drawn as its own top item)."""
    from PIL import Image, ImageDraw
    D = chip_px(r, S) + 2 * int(round(16 * S)); B = D * Q
    im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); _badge(ImageDraw.Draw(im), B / 2, r, S * Q, phase, env)
    return im.resize((D, D), Image.LANCZOS)
