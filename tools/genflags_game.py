"""Civ flag sprites from the game's own banner art, for civs the community flag set doesn't have yet.
1. python tools/sga_extract.py <game>/cardinal/archives/UIArt.sga races/flag_ <outdir>      (read-only; writes ui/images/races/flag_<civ>.rrtex)
2. dotnet AOEMods.Essence.CLI.dll rrtex-decode <rrtex> <png>                                    (aoemods/AOEMods.Essence 0.7.0)
3. python tools/genflags_game.py scots=<flag_scots.png> vikings=<flag_vikings.png>
Same pipeline as the other flag_<id> sprites: 60x32 (Lanczos), then 30x16 / 45x24 (Lanczos) like the 1.0.9 Art.flag()."""
import os, sys
from PIL import Image
out = os.path.join(os.path.dirname(__file__), "..", "ui", "img", "age")
for a in sys.argv[1:]:
    civ, src = a.split("=", 1)
    im = Image.open(src).convert("RGBA").resize((60, 32), Image.LANCZOS)
    for suf, size in (("@1", (30, 16)), ("@1.5", (45, 24))):
        im.resize(size, Image.LANCZOS).save(os.path.join(out, f"flag_{civ}{suf}.png"))
    print("ok", civ)
