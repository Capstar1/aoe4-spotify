"""Builds gtg_frames/ (the animated face in the "You're good to go" window) from the source GIF.
Usage: python make_gtg_frames.py source.gif
Keeps only the opening face frames (0-8, before the insect scenes), crops the face and paints
over the PixVerse watermark corner."""
import os, sys
from PIL import Image, ImageDraw
src = Image.open(sys.argv[1]); os.makedirs("gtg_frames", exist_ok=True)
CX, CY, R, OUT = 138, 108, 92, 248
for n, i in enumerate(range(0, 9)):
    src.seek(i); f = src.convert("RGB")
    ImageDraw.Draw(f).rectangle([176, 0, f.width, 32], fill=f.getpixel((172, 36)))   # remove watermark
    f.crop((CX - R, CY - R, CX + R, CY + R)).resize((OUT, OUT), Image.LANCZOS).save("gtg_frames/face_%d.jpg" % n, quality=88)
print("gtg_frames written")
