"""Builds the app icon: app.ico (exe, installer, shortcuts, title bars), app.png (panel header) and app_<size>.png.
Green circle with a dark "IV" (Age IV). Geometry in 1024 units; the glyph is centred optically (I/V centroid
horizontally, bounding box vertically) and the I stroke is snapped to whole pixels at <= 48 px so it stays crisp.
Usage: python make_icon.py"""
from PIL import Image, ImageDraw
G, D, W_ = "#1DB954", "#191414", 92
SIZES = (16, 24, 32, 48, 64, 128, 256)

def render(S, w, ox, oy, ss=8, snapI=False):
    N = S * ss; k = N / 1024
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([16 * k, 16 * k, N - 16 * k, N - 16 * k], fill=G)
    W = w * k
    I = [(310 + ox, 320 + oy), (310 + ox, 704 + oy)]; V = [(490 + ox, 320 + oy), (620 + ox, 704 + oy), (750 + ox, 320 + oy)]
    if snapI:
        pw = max(2, round(w * S / 1024)); W = pw * ss
        xi = (310 + ox) * S / 1024; L = round(xi - pw / 2); cx = (L + pw / 2) * ss / k
        sh = cx - (310 + ox); I = [(x + sh, y) for x, y in I]
    def poly(pts):
        P = [(x * k, y * k) for x, y in pts]; r = W / 2
        for a, b in zip(P, P[1:]): d.line([a, b], fill=D, width=max(1, int(W)))
        for x, y in P: d.ellipse([x - r, y - r, x + r, y + r], fill=D)
    poly(I); poly(V)
    return im.resize((S, S), Image.LANCZOS) if ss > 1 else im

def measure(ox, oy, w=W_):
    """Glyph bounding-box centre and centroid at 1024 px (pure Pillow)."""
    im = render(1024, w, ox, oy, ss=1)
    px = im.load(); xs = ys = n = 0; minx = miny = 10 ** 9; maxx = maxy = -1
    for y in range(0, 1024):
        for x in range(0, 1024):
            pr, pg, pb, pa = px[x, y]
            if pa > 0 and pg < 100:
                xs += x; ys += y; n += 1
                minx, maxx, miny, maxy = min(minx, x), max(maxx, x), min(miny, y), max(maxy, y)
    return ((minx + maxx + 1) / 2, (miny + maxy + 1) / 2), (xs / n, ys / n)

if __name__ == "__main__":
    bc, cen = measure(0, 0)
    ox, oy = 512 - cen[0], 512 - bc[1]
    print("glyph offset: %.3f, %.3f" % (ox, oy))
    ico = [render(s, W_, ox, oy, snapI=s <= 48) for s in SIZES]
    ico[-1].save("app.ico", sizes=[(s, s) for s in SIZES], append_images=ico[:-1])
    for s, i in zip(SIZES, ico): i.save("app_%d.png" % s)
    ico[-1].save("app.png")
    print("app.ico, app.png, app_<size>.png written")
