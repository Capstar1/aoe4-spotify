"""Install config, the per-user settings overlay, playlists, and intro presets.
"""

import base64, json, os, re, threading
from aoe4spotify.core.runtime import CONFIG, DATA, TOKEN, atomic_write, log

def _g_gui():
    import aoe4spotify.core.gui as _m
    return _m

USER_CONFIG = os.path.join(DATA, "config.json")   # settings from the control panel (overlay)
def load_config(user=True):
    """Install config.json, with the user's panel settings from %APPDATA%/AoE4Spotify laid on top."""
    with open(CONFIG, encoding="utf-8") as f: cfg = json.load(f)
    cfg.setdefault("default_playlists", dict(cfg.get("playlists", {})))
    if not user: return cfg
    return apply_user(cfg, load_user_settings())
def load_user_settings():
    """Panel settings; a missing or damaged file just means 'no changes'."""
    try:
        with open(USER_CONFIG, encoding="utf-8") as f: u = json.load(f)
        return u if isinstance(u, dict) else {}
    except FileNotFoundError: return {}
    except Exception as e: log("Settings file damaged, using defaults: %r" % e); return {}
def client_id_ok(v):
    """A Spotify Client ID is 32 hex characters. The Client Secret is the same shape, so the screen has to say which."""
    return isinstance(v, str) and len(v) == 32 and all(c in "0123456789abcdefABCDEF" for c in v)
OWN_APP_ENABLED = False   # 'Your own Spotify app' is off until its screen is approved. Off = 1.0.7 behaviour.
def using_own_app(u=None):
    if not OWN_APP_ENABLED: return False
    if u is None: u = load_user_settings()
    if not isinstance(u, dict) or not u.get("own_app"): return False
    return client_id_ok((u.get("client_id") or "").strip())
def save_own_client(cid):
    """Store this user's Client ID in their settings overlay. A different id drops the old login."""
    if not OWN_APP_ENABLED: return "bad"
    cid = (cid or "").strip()
    if not client_id_ok(cid): return "bad"
    cid = cid.lower()
    old = (load_user_settings().get("client_id") or "").strip().lower()
    merge_user({"client_id": cid, "own_app": True})
    if cid != old:
        try:
            if os.path.exists(TOKEN): os.remove(TOKEN)
        except OSError: pass
        log("Using your own Spotify app")
    return "saved"
def clear_own_client():
    """Back to the shared app that ships with the installer."""
    if not OWN_APP_ENABLED: return
    u = load_user_settings()
    had = isinstance(u, dict) and bool(u.get("own_app") or u.get("client_id"))
    merge_user(remove=("client_id", "own_app"))
    if had:
        try:
            if os.path.exists(TOKEN): os.remove(TOKEN)
        except OSError: pass
        log("Using the shared Spotify app")
def apply_user(cfg, u):
    pls = u.get("playlists") if isinstance(u.get("playlists"), dict) else {}
    cfg["playlists"] = {**cfg.get("playlists", {}),
                        **{k: v for k, v in pls.items() if isinstance(v, str) and (v.startswith("spotify:playlist:") or (is_custom(v) and custom_tracks(v, u)))}}
    if isinstance(u.get("enabled"), bool): cfg["enabled"] = u["enabled"]
    cid = (u.get("client_id") or "").strip() if isinstance(u.get("client_id"), str) else ""
    if OWN_APP_ENABLED and u.get("own_app") and client_id_ok(cid): cfg["client_id"] = cid.lower()
    if isinstance(u.get("fade_seconds"), (int, float)): cfg["fade_seconds"] = max(0.0, min(5.0, float(u["fade_seconds"])))
    if isinstance(u.get("boss_intro_enabled"), bool): cfg.setdefault("boss_intro", {})["enabled"] = u["boss_intro_enabled"]
    if isinstance(u.get("after_match"), dict): cfg["after_match"] = u["after_match"]
    cfg["intros"] = build_intros(cfg, u)
    cfg["boss_intro"]["pools"] = cfg["intros"]["imperial"]["pools"]          # (older readers)
    return cfg
INTRO_AGES = ("dark", "feudal", "castle", "imperial")
AFTER_MODES = ("stop", "playlist", "resume")
CUSTOM_PREFIX = "aoe4s:list:"; CUSTOM_MAX = 100
def is_custom(uri): return isinstance(uri, str) and uri.startswith(CUSTOM_PREFIX)
def is_playable(uri): return isinstance(uri, str) and (uri.startswith("spotify:") or is_custom(uri)) and "PASTE" not in uri
def custom_get(uri, u=None):
    if not is_custom(uri): return None
    lst = (load_user_settings() if u is None else u).get("custom_lists")
    v = lst.get(uri[len(CUSTOM_PREFIX):]) if isinstance(lst, dict) else None
    return v if isinstance(v, dict) else None
def custom_tracks(uri, u=None):
    return [t["uri"] for t in ((custom_get(uri, u) or {}).get("tracks") or [])
            if isinstance(t, dict) and str(t.get("uri", "")).startswith("spotify:track:")][:CUSTOM_MAX]
def custom_cover(uri): return os.path.join(_g_gui().COVERS, "list_%s.png" % uri[len(CUSTOM_PREFIX):])
RE_AM_URI = re.compile(r"(spotify:(playlist|track):[A-Za-z0-9]{22}|aoe4s:list:[A-Za-z0-9]{1,32})$")
def after_match_cfg(cfg):
    a = cfg.get("after_match") if isinstance(cfg.get("after_match"), dict) else {}
    def u(k):
        v = a.get(k)
        if not (isinstance(v, str) and RE_AM_URI.match(v)): return ""
        return "" if is_custom(v) and not custom_tracks(v) else v          # deleted / empty app list: nothing
    old_wl = a.get("mode") == "winloss"                          # 0.4.5: Win / Loss was a choice -> now toggle on + Stop
    mode = a.get("mode") if a.get("mode") in AFTER_MODES else ("resume" if "mode" not in a else "stop")   # never picked -> Resume; old keep/fade/dark -> Stop
    return {"mode": mode,
            "wl": bool(a["winloss_on"]) if isinstance(a.get("winloss_on"), bool) else old_wl,
            "playlist": u("playlist") if (u("playlist").startswith("spotify:playlist:") or is_custom(u("playlist"))) else "", "win": u("win"), "loss": u("loss")}
def user_intro_pools(u, base_pools=None):
    """Per-age civ pools edited in the Age Intros editor; migrates the 0.3.x Imperial-only "boss_pools".
    Semantics (v2): Imperial = defaults + your changes; Dark/Feudal/Castle = only what you put there
    (a civ with no songs has no intro). Before v2 the other ages were copies of the Imperial defaults:
    civ lists that are just those defaults are dropped (blank), genuine edits are kept."""
    ip = u.get("intro_pools") if isinstance(u.get("intro_pools"), dict) else {}
    if isinstance(u.get("boss_pools"), dict) and "imperial" not in ip: ip = {**ip, "imperial": u["boss_pools"]}
    if not u.get("intro_v2") and base_pools is not None:
        ip = dict(ip)
        for age in ("dark", "feudal", "castle"):
            if isinstance(ip.get(age), dict):
                ip[age] = {c: l for c, l in ip[age].items() if isinstance(l, list) and l and sorted(l) != sorted(base_pools.get(c) or base_pools.get("__default__") or [])}
                if not ip[age]: ip.pop(age)
    return ip
def migrate_intros_v2(u, base_pools):
    """One-time in-place migration of the user settings to the v2 per-age semantics. True if changed."""
    if u.get("intro_v2"): return False
    ip = user_intro_pools(u, base_pools); u.pop("boss_pools", None)
    if ip: u["intro_pools"] = ip
    else: u.pop("intro_pools", None)
    u["intro_v2"] = True; return True
def build_intros(cfg, u):
    """{age: {"enabled": bool, "pools": {civ: [track uris]}}}. Every age starts from the default pools;
    only the ages listed in boss_intro.ages (default Imperial) are on until you switch others on."""
    b = cfg.setdefault("boss_intro", {}); base_pools = dict(b.get("pools") or {})
    ages_on = b.get("ages") or ["imperial"]; ia = u.get("intro_ages") if isinstance(u.get("intro_ages"), dict) else {}
    ip = user_intro_pools(u, {**base_pools, "__default__": b.get("default") or []}); out = {}
    for age in INTRO_AGES:
        pools = dict(base_pools) if age == "imperial" else {}           # other ages start blank
        for civ, lst in (ip.get(age) or {}).items():
            if isinstance(lst, list) and (lst or age == "imperial") and all(isinstance(x, str) and x.startswith("spotify:track:") for x in lst):
                pools[civ] = list(lst)
        out[age] = {"enabled": ia[age] if isinstance(ia.get(age), bool) else age in ages_on, "pools": pools}
    return out
PRESET_VER = 1; PRESET_PREFIX = "AOE4S%d:" % PRESET_VER; DEFAULT_PRESET_NAME = "Default"
_TRACK_RE = re.compile(r"^spotify:track:[A-Za-z0-9]{22}$")
def preset_from_user(u, name):
    """A preset = every age's civ->song lists, age on/off and the custom songs those lists use."""
    pools = json.loads(json.dumps(u.get("intro_pools") or {})); ages = dict(u.get("intro_ages") or {})
    used = {x for a in pools.values() for v in a.values() for x in v}
    custom = [{k: c[k] for k in ("uri", "name", "artist", "cover") if c.get(k)} for c in (u.get("custom_songs") or []) if c.get("uri") in used]
    return {"v": PRESET_VER, "name": str(name)[:40], "pools": pools, "ages": ages, "custom": custom}
def default_preset(): return {"v": PRESET_VER, "name": DEFAULT_PRESET_NAME, "pools": {}, "ages": {}, "custom": [], "builtin": True}
def user_presets(u):
    return [default_preset()] + [p for p in (u.get("intro_presets") or []) if isinstance(p, dict) and p.get("name")]
def preset_key(u, p=None):
    """Comparable (pools, ages) of the user's current lists (p=None) or of a preset - for the 'unsaved' dot."""
    pools = (p or {}).get("pools") if p is not None else u.get("intro_pools")
    ages = (p or {}).get("ages") if p is not None else u.get("intro_ages")
    pk = {a: {c: sorted(v) for c, v in (d or {}).items() if v} for a, d in (pools or {}).items()}
    pk = {a: d for a, d in pk.items() if d}
    on = {a: bool((ages or {}).get(a, a == "imperial")) for a in INTRO_AGES}
    return json.dumps([pk, on], sort_keys=True)
def apply_preset(u, p):
    """Switch the user's lists to preset p (custom songs it uses are added to YOURS; nothing is removed)."""
    if p.get("pools"): u["intro_pools"] = json.loads(json.dumps(p["pools"]))
    else: u.pop("intro_pools", None)
    if p.get("ages"): u["intro_ages"] = dict(p["ages"])
    else: u.pop("intro_ages", None)
    cs = list(u.get("custom_songs") or []); have = {c.get("uri") for c in cs}
    for c in p.get("custom") or []:
        if c.get("uri") not in have: cs.append(dict(c)); have.add(c.get("uri"))
    if cs: u["custom_songs"] = cs
    u["intro_preset"] = p.get("name") or DEFAULT_PRESET_NAME; u["intro_v2"] = True
def unique_preset_name(u, name):
    names = {p["name"].lower() for p in user_presets(u)}; name = (name or "Preset").strip()[:40] or "Preset"
    if name.lower() not in names: return name
    n = 2
    while ("%s (%d)" % (name, n)).lower() in names: n += 1
    return "%s (%d)" % (name, n)
def encode_preset(p):
    import zlib
    d = {k: p.get(k) for k in ("v", "name", "pools", "ages", "custom")}; d["v"] = PRESET_VER
    raw = zlib.compress(json.dumps(d, separators=(",", ":")).encode("utf-8"), 9)
    return PRESET_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
def decode_preset(code):
    """(preset, None) or (None, short reason). Accepts surrounding whitespace / line breaks."""
    import zlib
    code = re.sub(r"\s+", "", code or "")
    m = re.match(r"^AOE4S(\d+):(.*)$", code)
    if not m: return None, "Not an AoE4 Spotify code"
    if int(m.group(1)) != PRESET_VER: return None, "Made with a newer version - update AoE4 Spotify"
    try:
        b = m.group(2)
        if len(b) > 1 << 18: return None, "Code is too big"
        dz = zlib.decompressobj(); raw = dz.decompress(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)), (1 << 18) + 1)
        if len(raw) > 1 << 18 or dz.unconsumed_tail: return None, "Code is too big"     # hard cap: a zip bomb never inflates
        d = json.loads(raw.decode("utf-8"))
    except Exception: return None, "Code is incomplete or damaged"
    if not isinstance(d, dict): return None, "Code is incomplete or damaged"
    if d.get("v") != PRESET_VER: return None, "Made with a newer version - update AoE4 Spotify"
    civs = {c for c, _ in _g_gui().CIV_LIST}; pools = {}; ages = {}; custom = []
    for a, dd in (d.get("pools") or {}).items() if isinstance(d.get("pools"), dict) else ():
        if a in INTRO_AGES and isinstance(dd, dict):
            ok_ = {c: list(dict.fromkeys(x for x in v if isinstance(x, str) and _TRACK_RE.match(x)))[:12]
                   for c, v in dd.items() if c in civs and isinstance(v, list)}
            ok_ = {c: v for c, v in ok_.items() if v}
            if ok_: pools[a] = ok_
    for a, v in (d.get("ages") or {}).items() if isinstance(d.get("ages"), dict) else ():
        if a in INTRO_AGES and isinstance(v, bool): ages[a] = v
    used = {x for dd in pools.values() for v in dd.values() for x in v}
    for c in d.get("custom") or [] if isinstance(d.get("custom"), list) else ():
        if isinstance(c, dict) and isinstance(c.get("uri"), str) and _TRACK_RE.match(c["uri"]) and c["uri"] in used:
            e = {"uri": c["uri"], "name": str(c.get("name") or "Song")[:80], "artist": str(c.get("artist") or "")[:80]}
            if isinstance(c.get("cover"), str) and c["cover"].startswith("https://"): e["cover"] = c["cover"][:300]
            custom.append(e)
    known = {x[3] for x in _g_gui().BUILTIN_SONGS} | {c["uri"] for c in custom}
    if used - known: return None, "Code uses songs it doesn't include"
    if "pools" not in d and "ages" not in d: return None, "Code has no intro lists"
    name = str(d.get("name") or "Shared").strip()[:40] or "Shared"
    return {"v": PRESET_VER, "name": name, "pools": pools, "ages": ages, "custom": custom}, None
def preset_counts(base_cfg, p):
    """{age: civs with an intro} for a preset (Imperial starts from the defaults)."""
    out = {}
    for a in INTRO_AGES:
        dd = (p.get("pools") or {}).get(a) or {}
        out[a] = sum(1 for c, _ in _g_gui().CIV_LIST if (dd[c] if c in dd else (_g_gui().default_pool(base_cfg, c) if a == "imperial" else [])))
    return out
def preset_songs(base_cfg, p):
    """Distinct songs a preset uses (canonical order)."""
    us = [x for a in INTRO_AGES for c, _ in _g_gui().CIV_LIST
          for x in ((((p.get("pools") or {}).get(a) or {})[c] if c in ((p.get("pools") or {}).get(a) or {}) else None) or (_g_gui().default_pool(base_cfg, c) if a == "imperial" and c not in ((p.get("pools") or {}).get(a) or {}) else []))]
    return _g_gui().song_sorted(us)
def load_user(): return load_user_settings()
_save_lock = threading.RLock()
_LIVE_USER = []                                     # the panel's in-memory settings dict (when the panel runs)
def save_user(u):
    """Write-then-rename (never half-written), serialized, retried while another process has the file open."""
    with _save_lock: atomic_write(USER_CONFIG, json.dumps(u, indent=2))
def merge_user(set_=None, remove=()):
    """Change only these keys: in the panel's live dict (so its next save keeps them) and on disk (other keys as they
    are there). Side dialogs use this instead of load/modify/save, which overwrote newer changes."""
    set_ = dict(set_ or {})
    with _save_lock:
        for live in _LIVE_USER:
            live.update(set_)
            for k in remove: live.pop(k, None)
        u = load_user_settings(); u.update(set_)
        for k in remove: u.pop(k, None)
        save_user(u)
