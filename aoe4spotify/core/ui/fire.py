"""'Glow pool' fire on the age row that is playing right now (approved mockups j1 + l1 softening).

Delve-style heat grid, Bayer 4x4 ordered dither, 3-stop green palette, ~60 % fire opacity, low sparse flames,
a soft green wash rising from the bottom, a light bloom and a faint rounded halo. Intensity is full on the left
third and eases to ~28 % at the right edge. One sim step every 170 ms, drawn at ~29 fps as an eased blend
(l1: EMA 0.35, soft dither ramp, greens 25 % closer, 0.6 px edge blur) so cells drift instead of popping.

Lean by design: the glow layers are built once per size (cached); a tick only steps the small heat grid
(pure Python, a few thousand cells) and pastes one image into the same PhotoImage. The panel runs the timer
only while the window is visible and a row is playing.
"""

import random
from PIL import Image, ImageChops, ImageDraw, ImageFilter

STEP_MS = 170
SUB = 5                       # display frames per sim step
FRAME_MS = STEP_MS // SUB     # 34 ms ~ 29 fps
EMA = 0.35                    # per-frame easing toward the blended heat (l1)
DITHER_W = 0.10               # soft dither ramp width (heat units)
CONTRAST = 0.75               # palette stops pulled 25 % toward the middle green
EDGE_BLUR = 0.6               # px at 2x: slight sub-cell softening
BAY = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
STOPS = ((16, 92, 46), (29, 185, 84), (110, 225, 160))
GREEN = (29, 185, 84); MINT = (110, 225, 160)
FIRE_ALPHA = 0.6
SOFT_STOPS = tuple(tuple(int(round(STOPS[1][i] + (s[i] - STOPS[1][i]) * CONTRAST)) for i in range(3)) for s in STOPS)

def _sm(x):
    x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)
_LUT_DITHER = [int(255 * _sm(((v - 128) / 255) / DITHER_W + 0.5)) for v in range(256)]   # heat - bayer -> alpha
_LUT_FLOOR = [int(255 * _sm((v / 255 - 0.04) / 0.08)) for v in range(256)]             # fade out the faintest heat
_LUT_HEAT = [int(v * 0.45) for v in range(256)]
_LUT_T1 = [int(255 * _sm((v / 255 - 0.38) / 0.2 + 0.5)) for v in range(256)]            # soft palette transitions
_LUT_T2 = [int(255 * _sm((v / 255 - 0.72) / 0.2 + 0.5)) for v in range(256)]

def falloff(u):
    """1.0 on the left third, smoothly down to 0.28 at the right edge."""
    t = min(1.0, max(0.0, (u - 1 / 3) / (2 / 3))); t = t * t * (3 - 2 * t)
    return 1 - 0.72 * t

def _mask(w, h, r, q=4):
    m = Image.new("L", (w * q, h * q), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * q - 1, h * q - 1], radius=r * q, fill=255)
    return m.resize((w, h), Image.LANCZOS)

def _grad_x(w, h, fn):
    row = Image.new("L", (w, 1)); row.putdata([int(round(255 * fn((x + 0.5) / w))) for x in range(w)])
    return row.resize((w, h), Image.NEAREST)

def _grad_y(w, h, fn):
    col = Image.new("L", (1, h)); col.putdata([int(round(255 * fn((y + 0.5) / h))) for y in range(h)])
    return col.resize((w, h), Image.NEAREST)

def _solid(size, rgb, alpha):
    im = Image.new("RGBA", size, rgb + (0,)); im.putalpha(alpha); return im

_GLOW = {}
def glow_layer(w, h, r, S):
    """Static wash + bloom + rounded outer halo, RGBA, size (w + 2 pad, h + 2 pad). Built once per size."""
    key = (w, h, r, round(S, 3))
    if key in _GLOW: return _GLOW[key]
    pad = int(round(10 * S)); W_, H_ = w + 2 * pad, h + 2 * pad
    M = _mask(w, h, r); FX = _grad_x(w, h, falloff)
    out = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
    # faint outer halo, round (blurred rounded mask), only outside the row
    big = Image.new("L", (W_, H_), 0); big.paste(M, (pad, pad))
    halo = big.filter(ImageFilter.GaussianBlur(4.5 * S)).point(lambda v: min(255, int(v * 1.6)))
    halo = ImageChops.multiply(halo, ImageChops.invert(big)).point(lambda v: int(v * 0.16))
    out = Image.alpha_composite(out, _solid((W_, H_), GREEN, halo))
    # green wash rising from the bottom, eased left -> right, clipped to the rounded row
    wash = ImageChops.multiply(_grad_y(w, h, lambda v: min(1.0, max(0.0, (v - 0.25) / 0.75)) ** 1.8), FX)
    wash = ImageChops.multiply(wash, M).point(lambda v: int(v * 0.22))
    # light bloom: a soft mint band low in the row
    band = _grad_y(w, h, lambda v: min(1.0, max(0.0, (v - 0.55) / 0.45))).filter(ImageFilter.GaussianBlur(3 * S))
    bloom = ImageChops.multiply(ImageChops.multiply(band, FX), M).point(lambda v: int(v * 0.18))
    inner = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    inner = Image.alpha_composite(inner, _solid((w, h), GREEN, wash))
    inner = Image.alpha_composite(inner, _solid((w, h), MINT, bloom))
    out.alpha_composite(inner, (pad, pad))
    _GLOW.clear(); _GLOW[key] = (out, pad)            # one size at a time: no growth
    return _GLOW[key]

class Fire:
    """Heat grid for one row of w x h device pixels. tick() -> RGBA image (w x h), already clipped and faded.

    The simulation steps every STEP_MS; tick() runs every FRAME_MS and draws an exponentially smoothed blend
    of the last two steps (approved l1), so cells drift instead of popping. All per-frame work is PIL C code
    on the small cell grid (blend, LUTs, one 3x3 kernel, composite), then one upscale and a light blur."""
    def __init__(self, w, h, r, S, seed=7):
        self.w, self.h, self.r, self.S = w, h, r, S
        self.c = c = max(2, int(round(2.5 * S)))          # 5 px cells at 2x
        self.gw, self.gh = -(-w // c), -(-h // c)
        gw, gh = self.gw, self.gh
        self.bed = max(1, round(gh * 0.48))
        self.edge = [1 + 0.6 * (abs(x - gw / 2) / (gw / 2)) ** 2 for x in range(gw)]
        self.fg = [falloff((x + 0.5) / gw) for x in range(gw)]
        self.heat = [[0.0] * gw for _ in range(gh)]
        self.rng = random.Random(seed)
        self.embers = [[self.rng.uniform(0, gw), self.rng.uniform(0, 1), self.rng.uniform(-.3, .3)] for _ in range(4)]
        self.mask = _mask(w, h, r)
        self.blur = ImageFilter.BoxBlur(EDGE_BLUR * S / 2) if EDGE_BLUR else None
        size = (gw, gh)
        bay = Image.new("L", (4, 4)); bay.putdata([int(BAY[y][x] * 255 / 16) for y in range(4) for x in range(4)])
        self.bay = Image.new("L", size)
        for y in range(0, gh, 4):
            for x in range(0, gw, 4): self.bay.paste(bay, (x, y))
        self.ygrad = _grad_y(gw, gh, lambda v: 0.55 * (min(gh - 1, int(v * gh)) / max(1, gh - 1)))
        self.stops = [Image.new("RGB", size, s) for s in SOFT_STOPS]
        nb = [1] * 9; nb[4] = 0
        self.kern = ImageFilter.Kernel((3, 3), nb, scale=1)
        self.bot = Image.new("L", (gw, min(3, gh)), 255)
        self.alut = [v * int(255 * FIRE_ALPHA) // 255 for v in range(256)]
        self.n = 0; self.sub = 0
        for _ in range(gh * 2): self.step()               # start with a settled fire
        self.prev = self.cur; self.ema = self.cur
    def _grid(self):
        return Image.frombytes("L", (self.gw, self.gh), bytes(int(v * 255) for row in self.heat for v in row))
    def step(self):
        gw, gh, bed, rnd = self.gw, self.gh, self.bed, self.rng.uniform
        heat, edge, fg = self.heat, self.edge, self.fg
        for j, y in enumerate(range(gh - bed, gh)):
            k = 0.6 + 0.4 * j / bed
            heat[y] = [min(1.0, rnd(.15, .6) * .85 * edge[x] * fg[x] * k) for x in range(gw)]
        for y in range(gh - bed - 1, -1, -1):
            s = heat[y + 1]; f = 1 + (gh - bed - y) * 1.3
            heat[y] = [max(0.0, (s[x - 1] + 2 * s[x] + s[(x + 1) % gw]) * 0.25 - rnd(.01, .034) * f) for x in range(gw)]
        for e in self.embers:
            e[1] += 1 / 32
            if e[1] >= 1: e[0] = rnd(0, gw); e[1] = 0.0; e[2] = rnd(-.3, .3)
        self.prev = getattr(self, "cur", None); self.cur = self._grid()
        if self.prev is None: self.prev = self.cur
        self.n += 1
    def tick(self):
        """One display frame (call every FRAME_MS): steps the sim every SUB frames, eases toward it, renders."""
        self.sub += 1
        if self.sub >= SUB: self.sub = 0; self.step()
        t = self.sub / SUB
        self.ema = Image.blend(self.ema, Image.blend(self.prev, self.cur, t), EMA)
        return self.frame(t)
    def frame(self, t=0.0):
        gw, gh, h = self.gw, self.gh, self.ema
        A = ImageChops.subtract(h, self.bay, 1.0, 128).point(_LUT_DITHER)       # soft dither ramp
        A = ImageChops.multiply(A, h.point(_LUT_FLOOR))
        nb = A.filter(self.kern); nb.paste(self.bot, (0, gh - self.bot.size[1]))  # lone dots never float
        A = ImageChops.multiply(A, nb)
        tt = ImageChops.add(h.point(_LUT_HEAT), self.ygrad)
        col = Image.composite(self.stops[1], self.stops[0], tt.point(_LUT_T1))
        col = Image.composite(self.stops[2], col, tt.point(_LUT_T2))
        top = gh - self.bed
        for ex, ph, dx in self.embers:                # a few rising sparks, sub-cell smooth
            ph = ph + t / 32; ey = top * (1 - ph); x = int(ex + dx * ph * 32) % gw; y0 = int(ey); f = ey - y0
            for yy, wt in ((y0, 1 - f), (y0 + 1, f)):
                if 3 <= yy < gh and wt > 0.02:
                    c0 = col.getpixel((x, yy)); col.putpixel((x, yy), tuple(int(SOFT_STOPS[2][i] * wt + c0[i] * (1 - wt)) for i in range(3)))
                    A.putpixel((x, yy), max(A.getpixel((x, yy)), int(255 * wt)))
        A = A.point(self.alut)
        big = (self.w, self.h); cc = self.c
        im = col.resize((gw * cc, gh * cc), Image.NEAREST).crop((0, 0) + big).convert("RGBA")
        al = A.resize((gw * cc, gh * cc), Image.NEAREST).crop((0, 0) + big)
        if self.blur: al = al.filter(self.blur)
        im.putalpha(ImageChops.multiply(al, self.mask))   # rounded corners, smooth edge
        return im
