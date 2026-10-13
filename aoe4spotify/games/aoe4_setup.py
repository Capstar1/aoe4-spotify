"""AoE4 install glue: Steam launch option and the game-music mute. Not the match watcher.
"""

import glob, json, os, re, shutil, time
from aoe4spotify.core.runtime import HERE, atomic_write, child_env, documents_dir, log, proc_running, test_env

def game_cfg_path():
    return test_env("AOE4SPOTIFY_GAME_CFG") or os.path.join(documents_dir(), "My Games", "Age of Empires IV", "configuration_system.lua")
MUSIC_STATE = os.path.join(globals().get("DATA", HERE), "game_music.json")
RE_MUSIC = re.compile(rb'(setting\s*=\s*"musicvolume"\s*,\s*variantFloat\s*=\s*)(-?[0-9]+(?:\.[0-9]+)?)')
def music_read():
    try: m = RE_MUSIC.search(open(game_cfg_path(), "rb").read())
    except OSError: return None
    return float(m.group(2)) if m else None
def music_write(v):
    """Change only that one number; the rest of the file stays byte-identical. Backs the file up once."""
    p = game_cfg_path(); data = open(p, "rb").read(); m = RE_MUSIC.search(data)
    if not m: return False
    if not os.path.exists(p + ".aoe4spotify.bak"): shutil.copyfile(p, p + ".aoe4spotify.bak")
    new = data[:m.start(2)] + (b"%.5f" % v) + data[m.end(2):]
    if new != data: atomic_write(p, new, "wb")
    return True
def music_saved():
    try: return float(json.load(open(MUSIC_STATE)).get("level"))
    except Exception: return None
def music_sync(enabled, running=None):
    """enabled: mute the game music (remember your level); disabled: put your level back. Never while AoE4 runs."""
    try:
        if (aoe_running() if running is None else running): log("Game music: AoE4 is running - will apply after it closes"); return False
        v = music_read()
        if v is None: return False
        if enabled:
            if v > 0:
                os.makedirs(os.path.dirname(MUSIC_STATE), exist_ok=True)
                atomic_write(MUSIC_STATE, json.dumps({"level": v})); music_write(0.0); log("Game music muted (your level %.2f saved)" % v)
        else:
            lv = music_saved()
            if lv and v == 0: music_write(lv); log("Game music restored to %.2f" % lv)
            if lv is not None:
                try: os.remove(MUSIC_STATE)
                except OSError: pass
        return True
    except Exception as e:
        log("Game music: %r" % e); return False
def aoe_running(): return proc_running("RelicCardinal.exe")
APPID = "1466860"   # Age of Empires IV on Steam
STATE = os.path.join(HERE, "launch_option_backup.json")
def steam_path():
    if test_env("AOE4SPOTIFY_STEAM_PATH"): return test_env("AOE4SPOTIFY_STEAM_PATH")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
        return winreg.QueryValueEx(k, "SteamPath")[0]
def vdf_tokens(t):
    """Tokenize VDF text -> list of (kind, value, start, end). kind: 's' string, '{', '}'."""
    out, i, n = [], 0, len(t)
    while i < n:
        c = t[i]
        if c == '"':
            j = i + 1
            while j < n and t[j] != '"':
                j += 2 if t[j] == "\\" else 1
            out.append(("s", t[i+1:j], i, j + 1)); i = j + 1
        elif c in "{}": out.append((c, c, i, i + 1)); i += 1
        elif c == "/" and t[i:i+2] == "//": i = t.find("\n", i); i = n if i < 0 else i
        else: i += 1
    return out
def vdf_find(toks, path):
    """Return (open_idx, close_idx) token indexes of the block at key path (case-insensitive)."""
    lo, hi = -1, len(toks)
    for key in path:
        depth, k, found = 0, lo + 1, None
        while k < hi:
            kind = toks[k][0]
            if kind == "{": depth += 1
            elif kind == "}": depth -= 1
            elif depth == 0 and kind == "s" and k + 1 < hi and toks[k+1][0] == "{" and toks[k][1].lower() == key.lower():
                found = k + 1; break
            k += 1
        if found is None: return None
        d, m = 0, found
        while True:
            if toks[m][0] == "{": d += 1
            elif toks[m][0] == "}":
                d -= 1
                if d == 0: break
            m += 1
        lo, hi = found, m
    return lo, hi
def vesc(v): return v.replace("\\", "\\\\").replace('"', '\\"')
def vunesc(v): return re.sub(r"\\(.)", r"\1", v)
def our_prefix():
    return '"%s" ' % os.path.join(HERE, "AoE4 Spotify.exe")
def localconfigs():
    try: root = steam_path()
    except OSError: log("Steam is not installed (no SteamPath in the registry) - launch option not changed"); return []
    files = sorted(glob.glob(os.path.join(root, "userdata", "*", "config", "localconfig.vdf")))
    if not files: log("No Steam user configs found under %s" % root)
    return files
def set_launch_option():
    state = {}
    for f in localconfigs():
        raw = open(f, "rb").read(); t = raw.decode("utf-8", "surrogateescape")
        shutil.copy2(f, f + ".aoe4spotify.bak")              # backup before editing
        toks = vdf_tokens(t)
        app = None
        for base in (["UserLocalConfigStore", "Software", "Valve", "Steam", "apps"],
                     ["UserLocalConfigStore", "Software", "Valve", "Steam", "Apps"]):
            app = vdf_find(toks, base + [APPID])
            if app: break
        if not app:
            log("%s: AoE4 has no entry (never launched by this Steam user) - skipped" % f); continue
        lo, hi = app; d = 0; kv = None
        for k in range(lo + 1, hi):
            if toks[k][0] == "{": d += 1
            elif toks[k][0] == "}": d -= 1
            elif d == 0 and toks[k][0] == "s" and toks[k][1].lower() == "launchoptions" and toks[k+1][0] == "s":
                kv = k; break
        pre = our_prefix()
        if kv is not None:
            old = vunesc(toks[kv+1][1])
            if old.startswith(pre): log("%s: already set" % f); continue
            new = pre + (old if "%command%" in old else ("%command% " + old).strip())
            a, b = toks[kv+1][2], toks[kv+1][3]
            t2 = t[:a] + '"' + vesc(new) + '"' + t[b:]
            state[f] = {"mode": "replace", "old": old, "new": new}
        else:
            new = pre + "%command%"
            close = toks[hi][2]
            line_start = t.rfind("\n", 0, close) + 1
            indent = t[line_start:close]
            ins = indent + '\t"LaunchOptions"\t\t"' + vesc(new) + '"\n'
            t2 = t[:line_start] + ins + t[line_start:]
            state[f] = {"mode": "insert", "ins": ins, "new": new}
        open(f, "wb").write(t2.encode("utf-8", "surrogateescape"))
        log("%s: launch option set to %s" % (f, new))
    old_state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    old_state.update(state)
    atomic_write(STATE, json.dumps(old_state, indent=1))
def remove_launch_option():
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    pre = our_prefix()
    for f in localconfigs():
        t = open(f, "rb").read().decode("utf-8", "surrogateescape"); st = state.get(f)
        toks = vdf_tokens(t); t2 = None
        for k, tok in enumerate(toks):
            if tok[0] == "s" and tok[1].lower() == "launchoptions" and k + 1 < len(toks) and toks[k+1][0] == "s" \
                    and vunesc(toks[k+1][1]).startswith(pre):
                cur = vunesc(toks[k+1][1]); a, b = toks[k+1][2], toks[k+1][3]
                if st and st["mode"] == "insert" and cur == st["new"] and st["ins"] in t:
                    t2 = t.replace(st["ins"], "", 1)                       # remove the line we added
                elif st and st["mode"] == "replace" and cur == st["new"]:
                    t2 = t[:a] + '"' + vesc(st["old"]) + '"' + t[b:]       # exact original value
                else:
                    t2 = t[:a] + '"' + vesc(cur[len(pre):]) + '"' + t[b:]  # user edited it: just strip ours
                break
        if t2 is not None:
            open(f, "wb").write(t2.encode("utf-8", "surrogateescape")); log("%s: launch option removed" % f)
    if os.path.exists(STATE): os.remove(STATE)
def launch_option_is_set():
    """True/False whether AoE4's Steam launch option starts us; None if Steam isn't found."""
    files = localconfigs()
    if not files: return None
    pre = our_prefix().lower()
    for f in files:
        try: toks = vdf_tokens(open(f, "rb").read().decode("utf-8", "surrogateescape"))
        except OSError: continue
        for k, tok in enumerate(toks):
            if tok[0] == "s" and tok[1].lower() == "launchoptions" and k + 1 < len(toks) and toks[k+1][0] == "s" \
                    and vunesc(toks[k+1][1]).lower().startswith(pre):
                return True
    return False
def steam_running():
    import subprocess
    try:
        name = test_env("AOE4SPOTIFY_STEAM_PROC") or "steam.exe"         # override: testing only (dummy Steam)
        out = subprocess.run(["tasklist", "/fi", "imagename eq " + name, "/nh"], capture_output=True,
                             text=True, creationflags=0x08000000).stdout
        return name.lower() in out.lower()
    except Exception: return False
def steam_exe():
    if test_env("AOE4SPOTIFY_STEAM_EXE"): return test_env("AOE4SPOTIFY_STEAM_EXE")
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            return winreg.QueryValueEx(k, "SteamExe")[0]
    except OSError: return None
def with_steam_closed(fn):
    """Steam rewrites localconfig.vdf while running: close it gracefully, run fn, reopen it if it was open."""
    import subprocess
    was = steam_running(); exe = steam_exe()
    if was:
        log("Closing Steam to edit the launch option")
        if exe: subprocess.Popen([exe, "-shutdown"], env=child_env())
        for _ in range(30):
            time.sleep(1)
            if not steam_running(): break
        else:
            log("Steam did not close in 30s - force closing")
            subprocess.run(["taskkill", "/im", test_env("AOE4SPOTIFY_STEAM_PROC") or "steam.exe", "/f"], capture_output=True, creationflags=0x08000000)
            time.sleep(2)
    try: fn()
    finally:
        if was and exe: subprocess.Popen([exe, "-silent"], env=child_env()); log("Reopened Steam")
