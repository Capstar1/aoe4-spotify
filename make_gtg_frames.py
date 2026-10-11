"""Builds assets/gtg_face.jpg + assets/gtg_face.json (the animated picture in the "You're good to go" window)
from the source GIF: one sprite sheet, 10 frames per row, plus frame size/count and the GIF's own per-frame timing.
Usage: python make_gtg_frames.py source.gif
Every frame is kept (played straight through). The PixVerse watermark corner is painted over on every
frame, then the circle area is cropped and downscaled."""
import json, os, sys
from PIL import Image, ImageFilter
src = Image.open(sys.argv[1]); os.makedirs("assets", exist_ok=True)
CX, CY, R, OUT, COLS = 138, 108, 92, 248, 10
n = src.n_frames; rows = (n + COLS - 1) // COLS
sheet = Image.new("RGB", (COLS * OUT, rows * OUT), "#121212"); durations = []
for i in range(n):
    src.seek(i); f = src.convert("RGB")
    # cover the watermark (top-right corner) with a blurred patch of its surroundings
    box = (170, 0, f.width, 40)
    patch = f.crop((box[0], 40, box[2], 80)).filter(ImageFilter.GaussianBlur(6)).resize((box[2] - box[0], 40))
    f.paste(patch, box[:2])
    sheet.paste(f.crop((CX - R, CY - R, CX + R, CY + R)).resize((OUT, OUT), Image.LANCZOS), ((i % COLS) * OUT, (i // COLS) * OUT))
    durations.append(int(src.info.get("duration", 70)))
sheet.save("assets/gtg_face.jpg", quality=90)
json.dump({"size": OUT, "cols": COLS, "count": n, "durations_ms": durations}, open("assets/gtg_face.json", "w"))
print("assets/gtg_face.jpg: %d frames, %d ms loop" % (n, sum(durations)))
