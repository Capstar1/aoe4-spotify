"""Builds assets/ for the Imperial Age Intro editor.
- assets/portraits/<song>.jpg: OCTOPATH TRAVELER character portraits, face crop, 96 px.
- assets/flags/<civ id>.png: AoE4 civ flags from aoe4world/overlay (src/assets/flags), 60x32 px.
Usage: python make_editor_assets.py <portrait dir> <flag dir> [portrait out dir]"""
import os, sys
from PIL import Image
PORTRAIT = {"light": "Ophilia", "truth": "Cyrus", "treasure": "Tressa", "redemption": "Olberic",
            "revenge": "Primrose", "succor": "Alfyn", "freedom": "Therion", "master": "Haanit"}
# Per-portrait pan in source px: +dx moves the picture right, +dy moves it down (crop window moves the opposite way).
PORTRAIT_OFFSET = {"light": (0, 20), "truth": (30, 0), "treasure": (30, -12), "revenge": (12, 0), "succor": (12, -5),
                   "freedom": (-6, 0), "master": (15, 0)}
FLAG = {"french": "french", "hre": "holy_roman_empire", "templar": "knights_templar", "french_ha_01": "jeanne_darc",
        "abbasid": "abbasid_dynasty", "abbasid_ha_01": "ayyubids", "byzantine": "byzantines", "malian": "malians",
        "sultanate": "delhi_sultanate", "ottoman": "ottomans", "english": "english", "hre_ha_01": "order_of_the_dragon",
        "lancaster": "house_of_lancaster", "mongol": "mongols", "mongol_ha_gol": "golden_horde", "rus": "rus",
        "chinese_ha_01": "zhu_xis_legacy", "chinese": "chinese", "japanese": "japanese", "jin_dynasty": "jin_dynasty",
        "japanese_ha_sen": "sengoku_daimyo", "sultanate_ha_tug": "tughlaq_dynasty", "byzantine_ha_mac": "macedonian_dynasty",
        "_unknown": "unknown"}
pdir, fdir = sys.argv[1], sys.argv[2]; pout = sys.argv[3] if len(sys.argv) > 3 else "assets/portraits"
os.makedirs(pout, exist_ok=True); os.makedirs("assets/flags", exist_ok=True)
for song, who in PORTRAIT.items():
    dx, dy = PORTRAIT_OFFSET.get(song, (0, 0))
    Image.open(os.path.join(pdir, who + ".png")).convert("RGB").crop((60 - dx, 35 - dy, 250 - dx, 225 - dy)).resize((96, 96), Image.LANCZOS) \
        .save(os.path.join(pout, song + ".jpg"), quality=90)
missing = []
for civ, fn in FLAG.items():
    p = os.path.join(fdir, fn + ".png")
    if not os.path.exists(p): missing.append(civ); continue
    Image.open(p).convert("RGBA").resize((60, 32), Image.LANCZOS).save("assets/flags/%s.png" % civ, optimize=True)
print("assets written; missing flags:", missing or "none")
