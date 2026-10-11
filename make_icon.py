"""Build app.ico (green badge) for the exe, shortcuts and installer. Needs Pillow."""
from PIL import Image, ImageDraw
def badge(px):
    m = px * 4; im = Image.new("RGBA", (m, m), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([0, 0, m - 1, m - 1], fill="#1DB954")
    for k, hh in ((-0.2, 0.2), (0, 0.3), (0.2, 0.2)):
        x = m * (0.5 + k); d.rounded_rectangle([x - m*0.05, m*(0.5-hh), x + m*0.05, m*(0.5+hh)], radius=m*0.05, fill="#121212")
    return im.resize((px, px), Image.LANCZOS)
badge(256).save("app.ico", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print("app.ico written")
