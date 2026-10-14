"""GitHub update check, download, and silent install. Behaviour is unchanged from 1.0.7. Match state comes from the game adapter hooks.
"""

import hashlib, json, os, re, time, urllib.error, urllib.parse, urllib.request
from aoe4spotify.core.runtime import DATA, FROZEN, VERSION, atomic_write, child_env, clean_env, log, test_env
from aoe4spotify.games.registry import active as game

from aoe4spotify.core.branding import LATEST_API, SETUP_FILE, USER_AGENT
def parse_ver(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3])) if nums else (0, 0, 0)
def check_update(timeout=6, report=False):
    """{version, url, size, sha256} if GitHub has a newer release (with a Setup .exe) than VERSION, else None.
    Offline or any error -> None (silently)."""
    try:
        api = test_env("AOE4SPOTIFY_UPDATE_API") or LATEST_API     # env var: testing only (fake release)
        req = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r: rel = json.loads(r.read())
        tag = rel.get("tag_name", "")
        if parse_ver(tag) <= parse_ver(VERSION): return None
        asset = next((a_ for a_ in rel.get("assets", []) if a_.get("name", "").lower().endswith(".exe")), None)
        if not asset: return None
        return {"version": tag.lstrip("vV"), "url": asset["browser_download_url"], "size": int(asset.get("size") or 0),
                "sha256": (asset.get("digest") or "").split("sha256:")[-1] if "sha256:" in (asset.get("digest") or "") else ""}
    except Exception:
        if report: raise                                     # manual check: caller shows "Couldn't check"
        return None
def download_update(info, dest, progress=lambda f: None):
    """Download the Setup and verify it against the GitHub asset size (and SHA-256 when GitHub gives one).
    Raises on any problem; never leaves a partial file at dest."""
    req = urllib.request.Request(info["url"], headers={"User-Agent": USER_AGENT})
    h = hashlib.sha256(); got = 0
    try:
        with urllib.request.urlopen(req, timeout=30) as r, open(dest + ".part", "wb") as f:
            total = info.get("size") or int(r.headers.get("Content-Length") or 0)
            while True:
                b = r.read(65536)
                if not b: break
                f.write(b); h.update(b); got += len(b)
                if total: progress(min(1.0, got / total))
        if info.get("size") and got != info["size"]: raise ValueError("size mismatch (%d of %d bytes)" % (got, info["size"]))
        if info.get("sha256") and h.hexdigest().lower() != info["sha256"].lower(): raise ValueError("checksum mismatch")
        os.replace(dest + ".part", dest)
    finally:
        if os.path.exists(dest + ".part"): os.remove(dest + ".part")
    return dest
def run_update(setup):
    """Silent in-place upgrade. Setup keeps token/settings/shortcuts/launch option and relaunches the panel."""
    import subprocess
    subprocess.Popen([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/RELAUNCH=1",
                      "/LOG=" + os.path.join(DATA, "update_setup.log")], env=clean_env(), close_fds=True)
def silent_install(setup):
    """Invisible upgrade from the switcher: no panel relaunch; setup's post-install '--attach' re-attaches to a running game.
    /FROMSWITCHER=1: we checked no match is on, so setup may install while the game runs (anyone else must wait)."""
    import subprocess
    subprocess.Popen([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/FROMSWITCHER=1", "/LOG=" + os.path.join(DATA, "update_setup.log")],
                     env=clean_env(), close_fds=True, creationflags=0x08000000)
def auto_update(t):
    """Switcher background thread: newer GitHub release -> download, then install silently only between matches.
    Returns the downloaded setup path if the install must wait until the game closes, else None. Never raises."""
    try:
        if not FROZEN and not test_env("AOE4SPOTIFY_UPDATE_API"): return None      # running from source: never
        info = check_update(timeout=5)
        if not info: return None
        v = info["version"]; mark = os.path.join(DATA, "auto_update.json")
        try: last = json.load(open(mark, encoding="utf-8"))
        except Exception: last = {}
        if isinstance(last, dict) and last.get("v") == v and time.time() - float(last.get("t") or 0) < 6 * 3600:
            log("Auto-update: %s was already installed recently but this is still %s - not retrying for now" % (v, VERSION)); return None
        log("Auto-update: %s available - downloading in the background" % v)
        dest = os.path.join(os.environ.get("TEMP") or DATA, SETUP_FILE % v)
        try: download_update(info, dest)
        except Exception as e: log("Auto-update: download failed (%r) - trying again next launch" % e); return None
        g = game()
        with g.update_lock(t):
            if not g.safe_to_update(t):
                log("Auto-update: %s ready - match in progress, installing after the game closes" % v); return dest
            log("Auto-update: installing %s now (not in a match); the switcher re-attaches afterwards" % v)
            try: atomic_write(mark, json.dumps({"v": v, "t": time.time()}))
            except Exception: pass
            silent_install(dest)
        return None
    except Exception as e:
        log("Auto-update failed: %r" % e); return None
