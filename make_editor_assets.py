"""Builds assets/ for the Imperial Age Intro editor.
- assets/portraits/<song>.jpg: OCTOPATH TRAVELER character portraits, face crop, 96 px.
- assets/flags/<civ id>.png: AoE4 civ flags from aoe4world/overlay (src/assets/flags), 60x32 px.
Usage: python make_editor_assets.py <portrait dir> <flag dir>"""
import os, sys
from PIL import Image
PORTRAIT = {"light": "Ophilia", "truth": "Cyrus", "treasure": "Tressa", "redemption": "Olberic",
            "revenge": "Primrose", "succor": "Alfyn", "freedom": "Therion", "master": "Haanit"}
FLAG = {"french": "french", "hre": "holy_roman_empire", "templar": "knights_templar", "french_ha_01": "jeanne_darc",
        "abbasid": "abbasid_dynasty", "abbasid_ha_01": "ayyubids", "byzantine": "byzantines", "malian": "malians",
        "sultanate": "delhi_sultanate", "ottoman": "ottomans", "english": "english", "hre_ha_01": "order_of_the_dragon",
        "lancaster": "house_of_lancaster", "mongol": "mongols", "mongol_ha_gol": "golden_horde", "rus": "rus",
        "chinese_ha_01": "zhu_xis_legacy", "chinese": "chinese", "japanese": "japanese", "jin_dynasty": "jin_dynasty",
        "japanese_ha_sen": "sengoku_daimyo", "sultanate_ha_tug": "tughlaq_dynasty", "byzantine_ha_mac": "macedonian_dynasty",
        "_unknown": "unknown"}
pdir, fdir = sys.argv[1], sys.argv[2]
os.makedirs("assets/portraits", exist_ok=True); os.makedirs("assets/flags", exist_ok=True)
for song, who in PORTRAIT.items():
    Image.open(os.path.join(pdir, who + ".png")).convert("RGB").crop((60, 35, 250, 225)).resize((96, 96), Image.LANCZOS) \
        .save("assets/portraits/%s.jpg" % song, quality=90)
missing = []
for civ, fn in FLAG.items():
    p = os.path.join(fdir, fn + ".png")
    if not os.path.exists(p): missing.append(civ); continue
    Image.open(p).convert("RGBA").resize((60, 32), Image.LANCZOS).save("assets/flags/%s.png" % civ, optimize=True)
print("assets written; missing flags:", missing or "none")
