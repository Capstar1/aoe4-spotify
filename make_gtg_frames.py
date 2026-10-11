"""Builds gtg_frames/ (the animated picture in the "You're good to go" window) from the source GIF.
Usage: python make_gtg_frames.py source.gif
Every frame is kept (played straight through at the GIF's own timing). The PixVerse watermark
corner is painted over on every frame, then the circle area is cropped and downscaled."""
import json, os, sys, glob
from PIL import Image, ImageDraw, ImageFilter
src = Image.open(sys.argv[1]); os.makedirs("gtg_frames", exist_ok=True)
for old in glob.glob("gtg_frames/face_*.jpg"): os.remove(old)
CX, CY, R, OUT = 138, 108, 92, 248
durations = []
for i in range(src.n_frames):
    src.seek(i); f = src.convert("RGB")
    # cover the watermark (top-right corner) with a blurred patch of its surroundings
    box = (170, 0, f.width, 40)
    patch = f.crop((box[0], 40, box[2], 80)).filter(ImageFilter.GaussianBlur(6)).resize((box[2] - box[0], 40))
    f.paste(patch, box[:2])
    f.crop((CX - R, CY - R, CX + R, CY + R)).resize((OUT, OUT), Image.LANCZOS).save("gtg_frames/face_%d.jpg" % i, quality=85)
    durations.append(int(src.info.get("duration", 70)))
json.dump({"durations_ms": durations}, open("gtg_frames/frames.json", "w"))
print("gtg_frames: %d frames, %d ms loop" % (len(durations), sum(durations)))
