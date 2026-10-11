"""AoE4 -> Spotify age playlist switcher. Python stdlib + Pillow (panel). MIT licensed (see LICENSE).

How it works, in short:
- AoE4: while RelicCardinal.exe runs, it reads Documents/My Games/Age of Empires IV/warnings.log,
  where the game writes "Age up started/complete ... for player id N" lines.
- Spotify: Web API with PKCE login (no client secret; the Client ID in config.json is public).
  Needs Spotify Premium. Calls: /me/player/play, /volume, /shuffle, /repeat, /playlists/{id}.
- Token: your Spotify login token is stored ONLY on your PC in %APPDATA%/AoE4Spotify/token.json.
- Steam: the installer sets AoE4's Steam launch option to `"<install dir>/AoE4 Spotify.exe" %command%`,
  so Steam starts this app with the game; it exits ~10s after the game closes.

Tails AoE4's warnings.log and switches Spotify playlists when YOU age up.
Run:  python aoe4_spotify.py            (normal)
      python aoe4_spotify.py --login    (just do Spotify login)
      python aoe4_spotify.py --dry-run warnings.log [DataCRC files in match order]  (no Spotify calls)
"""
import glob, shutil, random, base64, hashlib, http.server, json, os, re, secrets, sys, threading, time
import urllib.error, urllib.parse, urllib.request, webbrowser

FROZEN = getattr(sys, "frozen", False)
HERE = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
VERSION = "0.4.3"
ASSETS = getattr(sys, "_MEIPASS", HERE)     # bundled assets/ (icon, flags, portraits, gtg_face sprite): _internal next to the exe

def child_env():
    """Environment for processes we start: never pass PyInstaller's bootloader variables on."""
    env = {k: v for k, v in os.environ.items() if not (k.startswith("_PYI") or k.startswith("_MEI") or k in ("TCL_LIBRARY", "TK_LIBRARY"))}
    if FROZEN: env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env
DATA = os.path.join(os.environ.get("APPDATA") or HERE, "AoE4Spotify")
os.makedirs(DATA, exist_ok=True)
TOKEN = os.path.join(DATA, "token.json")   # private Spotify login token; never shared or packaged
LOGFILE = os.path.join(DATA, "aoe4_spotify.log")
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-modify-playback-state user-read-playback-state"
def documents_dir():
    """The real Documents folder (handles OneDrive / moved Documents)."""
    try:
        import ctypes, ctypes.wintypes as wt
        buf = ctypes.create_unicode_buffer(wt.MAX_PATH)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value: return buf.value  # CSIDL_PERSONAL
    except Exception: pass
    return os.path.join(os.path.expanduser("~"), "Documents")
DEFAULT_LOG = os.path.join(documents_dir(), "My Games", "Age of Empires IV", "warnings.log")

def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    try: print(line, flush=True)
    except Exception: pass  # pythonw has no console
    try:
        if os.path.exists(LOGFILE) and os.path.getsize(LOGFILE) > 1_000_000:   # keep the log small
            os.replace(LOGFILE, LOGFILE + ".old")
        with open(LOGFILE, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass

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

def apply_user(cfg, u):
    pls = u.get("playlists") if isinstance(u.get("playlists"), dict) else {}
    cfg["playlists"] = {**cfg.get("playlists", {}),
                        **{k: v for k, v in pls.items() if isinstance(v, str) and v.startswith("spotify:playlist:")}}
    if isinstance(u.get("enabled"), bool): cfg["enabled"] = u["enabled"]
    for k in ("access_webhook", "access_key"):                       # request-access endpoint: overridable per user
        if isinstance(u.get(k), str) and u[k]: cfg[k] = u[k]
    if isinstance(u.get("fade_seconds"), (int, float)): cfg["fade_seconds"] = max(0.0, min(5.0, float(u["fade_seconds"])))
    if isinstance(u.get("boss_intro_enabled"), bool): cfg.setdefault("boss_intro", {})["enabled"] = u["boss_intro_enabled"]
    cfg["intros"] = build_intros(cfg, u)
    cfg["boss_intro"]["pools"] = cfg["intros"]["imperial"]["pools"]          # (older readers)
    return cfg

INTRO_AGES = ("dark", "feudal", "castle", "imperial")
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

# ---------------------------------------------------------------- intro presets + share codes
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
        b = m.group(2); raw = zlib.decompress(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)), bufsize=1 << 16)
        if len(raw) > 1 << 18: return None, "Code is too big"
        d = json.loads(raw.decode("utf-8"))
    except Exception: return None, "Code is incomplete or damaged"
    if not isinstance(d, dict): return None, "Code is incomplete or damaged"
    if d.get("v") != PRESET_VER: return None, "Made with a newer version - update AoE4 Spotify"
    civs = {c for c, _ in CIV_LIST}; pools = {}; ages = {}; custom = []
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
    known = {x[3] for x in BUILTIN_SONGS} | {c["uri"] for c in custom}
    if used - known: return None, "Code uses songs it doesn't include"
    if "pools" not in d and "ages" not in d: return None, "Code has no intro lists"
    name = str(d.get("name") or "Shared").strip()[:40] or "Shared"
    return {"v": PRESET_VER, "name": name, "pools": pools, "ages": ages, "custom": custom}, None

def preset_counts(base_cfg, p):
    """{age: civs with an intro} for a preset (Imperial starts from the defaults)."""
    out = {}
    for a in INTRO_AGES:
        dd = (p.get("pools") or {}).get(a) or {}
        out[a] = sum(1 for c, _ in CIV_LIST if (dd[c] if c in dd else (default_pool(base_cfg, c) if a == "imperial" else [])))
    return out

def preset_songs(base_cfg, p):
    """Distinct songs a preset uses (canonical order)."""
    us = [x for a in INTRO_AGES for c, _ in CIV_LIST
          for x in ((((p.get("pools") or {}).get(a) or {})[c] if c in ((p.get("pools") or {}).get(a) or {}) else None) or (default_pool(base_cfg, c) if a == "imperial" and c not in ((p.get("pools") or {}).get(a) or {}) else []))]
    return song_sorted(us)

# ---------------------------------------------------------------- Spotify desktop app launch
STORE_APP = r"SpotifyAB.SpotifyMusic_zpdnekdrzrea0"

def spotify_running():
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/fi", "imagename eq Spotify.exe", "/nh"], capture_output=True,
                             text=True, creationflags=0x08000000).stdout
        return "spotify.exe" in out.lower()
    except Exception:
        return False

def _spotify_protocol_registered():
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "spotify")); return True
    except Exception:
        return False

def launch_spotify():
    """Start the Spotify desktop app minimized. Returns False if it isn't installed."""
    import subprocess
    exe = os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe")
    try:
        if os.path.isfile(exe):                                   # classic installer
            subprocess.Popen([exe, "--minimized"], env=child_env(), creationflags=0x08000000); log("Started Spotify (minimized)"); return True
        if os.path.isdir(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", STORE_APP)):   # Microsoft Store
            subprocess.Popen(["explorer.exe", r"shell:AppsFolder\%s!Spotify" % STORE_APP], env=child_env()); log("Started Spotify (Microsoft Store app)"); return True
        if _spotify_protocol_registered():
            os.startfile("spotify:"); log("Started Spotify via spotify: link"); return True
    except Exception as e:
        log("Could not start Spotify: %r" % e); return False
    log("Spotify desktop app is NOT INSTALLED on this PC - install it from spotify.com to get music.")
    return False

# ---------------------------------------------------------------- Spotify
FADE_FLOOR_DB = -34.0                                  # quiet point of a switch (about 2% loudness, not silence)

def fade_gain(t, floor_db=FADE_FLOOR_DB):
    """Amplitude for fade position t (0 = full, 1 = floor). Linear in decibels (even to the ear) with a
    cosine ease at both ends, so there is no sudden step at the start or a long almost-silent tail."""
    import math
    t = max(0.0, min(1.0, t)); e = 0.5 - 0.5 * math.cos(math.pi * t)
    return 10 ** (floor_db * e / 20.0)

def local_guard(v, last=None):
    """While a local fade runs: {"v": level to go back to, "last": level we last set}. None = done."""
    p = os.path.join(DATA, "fade_restore.json")
    try:
        if v is None:
            if os.path.exists(p): os.remove(p)
        else:
            os.makedirs(DATA, exist_ok=True)
            with open(p + ".part", "w") as f: f.write(json.dumps({"v": float(v), "last": None if last is None else float(last)}))
            os.replace(p + ".part", p)
    except Exception: pass

def local_guard_restore():
    """After a crash mid-fade: undo our dip only if Spotify is still exactly where we left it (else it's the user's level)."""
    p = os.path.join(DATA, "fade_restore.json")
    try:
        if not os.path.exists(p): return
        d = json.load(open(p)); sess = SpotifySession.find()
        if sess and d.get("last") is not None and abs(sess.get() - d["last"]) <= 0.01:
            sess.set(d["v"]); log("Restored Spotify app volume after an interrupted fade")
        else: log("Interrupted fade: volume was changed since, leaving it")
        os.remove(p)
    except Exception: pass

class SpotifySession:
    """Windows per-app volume of Spotify.exe (Core Audio session). Smooth and instant; local only."""
    def __init__(self, vols): self.vols = vols
    @staticmethod
    def find():
        if sys.platform != "win32" or test_env("AOE4SPOTIFY_NO_LOCAL_FADE"): return None
        try:
            from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
            vols = [x._ctl.QueryInterface(ISimpleAudioVolume) for x in AudioUtilities.GetAllSessions()
                    if x.Process and x.Process.name().lower() == "spotify.exe"]
            return SpotifySession(vols) if vols else None
        except Exception as e:
            log("Local fade unavailable: %s" % type(e).__name__); return None
    def get(self):
        return float(self.vols[0].GetMasterVolume())
    def set(self, v):
        v = max(0.0, min(1.0, float(v)))
        for x in self.vols: x.SetMasterVolume(v, None)
        return True

class ApiVolumePacer:
    """Fire-and-forget Spotify volume: callers set a target any time; one sender thread sends the newest value
    (older ones are dropped), at most every `step` seconds, on the shared keep-alive connection. 429 -> wait
    Retry-After and send less often."""
    def __init__(self, sp, step=0.1):
        self.sp, self.step = sp, max(step, getattr(sp, "_vol_step", step)); self.want = None; self.sent = None
        self.cv = threading.Condition(); self.alive = True; self.fail = False
        threading.Thread(target=self._run, daemon=True).start()
    def target(self, v):
        if self.fail: return False
        with self.cv: self.want = int(round(v)); self.cv.notify()
        return True
    def _run(self):
        while True:
            with self.cv:
                while self.alive and (self.want is None or self.want == self.sent): self.cv.wait(0.5)
                if not self.alive and (self.want is None or self.want == self.sent): return
                v = self.want
            t0 = time.perf_counter()
            q = "&device_id=" + self.sp.device_id if self.sp.device_id else ""
            code, _ = self.sp._api("PUT", "/me/player/volume?volume_percent=%d%s" % (max(0, min(100, v)), q))
            if code == 429:
                ra = float(getattr(self.sp, "_retry_after", 1) or 1); self.step = min(0.5, self.step * 2); self.sp._vol_step = self.step
                log("Spotify volume rate-limited: waiting %.1fs, fewer steps" % ra); time.sleep(min(ra, 3)); continue
            if code not in (200, 202, 204):
                self.fail = True; return
            self.sent = v
            time.sleep(max(0.0, self.step - (time.perf_counter() - t0)))
    def flush(self, timeout=1.5):
        t0 = time.time()
        while not self.fail and self.want is not None and self.want != self.sent and time.time() - t0 < timeout: time.sleep(0.02)
    def stop(self):
        with self.cv: self.alive = False; self.cv.notify()

class Spotify:
    def __init__(self, cfg):
        self.cid = cfg["client_id"].strip()
        self.device_id = (cfg.get("device_id") or "").strip() or None
        self.tok = None
        self.shuffle = bool(cfg.get("shuffle", True))
        self.repeat = bool(cfg.get("repeat", True))
        self._glock = threading.Lock(); self._gen = 0   # fade/switch state
        if os.path.exists(TOKEN):
            try:
                with open(TOKEN, encoding="utf-8") as f: self.tok = json.load(f)
                if "refresh_token" not in self.tok: raise ValueError("no refresh_token")
            except Exception as e:
                log("Spotify login data is damaged (%r) - please log in again" % e); self.tok = None

    def _save(self, tok):
        if "refresh_token" not in tok and self.tok: tok["refresh_token"] = self.tok.get("refresh_token")
        tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
        self.tok = tok
        with open(TOKEN, "w", encoding="utf-8") as f: json.dump(tok, f)

    def _token_req(self, data):
        req = urllib.request.Request("https://accounts.spotify.com/api/token",
            data=urllib.parse.urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as r: return json.load(r)

    def login(self):
        verifier = secrets.token_urlsafe(64)[:100]
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(16)
        result = {}
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                if urllib.parse.urlparse(self.path).path != "/callback":
                    self.send_response(404); self.end_headers(); return
                result.update({k: v[0] for k, v in q.items()})
                self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers()
                self.wfile.write(b"<h2>Spotify login done. You can close this tab.</h2>")
            def log_message(self, *a): pass
        try: srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
        except OSError:
            log("Login: port 8888 is busy (another login window open?) - try again in a minute"); raise SystemExit("port busy")
        srv.timeout = 2
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": self.cid, "response_type": "code", "redirect_uri": REDIRECT,
            "code_challenge_method": "S256", "code_challenge": challenge,
            "scope": SCOPES, "state": state})
        log("Opening browser for Spotify login...")
        webbrowser.open(url)
        deadline = time.time() + 300                 # give up after 5 minutes
        while "code" not in result and "error" not in result and time.time() < deadline:
            srv.handle_request()
        srv.server_close()
        if not result: log("Login timed out"); raise SystemExit("Spotify login timed out")
        if result.get("error") or result.get("state") != state:
            raise SystemExit("Spotify login failed: %s" % result)
        self._save(self._token_req({"grant_type": "authorization_code", "code": result["code"],
            "redirect_uri": REDIRECT, "client_id": self.cid, "code_verifier": verifier}))
        log("Spotify login OK, token cached in token.json")

    def access(self):
        # Never opens the login page by itself: background calls (panel, game) just fail quietly.
        if not self.tok: raise RuntimeError("not logged in to Spotify")
        if time.time() > self.tok.get("expires_at", 0):
            try:
                self._save(self._token_req({"grant_type": "refresh_token",
                    "refresh_token": self.tok["refresh_token"], "client_id": self.cid}))
            except urllib.error.HTTPError as e:
                if e.code in (400, 401):      # refresh token revoked/expired: forget it, user must log in again
                    log("Spotify login expired - open AoE4 Spotify and click Log in")
                    self.tok = None
                    try: os.remove(TOKEN)
                    except OSError: pass
                raise
        return self.tok["access_token"]

    def _api(self, method, path, body=None, _retry=True):
        """Call the Spotify Web API. Never raises: returns (status, body); status 0 = offline/not logged in."""
        import http.client, threading
        if not hasattr(self, "_klock"): self._klock = threading.Lock(); self._kconn = None
        try:
            data = json.dumps(body).encode() if body is not None else None
            hdr = {"Authorization": "Bearer " + self.access(), "Content-Type": "application/json"}
            if data is None and method in ("PUT", "POST"): hdr["Content-Length"] = "0"
            with self._klock:                                  # one persistent connection, reused (keep-alive)
                for attempt in (0, 1):
                    if self._kconn is None: self._kconn = http.client.HTTPSConnection("api.spotify.com", timeout=15)
                    try:
                        self._kconn.request(method, "/v1" + path, body=data, headers=hdr)
                        r = self._kconn.getresponse(); raw = r.read(); status = r.status; break
                    except (http.client.HTTPException, ConnectionError, OSError):
                        try: self._kconn.close()
                        except Exception: pass
                        self._kconn = None                     # stale keep-alive socket: reconnect once
                        if attempt: raise
            if status == 429:
                try: self._retry_after = float(r.getheader("Retry-After") or 1)
                except Exception: self._retry_after = 1.0
            if status == 401 and _retry and self.tok:          # access token rejected: refresh once
                self.tok["expires_at"] = 0
                return self._api(method, path, body, False)
            try: return status, (json.loads(raw) if raw else None)
            except ValueError: return status, (raw.decode(errors="replace") if status >= 400 else None)
        except urllib.error.HTTPError as e:                    # token refresh failed (raised by access())
            raw = e.read()
            try: return e.code, json.loads(raw)
            except Exception: return e.code, raw.decode(errors="replace")
        except (urllib.error.URLError, OSError, __import__("http.client").client.HTTPException) as e:
            log("Spotify unreachable (offline?): %s" % getattr(e, "reason", e)); return 0, None
        except BaseException as e:
            log("Spotify request failed: %r" % e); return 0, None

    def play(self, uri):
        q = "?device_id=" + self.device_id if self.device_id else ""
        payload = {"context_uri": uri}
        if self.shuffle and uri.startswith("spotify:playlist:"):
            c, pl = self._api("GET", "/playlists/%s?fields=tracks.total" % uri.split(":")[-1])
            try: n = int(pl["tracks"]["total"]) if c == 200 else 0
            except Exception: n = 0
            payload["offset"] = {"position": random.randrange(n) if n > 0 else 0}
        ok = self._play(uri, payload, q)
        if ok and self.shuffle:
            dq = "&device_id=" + self.device_id if self.device_id else ""
            self._api("PUT", "/me/player/shuffle?state=true" + dq)
        if ok and self.repeat:
            dq = "&device_id=" + self.device_id if self.device_id else ""
            self._api("PUT", "/me/player/repeat?state=context" + dq)
        return ok

    def ensure_device(self, wait=20):
        """Find this PC's Spotify device (type Computer); start Spotify if needed and wait for it."""
        def find():
            c, d = self._api("GET", "/me/player/devices")
            devs = (d or {}).get("devices", []) if isinstance(d, dict) else []
            comp = [x for x in devs if (x.get("type") or "").lower() == "computer"]
            me = os.environ.get("COMPUTERNAME", "").lower()
            comp.sort(key=lambda x: (x.get("name", "").lower() != me, not x.get("is_active")))
            return comp[0] if comp else None
        dev = find()
        if not dev:
            if not spotify_running() and not launch_spotify(): return False
            t0 = time.time()
            while not dev and time.time() - t0 < wait:
                time.sleep(2); dev = find()
        if not dev:
            log("Spotify: NO DEVICE after %ds. Is the Spotify app logged in on this PC?" % wait); return False
        if dev["id"] != self.device_id: log("Spotify: using device '%s'" % dev.get("name"))
        self.device_id = dev["id"]
        return True

    def _play(self, uri, payload, q):
        code, body = self._api("PUT", "/me/player/play" + q, payload)
        if code == 404:  # no active device (Spotify closed/idle): start it and target this PC by device_id
            self.device_id = None
            if not self.ensure_device(): return False
            code, body = self._api("PUT", "/me/player/play?device_id=" + self.device_id, payload)
        if code == 403:
            log("Spotify 403: playback control needs Spotify Premium (%s)" % body); return False
        if code not in (200, 202, 204):
            log("Spotify error %s: %s" % (code, body)); return False
        return True

    def warm(self):
        """Editor warm-up on a worker thread: token + keep-alive connection + this PC's device id, so a
        preview click is a single PUT. Never starts Spotify."""
        try:
            c, d = self._api("GET", "/me/player/devices")
            devs = (d or {}).get("devices", []) if c == 200 and isinstance(d, dict) else []
            comp = [x for x in devs if (x.get("type") or "").lower() == "computer"]
            me = os.environ.get("COMPUTERNAME", "").lower()
            comp.sort(key=lambda x: (x.get("name", "").lower() != me, not x.get("is_active")))
            if comp and not self.device_id: self.device_id = comp[0]["id"]
        except Exception as e: log("Preview warm-up: %r" % e)

    def preview(self, track):
        """Play one track right now (editor preview, no fade). Starts Spotify / picks this PC like the switcher."""
        q = "?device_id=" + self.device_id if self.device_id else ""
        return self._play(track, {"uris": [track]}, q)

    def pause(self):
        q = "?device_id=" + self.device_id if self.device_id else ""
        code, _ = self._api("PUT", "/me/player/pause" + q)
        return code in (200, 202, 204)

    # ---- fading switch (runs in a background thread)
    # Two faders: LOCAL (Windows per-app volume of Spotify.exe: smooth 60 fps, no network) when Spotify on this
    # PC is the playing device, else the Web API volume, paced by a timer (fire-and-forget, newest value wins,
    # backs off on 429). Both use the same perceptual curve down to a quiet floor (never true silence), start
    # the new music at the floor, wait until it actually plays, fade back in, and restore the exact volume.
    def _set_vol(self, v):
        q = "&device_id=" + self.device_id if self.device_id else ""
        code, _ = self._api("PUT", "/me/player/volume?volume_percent=%d%s" % (max(0, min(100, int(round(v)))), q))
        return code in (200, 202, 204)

    def _fader(self, dev):
        """('local', session) when Spotify on this PC is the active device and its audio session is reachable."""
        if not dev or str(dev.get("type", "")).lower() != "computer": return None
        here = (os.environ.get("COMPUTERNAME") or "").lower()
        if not (dev.get("id") and dev.get("id") == self.device_id) and str(dev.get("name", "")).lower() != here: return None
        sess = SpotifySession.find()
        return sess if sess else None

    def _wait_started(self, old_item, timeout=1.6):
        """Hold at the quiet point until the new music is really playing (no fade-in over the gap)."""
        t0 = time.time()
        while time.time() - t0 < timeout:
            c, st = self._api("GET", "/me/player")
            if c == 200 and isinstance(st, dict) and st.get("is_playing") and (st.get("item") or {}).get("uri") != old_item \
                    and (st.get("progress_ms") or 0) > 0:
                return True
            time.sleep(0.12)
        return False

    # Volume ownership: we never keep an "original" beyond one switch. The level is read right before the fade;
    # if it moves away from what we last set (Spotify, Windows mixer, another device) that's the user: stop the
    # fade, leave their level alone, and just switch the music.
    def _run_fade(self, ctl, secs, down, gen):
        """Returns "done", "stop" (superseded / volume not allowed) or "user" (someone else changed the volume)."""
        t0 = time.perf_counter(); dt = 1.0 / ctl["fps"]; nchk = 0.0
        while True:
            if gen != self._gen: return "stop"
            el = time.perf_counter() - t0
            if el >= nchk and ctl["last"] is not None:
                cur = ctl["get"]()
                if cur is not None and not ctl["near"](cur): ctl["user"] = cur; return "user"
                nchk = el + ctl["every"]
            t = min(1.0, el / secs) if secs > 0 else 1.0
            v = ctl["orig"] * fade_gain(t if down else 1.0 - t)
            if ctl["set"](v) is False: return "stop"
            if t >= 1.0: return "done"
            time.sleep(dt)

    def _vol_ctl(self, mode, orig, sess=None):
        ctl = {"mode": mode, "orig": orig, "last": None, "user": None, "pacer": None}
        if mode == "local":
            def set_(v):
                sess.set(v); ctl["last"] = v; local_guard(orig, v); return True
            ctl.update(set=set_, get=lambda: sess.get(), near=lambda c: abs(c - ctl["last"]) <= 0.02, every=0.0, fps=60,
                       read=lambda: sess.get(), put=lambda v: sess.set(v))
        else:
            pacer = ApiVolumePacer(self); ctl["pacer"] = pacer; recent = []
            def set_(v):
                iv = int(round(v))
                if pacer.target(iv) is False: return False
                ctl["last"] = iv; recent.append(iv); del recent[:-12]; return True
            def get_():
                c, st = self._api("GET", "/me/player")
                d = (st or {}).get("device") if c == 200 and isinstance(st, dict) else None
                return float(d["volume_percent"]) if d and d.get("volume_percent") is not None else None
            near = lambda c: any(abs(c - x) <= 3 for x in recent + ([pacer.sent] if pacer.sent is not None else []))
            ctl.update(set=set_, get=get_, near=near, every=0.5, fps=1.0 / pacer.step, read=get_, put=lambda v: self._set_vol(v))
        return ctl

    def switch(self, uri, fade=2.0, player=None):
        player = player or self.play
        if not hasattr(self, "_glock"):
            self._glock = threading.Lock(); self._gen = 0
        with self._glock:
            self._gen += 1; gen = self._gen
            st = None
            if fade > 0:
                code, st = self._api("GET", "/me/player")
                st = st if code == 200 and isinstance(st, dict) else None
            dev = (st or {}).get("device")
            playing = bool(st and st.get("is_playing"))
            old_item = ((st or {}).get("item") or {}).get("uri")
            loc = self._fader(dev) if (playing and fade > 0) else None
            mode = cur = None
            if loc: mode, cur = "local", loc.get()           # Windows app volume; Spotify's own volume is never touched
            elif fade > 0 and playing and dev and dev.get("volume_percent") is not None and dev.get("supports_volume", True):
                mode, cur = "api", float(dev["volume_percent"])
            live = getattr(self, "_live", None)          # a fade a newer age-up just interrupted
            orig = cur
            if live and mode and live["mode"] == mode and live["last"] is not None and live["near"](cur):
                orig = live["orig"]                      # still dipped by us: go back to the level before that dip
            ctl = self._vol_ctl(mode, orig, loc) if mode else None
            self._live = ctl
        try:
            if not ctl:
                return player(uri)
            r = self._run_fade(ctl, fade, True, gen)
            if r == "stop":
                if gen != self._gen: return False
                log("Spotify: volume control not allowed on this device, switching without fade")
                return player(uri)
            if r == "user":
                log("Volume changed during the fade: keeping your level, switching without fade")
                return player(uri)
            log("Fade: %s, %.1fs each way" % ("Windows app volume" if ctl["mode"] == "local" else "Spotify volume", fade))
            ok = player(uri)
            if gen == self._gen: self._wait_started(old_item)
            r = self._run_fade(ctl, fade, False, gen)
            if r == "user": log("Volume changed during the fade: keeping your level")
            return ok
        finally:
            with self._glock:
                if ctl and gen == self._gen:
                    if ctl["user"] is None and ctl["last"] is not None:
                        cur = ctl["read"]()              # only undo OUR dip, never a newer user choice
                        if cur is None or ctl["near"](cur):
                            if ctl["pacer"] and not ctl["pacer"].fail: ctl["pacer"].target(ctl["orig"]); ctl["pacer"].flush()
                            else: ctl["put"](ctl["orig"])
                        else: log("Volume changed during the fade: keeping your level")
                    if ctl["mode"] == "local": local_guard(None)
                    self._live = None
                if ctl and ctl["pacer"]: ctl["pacer"].stop()

    # ---- Age 4 Intro theme (config key boss_intro): play one track, then the age playlist (runs in a background thread)
    def boss_then(self, track, playlist, fade=2.0):
        if not hasattr(self, "_glock"):
            self._glock = threading.Lock(); self._gen = 0
        dq = "?device_id=" + self.device_id if self.device_id else ""
        # intro must not loop: repeat off, then play it as a single-track list
        self._api("PUT", "/me/player/repeat?state=off" + dq.replace("?", "&"))
        ok = self.switch_uris(track, fade)
        gen = self._gen
        if not ok: return self.switch(playlist, fade)
        _, tr = self._api("GET", "/tracks/" + track.split(":")[-1])
        dur = (tr or {}).get("duration_ms", 240000) if isinstance(tr, dict) else 240000
        t0 = time.time(); started = False
        while time.time() - t0 < dur / 1000.0 + 15:
            time.sleep(2)
            if gen != self._gen: return                     # a newer switch took over
            c, st = self._api("GET", "/me/player")
            if c != 200 or not isinstance(st, dict): continue
            item = (st.get("item") or {}).get("uri")
            if item == track: started = True
            if started and item != track: break             # ended or skipped by the user
            if item == track and st.get("progress_ms", 0) >= dur - 2500: break   # about to end
            if started and not st.get("is_playing") and st.get("progress_ms", 1) == 0: break
        if gen != self._gen: return
        log("Age 4 Intro theme done -> playlist")
        self.switch(playlist, fade)

    def switch_uris(self, track, fade):
        """Like switch(), but plays a single track (uris) instead of a playlist context."""
        q = "?device_id=" + self.device_id if self.device_id else ""
        return self.switch(track, fade, player=lambda _u: self._play(track, {"uris": [track]}, q))

# ---------------------------------------------------------------- log parsing
RE_HUMAN   = re.compile(r"GAME -- Human Player: (\d+) (.+) (\d+) (\d+) (\S+)$")
RE_STEAM   = re.compile(r"GAME -- Current Steam name is \[(.*)\]")
RE_PROFILE = re.compile(r'WebSocketConnection::ProcessMessages: message=\[0,"\w+",(\d+),')  # recipient = local profile id
RE_BEGIN   = re.compile(r"\[Match Flow\] GameApp::RequestGameBegin\(\)")
RE_START   = re.compile(r"GAME -- Starting mission")
RE_REPLAY  = re.compile(r"PlaybackSynchronization::")
RE_UPSTART = re.compile(r"Age up started from (\w+) to (\w+) for player id (\d+)")
RE_UPDONE  = re.compile(r"Age up complete from (\w+) for player id (\d+)")
RE_END     = re.compile(r"MOD -- Game Over at frame|GameObj::ShutdownGameObj")
NEXT = {"dark_age": "feudal_age", "feudal_age": "castle_age", "castle_age": "imperial_age"}
KEY  = {"dark_age": "dark", "feudal_age": "feudal", "castle_age": "castle", "imperial_age": "imperial"}

class Tracker:
    """Match state machine. `play(key)` is called with dark/feudal/castle/imperial."""
    def __init__(self, cfg, play):
        self.cfg, self.play = cfg, play
        self.me_name = (cfg.get("player_name") or "").strip()
        self.me_profile = str(cfg.get("profile_id") or "").strip()
        self.crc_dir = None; self.my_slot = None; self.begin_t = 0; self.catching_up = False
        self.fixed_id = cfg.get("player_id")          # optional manual override (int)
        self.in_match = self.replay = False
        self.my_id = None; self.started = {}; self.ages = {}; self.recent = []
        self.lock = threading.Lock()

    def reset(self):
        self.in_match = True; self.replay = False
        self.my_id = self.fixed_id if isinstance(self.fixed_id, int) else None
        self.my_slot = None; self.begin_t = 0 if self.catching_up else time.time()
        self.started.clear(); self.ages.clear(); self.recent.clear()

    def feed(self, line):
        with self.lock: self._feed(line.rstrip("\r\n"))

    def _feed(self, line):
        m = RE_STEAM.search(line)
        if m: self.me_name = m.group(1); self.me_profile = ""; log("Local Steam name: %s" % self.me_name)
        m = RE_PROFILE.search(line)
        if m and not self.me_profile:
            self.me_profile = m.group(1); log("Local AoE4 profile id: %s" % self.me_profile)
        if RE_BEGIN.search(line):
            self.reset(); log("Match loading - state reset")
            return
        m = RE_HUMAN.search(line)
        if m and (m.group(3) == self.me_profile or (not self.me_profile and m.group(2) == self.me_name)):
            self.my_slot = int(m.group(1)); self.my_civ = m.group(5)
            log("You are lobby slot %s (%s), team %s" % (m.group(1), m.group(5), m.group(4)))
            return
        if RE_REPLAY.search(line) and self.in_match:
            self.replay = True; log("Replay detected - ignoring this match")
            return
        if RE_START.search(line):
            if not self.in_match: self.reset()
            self.resolve_id()
            log("Match started -> Dark Age playlist")
            self.play("dark", getattr(self, "my_civ", None)); return
        if RE_END.search(line) and self.in_match:
            self.in_match = False; log("Match over"); return
        m = RE_UPSTART.search(line)
        if m:
            pid = int(m.group(3)); new = m.group(2)
            self.started[pid] = new
            # Earliest signal: fires when the age-up transition begins (~5s before "complete").
            if self.in_match and not self.replay:
                if self.my_id is None: self.resolve_id()
                if pid == self.my_id and new in KEY and self.ages.get(pid) != new:
                    self.ages[pid] = new
                    log("YOU are aging up to %s -> %s playlist" % (new, KEY[new])); self.play(KEY[new], getattr(self, "my_civ", None))
            return
        m = RE_UPDONE.search(line)
        if m and self.in_match and not self.replay:
            pid = int(m.group(2)); new = NEXT.get(m.group(1)) or self.started.get(pid)
            already = self.ages.get(pid) == new          # switched on "started" already
            self.ages[pid] = new; self.recent.append((time.time(), pid))
            if already and pid == self.my_id: return
            if self.my_id is None: self.resolve_id()
            if self.my_id is None:
                log("Player %d reached %s - could not identify you, staying on current playlist" % (pid, new))
            elif pid == self.my_id and new in KEY:
                log("YOU reached %s -> %s playlist" % (new, KEY[new])); self.play(KEY[new], getattr(self, "my_civ", None))

    def resolve_id(self):
        """Map lobby slot -> sim player id via the playermap in LogFiles/DataCRC*.txt,
        which the game writes for every match while it loads (setupindex -> simid, id = simid-1000)."""
        if self.catching_up or self.my_id is not None or self.my_slot is None or not self.crc_dir: return
        try:
            files = [os.path.join(self.crc_dir, f) for f in os.listdir(self.crc_dir)
                     if f.startswith("DataCRC") and f.endswith(".txt")]
            newest = max(files, key=os.path.getmtime)
            if self.begin_t and os.path.getmtime(newest) < self.begin_t - 5:
                log("DataCRC file for this match not written yet"); return
            self.my_id = slot_to_id(newest).get(self.my_slot)
            log("Identified you as player id %s (slot %d, from %s)" % (self.my_id, self.my_slot, os.path.basename(newest)))
        except Exception as e:
            log("Could not read DataCRC player map: %s" % e)

# ---------------------------------------------------------------- Age 4 Intro theme (config key boss_intro)
# When YOU reach a configured age (default Imperial), first play one "Age 4 Intro theme" track picked
# by your civ, then continue into that age's playlist. Pools live in config.json "boss_intro".
BOSS_STATE = os.path.join(globals().get("DATA", HERE), "boss_state.json")   # last pick per civ

def intro_of(cfg, age):
    it = (cfg.get("intros") or {}).get(age)
    if it: return it
    b = cfg.get("boss_intro") or {}
    return {"enabled": age in (b.get("ages") or ["imperial"]), "pools": b.get("pools") or {}}

def pick_boss_track(cfg, civ, age="imperial"):
    b = cfg.get("boss_intro") or {}
    pools = intro_of(cfg, age)["pools"]
    fallback = (b.get("default") or []) if age == "imperial" else []    # other ages: empty civ = no intro
    pool = [u for u in (pools[civ] if civ in pools else fallback) if u.startswith("spotify:track:")]   # [] = no intro
    if not pool: return None
    try: state = json.load(open(BOSS_STATE, encoding="utf-8"))
    except Exception: state = {}
    choices = [u for u in pool if u != state.get(civ)] or pool      # never the same as last time
    uri = random.choice(choices)
    state[civ] = uri
    try: json.dump(state, open(BOSS_STATE, "w", encoding="utf-8"), indent=1)
    except Exception as e: log("Could not save boss state: %r" % e)
    return uri

def choose_intro(cfg, age, civ):
    """The intro track to play when entering `age` as `civ`, or None (intro off, or that civ has no songs
    in this age): then the switcher just plays the age playlist."""
    return pick_boss_track(cfg, civ, age) if civ and boss_age(cfg, age) else None

def boss_age(cfg, key):
    b = cfg.get("boss_intro") or {}
    return bool(b.get("enabled", True)) and key in INTRO_AGES and bool(intro_of(cfg, key)["enabled"])

def slot_to_id(path):
    with open(path, encoding="utf-8", errors="replace") as f: t = f.read()
    i = t.index("playermap:"); blk = t[i:t.index("}", i)]
    return {int(s): int(m) - 1000 for s, m in
            re.findall(r"setupindex: \[ (\d+) \]\s*simid: \[ (\d+) \]", blk)}

# ---------------------------------------------------------------- tailing
def tail(path, tracker, stop=None):
    """Read the whole current log silently (catch-up: learn who you are / current match state),
    then follow new lines live. Handles the log being recreated or truncated."""
    pos, ino, last_check = 0, None, 0
    real_play = tracker.play
    tracker.play = lambda *a: None          # catch-up: no Spotify calls
    tracker.catching_up = True
    caught_up = False
    log("Watching %s" % path)
    while True:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            time.sleep(2); continue
        key = st.st_ctime
        if ino is not None and (key != ino or st.st_size < pos):
            log("Log was recreated/truncated (game restarted) - reading from start")
            pos = 0
        ino = key
        if st.st_size > pos:
            with open(path, "rb") as f:
                f.seek(pos); data = f.read()
            cut = data.rfind(b"\n") + 1
            for line in data[:cut].decode("utf-8", errors="replace").splitlines(): tracker.feed(line)
            pos += cut
        if not caught_up:
            caught_up = True; tracker.play = real_play; tracker.catching_up = False
            with tracker.lock:
                if tracker.in_match and not tracker.replay:
                    if tracker.my_id is None: tracker.resolve_id()
                    age = tracker.ages.get(tracker.my_id, "dark_age") if tracker.my_id is not None else "dark_age"
                    log("Joined mid-match, you are in %s" % age); real_play(KEY.get(age, "dark"))
        if stop and time.time() - last_check > 10:
            last_check = time.time()
            if stop(): return
        time.sleep(0.5)

NOWIN = 0x08000000  # CREATE_NO_WINDOW

# ---------------------------------------------------------------- game music mute
# AoE4 keeps its music volume in configuration_system.lua (setting = "musicvolume", variantFloat = X).
# It reads the file at launch and rewrites it on exit, so we only touch it while the game is closed.
# While the app is enabled the game music is 0; your own level is kept in game_music.json and put back
# when you disable/uninstall. A non-zero value found after a match = you changed it in-game: keep that.
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
    if new != data: open(p + ".tmp", "wb").write(new); os.replace(p + ".tmp", p)
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
                json.dump({"level": v}, open(MUSIC_STATE, "w")); music_write(0.0); log("Game music muted (your level %.2f saved)" % v)
        else:
            lv = music_saved()
            if lv and v == 0: music_write(lv); log("Game music restored to %.2f" % lv)
            if lv is not None:
                try: os.remove(MUSIC_STATE)
                except OSError: pass
        return True
    except Exception as e:
        log("Game music: %r" % e); return False

def aoe_running():
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq RelicCardinal.exe", "/NH"],
                             capture_output=True, text=True, creationflags=NOWIN).stdout
        return "RelicCardinal.exe" in out
    except Exception:
        return False

_WINDOW_MUTEXES = {}
def single_window(name, title):
    """One window of each kind (panel, good-to-go, editor) per user. Returns True if this process may open it.
    Otherwise brings the existing window to the front (restoring it if minimized) and returns False.
    Separate from the switcher's single-instance guard."""
    try:
        import ctypes
        k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
        k32.CreateMutexW.restype = ctypes.c_void_p
        nm = "Local\\AoE4Spotify_window_%s%s" % (name, os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX", ""))  # suffix: tests only
        h = k32.CreateMutexW(None, False, nm)
        if k32.GetLastError() == 183:             # ERROR_ALREADY_EXISTS
            if h: k32.CloseHandle(ctypes.c_void_p(h))
            u32.FindWindowW.restype = ctypes.c_void_p
            w = None
            try:                                   # exact window recorded by the owner (titles can repeat)
                w = int(open(_hwnd_file(name)).read()) or None
                if not u32.IsWindow(ctypes.c_void_p(w)): w = None
            except Exception: w = None
            w = w or u32.FindWindowW(None, title)
            if w:
                if u32.IsIconic(ctypes.c_void_p(w)): u32.ShowWindow(ctypes.c_void_p(w), 9)   # SW_RESTORE
                u32.SetForegroundWindow(ctypes.c_void_p(w))
            log("%s is already open - brought it to the front" % title)
            return False
        _WINDOW_MUTEXES[name] = h
        return True
    except Exception:
        return True                               # not Windows / no ctypes: no guard

def _hwnd_file(name):
    return os.path.join(os.environ.get("TEMP", HERE), "AoE4Spotify_window_%s%s.hwnd" % (name, os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX", "")))

def note_window(name, win):
    """Remember our top-level window handle so a second launch focuses exactly this window."""
    try:
        if sys.platform == "win32": open(_hwnd_file(name), "w").write(str(int(win.wm_frame(), 16)))
    except Exception: pass

def release_window(name):
    try: os.remove(_hwnd_file(name))
    except OSError: pass
    h = _WINDOW_MUTEXES.pop(name, None)
    if h:
        try: import ctypes; ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(h))
        except Exception: pass

def single_instance():
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "AoE4SpotifySwitcherMutex")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS

# ---------------------------------------------------------------- Steam launch option
# The installer calls `AoE4 Spotify.exe --set-launch-option` / `--remove-launch-option`.
# It edits userdata/<id>/config/localconfig.vdf for every Steam user (Steam must be closed,
# because Steam rewrites that file while running). The original value is saved so uninstall
# restores it exactly.
APPID = "1466860"   # Age of Empires IV on Steam
STATE = os.path.join(HERE, "launch_option_backup.json")

def test_env(name):
    """Test-only overrides (fake Steam etc.): honoured from source, or in the exe only with AOE4SPOTIFY_TEST=1,
    so a stray variable can never redirect a real install."""
    if FROZEN and os.environ.get("AOE4SPOTIFY_TEST") != "1": return None
    return os.environ.get(name) or None

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
    json.dump(old_state, open(STATE, "w"), indent=1)

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

def spotify_installed():
    return (os.path.isfile(os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Spotify.exe"))
            or os.path.isdir(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", STORE_APP))
            or _spotify_protocol_registered())

def setup_status(sp):
    """What the 'You're good to go' window shows."""
    st = {"ok": bool(sp and sp.tok), "name": None, "steam": None, "spotify_app": spotify_installed()}
    if st["ok"]:
        c, r = sp._api("GET", "/me")
        if c == 200 and isinstance(r, dict): st["name"] = r.get("display_name") or r.get("id")
    try: st["steam"] = launch_option_is_set()
    except Exception as e: log("Launch option check failed: %r" % e)
    return st

def open_panel_process():
    import subprocess
    cmd = [sys.executable, "--panel"] if FROZEN else [sys.executable, os.path.abspath(__file__), "--panel"]
    subprocess.Popen(cmd, env=child_env())

# ---------------------------------------------------------------- "You're good to go" window
def good_to_go(status, parent=None, on_open_panel=None, on_retry=None, fix=None):
    """Panel-style result window after Spotify login. status from setup_status().
    parent: an existing Tk root (from the panel) or None (own window, blocks until closed)."""
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk
    try: import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", red="#e5484d", warn="#f5a524")
    if not single_window("gtg", "AoE4 Spotify"): return None
    win = tk.Toplevel(parent) if parent else tk.Tk()
    dark_window(win, C["bg"])
    win.bind("<Destroy>", lambda e: release_window("gtg") if e.widget is win else None, add="+")
    win.title("AoE4 Spotify"); win.configure(bg=C["bg"]); win.resizable(False, False)
    S = win.winfo_fpixels("1i") / 96.0
    W = 400
    cv = tk.Canvas(win, width=int(W * S), height=10, bg=C["bg"], highlightthickness=0); cv.pack()
    imgs = []
    def F(sz, b=False): return ("Segoe UI", -int(sz * S), "bold" if b else "normal")
    def pil(w, h, paint):                         # 4x supersampled, anti-aliased
        m = 4; im = Image.new("RGBA", (int(w * S * m), int(h * S * m)), (0, 0, 0, 0)); paint(ImageDraw.Draw(im), S * m)
        ph = ImageTk.PhotoImage(im.resize((max(1, int(w * S)), max(1, int(h * S))), Image.LANCZOS), master=win)
        imgs.append(ph); return ph
    def rr(x0, y0, x1, y1, r, fill, outline=None, tag=None):
        ph = pil(x1 - x0, y1 - y0, lambda d, k: d.rounded_rectangle([0, 0, (x1-x0)*k - 1, (y1-y0)*k - 1], r * k, fill=fill,
                                                                   outline=outline, width=int(2 * k) if outline else 0))
        cv.create_image(x0 * S, y0 * S, image=ph, anchor="nw", tags=tag or ())
    def mark(cx, cy, size, kind, tag=None):       # filled circle with a check / cross / !
        col = {"ok": C["acc"], "bad": C["red"], "warn": C["warn"]}[kind]
        def paint(d, k):
            z = size * k; d.ellipse([0, 0, z - 1, z - 1], fill=col); w = max(2, int(z * 0.11))
            if kind == "ok": d.line([(z*.28, z*.52), (z*.44, z*.68), (z*.73, z*.36)], fill="#121212", width=w, joint="curve")
            elif kind == "bad":
                d.line([(z*.32, z*.32), (z*.68, z*.68)], fill="#121212", width=w); d.line([(z*.68, z*.32), (z*.32, z*.68)], fill="#121212", width=w)
            else:
                d.line([(z*.5, z*.24), (z*.5, z*.58)], fill="#121212", width=w); d.ellipse([z*.44, z*.68, z*.56, z*.80], fill="#121212")
        cv.create_image(cx * S, cy * S, image=pil(size, size, paint), anchor="center", tags=tag or ())
    def text(x, y, s, sz, c=None, b=False, anchor="w", tag=None):
        cv.create_text(x * S, y * S, text=s, font=F(sz, b), fill=c or C["tx"], anchor=anchor, tags=tag or ())
    actions = {}
    def button(x0, y0, x1, y1, label, primary, fn, tag):
        rr(x0, y0, x1, y1, (y1 - y0) / 2, C["acc"] if primary else C["card"], None if primary else C["mu"], tag)
        text((x0 + x1) / 2, (y0 + y1) / 2, label, 12, "#121212" if primary else C["tx"], True, "center", tag)
        actions[tag] = fn
        cv.tag_bind(tag, "<Button-1>", lambda e, t=tag: win.after_idle(actions[t]))
        if not getattr(cv, "_ptr", False):
            cv._ptr = True
            def ptr(e):
                tags = set()
                for it in cv.find_overlapping(e.x, e.y, e.x, e.y): tags.update(cv.gettags(it))
                c_ = "hand2" if any(t in actions for t in tags) else ""
                if cv.cget("cursor") != c_: cv.config(cursor=c_)
            cv.bind("<Motion>", ptr, add="+"); cv.bind("<Leave>", lambda e: cv.cget("cursor") and cv.config(cursor=""), add="+")
    def close():
        try: win.destroy()
        except tk.TclError: pass
    # Animated avatar: bundled face sprite (assets/gtg_face.jpg + .json), soft round mask, thin green ring, check badge.
    try: meta = json.load(open(os.path.join(ASSETS, "assets", "gtg_face.json")))
    except Exception: meta = {}
    R = 62                                        # avatar radius
    faces = []
    def load_faces():
        from PIL import ImageFilter, ImageChops
        D = int(2 * R * S)
        m = Image.new("L", (D * 4, D * 4), 0); ImageDraw.Draw(m).ellipse([0, 0, D * 4 - 1, D * 4 - 1], fill=255)
        m = m.resize((D, D), Image.LANCZOS)
        fade = Image.new("L", (D, D), 0); e = max(2, int(5 * S)); ImageDraw.Draw(fade).ellipse([e, e, D - e, D - e], fill=255)
        mask = ImageChops.multiply(m, fade.filter(ImageFilter.GaussianBlur(4.5 * S)))
        frames = []
        try:                                       # one sprite sheet (assets/gtg_face.jpg), cut into frames here
            sheet = Image.open(os.path.join(ASSETS, "assets", "gtg_face.jpg")).convert("RGB"); z, cols, n = meta["size"], meta["cols"], meta["count"]
        except Exception as ex: log("Face sprite: %r" % ex); return frames
        for i in range(n):
            f = sheet.crop(((i % cols) * z, (i // cols) * z, (i % cols + 1) * z, (i // cols + 1) * z)).resize((D, D), Image.LANCZOS)
            im = Image.new("RGB", (D, D), C["bg"]); im.paste(f, (0, 0), mask)
            frames.append(ImageTk.PhotoImage(im, master=win))
        return frames                              # played straight through, then loops
    anim = {"i": 0}
    durs = meta.get("durations_ms") or []
    def animate():                                 # original per-frame timing of the source GIF
        if not win.winfo_exists(): return
        it = cv.find_withtag("avatar")
        if it and faces:
            anim["i"] = (anim["i"] + 1) % len(faces); cv.itemconfig(it[0], image=faces[anim["i"]])
        win.after(int(durs[anim["i"]]) if anim["i"] < len(durs) else 70, animate)
    def draw():
        cv.delete("all"); imgs.clear(); actions.clear()
        ok = status["ok"]
        if ok:
            CY = 22 + R
            if faces: cv.create_image(W / 2 * S, CY * S, image=faces[anim["i"] % len(faces)], anchor="center", tags="avatar")
            else: mark(W / 2, CY, 2 * R, "ok")
            rg = R + 3
            cv.create_image(W / 2 * S, CY * S, anchor="center", image=pil(2 * rg + 2, 2 * rg + 2,
                lambda d, k: d.ellipse([k, k, (2 * rg + 1) * k, (2 * rg + 1) * k], outline=C["acc"], width=int(1.5 * k))))
            bx, by = W / 2 + R * 0.72, CY + R * 0.72
            cv.create_image(bx * S, by * S, anchor="center", image=pil(34, 34, lambda d, k: d.ellipse([0, 0, 34 * k - 1, 34 * k - 1], fill=C["bg"])))
            mark(bx, by, 28, "ok")
            y = CY + R + 30
        else:
            mark(W / 2, 54, 64, "bad"); y = 112
        text(W / 2, y, "You're good to go" if ok else "Spotify login didn't finish", 19, b=True, anchor="center")
        y += 28
        if ok:
            app_ok = status.get("spotify_app", True)
            sub = ("Connected as %s" % status["name"]) if status.get("name") else "Connected"
            rows = [("ok" if app_ok else "warn", "Spotify", sub if app_ok else "Spotify app not installed", None)]
            st = status.get("steam")
            if st: rows.append(("ok", "Age of Empires IV", "Starts with the game", None))
            elif st is False: rows.append(("warn", "Age of Empires IV", "Launch option missing", "fix"))
            else: rows.append(("warn", "Age of Empires IV", "Steam not found", None))
            rows.append(("warn", "Skill", "Issue detected", None))     # the joke row (always)
            for kind, lab, detail, act in rows:
                rr(20, y, W - 20, y + 40, 10, C["card"])
                mark(42, y + 20, 18, kind); text(60, y + 20, lab, 12, b=True)
                if act == "fix":
                    text(W - 92, y + 20, detail, 11, C["mu"], anchor="e")
                    button(W - 84, y + 8, W - 30, y + 32, "Fix", True, do_fix, "b_fix")
                else: text(W - 32, y + 20, detail, 11, C["mu"], anchor="e")
                y += 48
            y += 6
            button(20, y, W / 2 - 6, y + 40, "Open panel", False, open_panel, "b_panel")
            button(W / 2 + 6, y, W - 20, y + 40, "Done", True, close, "b_done")
        else:
            text(W / 2, y + 4, "Log in to Spotify and click Agree.", 12, C["mu"], anchor="center"); y += 30
            button(20, y, W / 2 - 6, y + 40, "Close", False, close, "b_done")
            button(W / 2 + 6, y, W - 20, y + 40, "Try again", True, retry, "b_retry")
        cv.config(height=int((y + 60) * S))
    def do_fix():
        if not fix: return
        text(W / 2, 20, "Steam closes and reopens...", 10, C["mu"], anchor="center")
        done = []
        def go():
            try: fix()
            except Exception as e: log("Fix launch option failed: %r" % e)
            try: done.append(launch_option_is_set())
            except Exception: done.append(None)
        def poll():                               # Tk must only be touched from this thread
            if done: status.update(steam=done[0]); draw()
            else: win.after(200, poll)
        threading.Thread(target=go, daemon=True).start(); poll()
    def open_panel():
        (on_open_panel or open_panel_process)(); close()
    def retry():
        close()
        if on_retry: on_retry()
    set_app_icon(win)
    faces.extend(load_faces())
    draw(); animate()
    win._gtg = {"cv": cv, "status": status, "actions": actions, "draw": draw}   # for tests
    reveal(win, over=parent); note_window("gtg", win); win.lift(); win.attributes("-topmost", True); win.after(300, lambda: win.attributes("-topmost", False))
    if parent is None: win.mainloop()
    return win

def dark_window(win, bg):
    """Start hidden with the dark background, so a window never flashes white while it is built."""
    try: win.withdraw()
    except Exception: pass
    win.configure(bg=bg)

def place_centered(win, over=None):
    """Centre on the primary monitor's work area, or over a visible parent window."""
    try:
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        wa = None
        if sys.platform == "win32":
            import ctypes, ctypes.wintypes as wt
            class MI(ctypes.Structure):
                _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
            u32 = ctypes.windll.user32; pt = wt.POINT(0, 0); flag = 1        # (0,0) + DEFAULTTOPRIMARY = primary monitor
            if over is not None and over.winfo_viewable():
                pt = wt.POINT(over.winfo_rootx() + over.winfo_width() // 2, over.winfo_rooty() + over.winfo_height() // 2); flag = 2
            u32.MonitorFromPoint.restype = ctypes.c_void_p
            mon = u32.MonitorFromPoint(pt, flag)
            mi = MI(); mi.cbSize = ctypes.sizeof(MI)
            if mon and u32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(mi)):
                r = mi.rcWork; wa = (r.left, r.top, r.right, r.bottom)
        if wa is None: wa = (0, 0, win.winfo_screenwidth(), win.winfo_screenheight())
        if over is not None and over.winfo_viewable():
            cx, cy = over.winfo_rootx() + over.winfo_width() // 2, over.winfo_rooty() + over.winfo_height() // 2
        else:
            cx, cy = (wa[0] + wa[2]) // 2, (wa[1] + wa[3]) // 2
        tb = int(32 * win.winfo_fpixels("1i") / 96.0)                # title bar height
        x = max(wa[0], min(cx - w // 2, wa[2] - w)); y = max(wa[1], min(cy - (h + tb) // 2, wa[3] - h - tb))
        win.geometry("+%d+%d" % (x, y))
    except Exception as e:
        log("Window placement: %r" % e)

def reveal(win, fade=True, over=None):
    """Show a window built hidden in one step: final position, dark title bar and first frame are set while withdrawn."""
    try:
        place_centered(win, over)
        win.update_idletasks()
        if sys.platform == "win32":
            import ctypes
            hwnd = ctypes.c_void_p(int(win.wm_frame(), 16)); on = ctypes.c_int(1)
            for attr in (20, 19):                          # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Win10)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0: break
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(on), 4)   # DWMWA_TRANSITIONS_FORCEDISABLED: no zoom/fade-in animation
        # Map it invisible, let Tk paint the first frame, then show it in one step. (Windows paints a new
        # window's client area white before Tk draws; the DWM open animation and our old fade made that a blink.)
        win.attributes("-alpha", 0.0); win.deiconify(); win.update()
        def show():
            try: win.attributes("-alpha", 1.0)
            except Exception: pass
        win.after(40, show)
    except Exception as e:
        log("Window reveal: %r" % e)
        try: win.deiconify(); win.attributes("-alpha", 1.0)
        except Exception: pass

def app_badge(px):
    """The app icon (green circle, "IV") as a PIL image: largest frame of the bundled app.ico, else drawn like make_icon.py."""
    from PIL import Image, ImageDraw
    try:
        ico = Image.open(os.path.join(ASSETS, "assets", "app.ico")); ico.size = max(ico.info.get("sizes") or [ico.size])
        return ico.convert("RGBA").resize((px, px), Image.LANCZOS)
    except Exception: pass
    ss = 8; N = px * ss; k = N / 1024; ox, oy, w = 0.409, -0.5, 92
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse([16 * k, 16 * k, N - 16 * k, N - 16 * k], fill="#1DB954")
    for pts in ([(310, 320), (310, 704)], [(490, 320), (620, 704), (750, 320)]):
        P = [((x + ox) * k, (y + oy) * k) for x, y in pts]; r = w * k / 2
        for a, b in zip(P, P[1:]): d.line([a, b], fill="#191414", width=int(w * k))
        for x, y in P: d.ellipse([x - r, y - r, x + r, y + r], fill="#191414")
    return im.resize((px, px), Image.LANCZOS)

def set_app_icon(win):
    """Title-bar icon = app.ico (bundled), so it matches the exe and shortcuts."""
    ico = os.path.join(ASSETS, "assets", "app.ico")
    try:
        if os.path.exists(ico): win.iconbitmap(ico); win.iconbitmap(default=ico); return
    except Exception as e: log("Icon: %r" % e)

# ---------------------------------------------------------------- "Not invited yet" (Spotify app in development mode)
ACCOUNT_URL = "https://www.spotify.com/account/overview/"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")
ACCESS_GAP = 600                                       # one request per 10 min per install

def not_invited(code, body):
    """True when Spotify refuses this account because it isn't on the app's user list (dev-mode 403)."""
    if code != 403: return False
    t = json.dumps(body).lower() if not isinstance(body, str) else body.lower()
    return "not registered" in t or "developer dashboard" in t or "user may not be registered" in t

def access_status(sp):
    """'ok', 'blocked' or None (offline / not logged in)."""
    if not (sp and sp.tok): return None
    c, r = sp._api("GET", "/me")
    if c == 200: return "ok"
    return "blocked" if not_invited(c, r) else None

def webhook_ok(url):
    if not isinstance(url, str) or not url: return False
    if url.startswith("https://api2.cursor.sh/automations/webhook/"): return True
    return bool(test_env("AOE4SPOTIFY_TEST")) and url.startswith("http://127.0.0.1:")

def send_access_request(cfg, email, name=None, now=None):
    """POST one request to the configured Discord webhook. Returns 'sent', 'wait', 'off', 'bad' or 'error'.
    Only ever called from the 'Send request' button."""
    url = cfg.get("access_webhook"); now = now or time.time()
    if not webhook_ok(url): return "off"
    if not EMAIL_RE.match(email or ""): return "bad"
    u = load_user_settings()
    if now - float(u.get("access_last") or 0) < ACCESS_GAP: return "wait"
    hdr = {"Content-Type": "application/json", "User-Agent": "AoE4Spotify/" + VERSION}
    if cfg.get("access_key"): hdr["Authorization"] = "Bearer " + str(cfg["access_key"])
    try:
        req = urllib.request.Request(url, data=json.dumps({"email": email, "name": name or None, "version": VERSION}).encode(), headers=hdr, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r: ok_ = 200 <= r.status < 300
    except urllib.error.HTTPError as e: log("Access request failed: HTTP %s" % e.code); return "error"
    except Exception as e: log("Access request failed: %s" % type(e).__name__); return "error"     # never logs the URL/key
    if not ok_: return "error"
    u["access_last"] = now; u["access_pending"] = True; save_user(u); log("Access request sent")
    return "sent"

def windows_light():
    """True when Windows apps use the light theme (HKCU ...\\Themes\\Personalize AppsUseLightTheme = 1)."""
    if test_env("AOE4SPOTIFY_THEME") in ("light", "dark"): return test_env("AOE4SPOTIFY_THEME") == "light"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "AppsUseLightTheme")[0])
    except Exception: return False

def set_titlebar(win, dark):
    if sys.platform != "win32": return
    try:
        import ctypes
        hwnd = ctypes.c_void_p(int(win.wm_frame(), 16)); v = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), 4) == 0: break
    except Exception: pass

ACCESS_THEMES = {   # soft, no pure white / pure black; same Spotify green family in both
    "dark":  dict(bg="#171717", card="#222222", tx="#e6e6e3", mu="#a3a29f", g="#1db954", gtx="#0e1a12", gact="#2fcf68", gdis="#35503f",
                  gdtx="#5f7a68", b2="#303030", b2a="#3a3a3a", b2tx="#e6e6e3", dis="#6c6c6c", ent="#2c2c2c", enttx="#ececea", err="#e8958c",
                  pg=(46, 46, 46), pgbar=(34, 34, 34), pglab=(170, 170, 166), pgline=(78, 78, 78), hl=(30, 66, 44), hlo=(29, 185, 84), hltx=(232, 232, 228)),
    "light": dict(bg="#efeeea", card="#e3e1dc", tx="#2b2b2a", mu="#62615d", g="#1a9f4a", gtx="#f4f3ef", gact="#178c41", gdis="#a9c8b3",
                  gdtx="#e8efe9", b2="#d4d2cc", b2a="#c9c7c1", b2tx="#2b2b2a", dis="#9a9893", ent="#f6f5f1", enttx="#262625", err="#b4473c",
                  pg=(240, 239, 235), pgbar=(204, 202, 197), pglab=(88, 88, 85), pgline=(206, 204, 199), hl=(208, 232, 214), hlo=(26, 159, 74), hltx=(36, 36, 34)),
}

def access_dialog(parent=None, on_allowed=None, name=None, recheck_ms=60000):
    """Simple 3-step 'Not invited yet' guide. Everything is drawn on one canvas from 4x-supersampled images on a
    strict grid (cards r=12, pill buttons, box r=8); follows the Windows light/dark theme live.
    Rechecks every minute; closes and calls on_allowed() once access works."""
    if not single_window("access", "AoE4 Spotify - Get access"): return None
    import tkinter as tk, webbrowser as wb
    from PIL import Image, ImageDraw, ImageTk, ImageFont
    own = parent is None
    win = tk.Tk() if own else tk.Toplevel(parent)
    if own: win.withdraw()
    th = {"light": windows_light()}; P = lambda: ACCESS_THEMES["light" if th["light"] else "dark"]
    dark_window(win, P()["bg"]); win.title("AoE4 Spotify - Get access"); win.resizable(False, False)
    win.bind("<Destroy>", lambda e: release_window("access") if e.widget is win else None, add="+")
    S = win.winfo_fpixels("1i") / 96.0; F = lambda sz, b=True: ("Segoe UI", -int(round(sz * S)), "bold" if b else "normal")
    cfg = load_config(); st = {"sent": False, "job": None, "clip": None, "allowed": False, "hov": None, "focus": False, "b3": "disabled", "b3t": "Send request", "note": None}
    on = webhook_ok(cfg.get("access_webhook"))
    st["note"] = ("" if on else "Requests not set up yet", "mu")
    # ---- grid (logical px)
    W = 500; M = 20; PAD = 18; BD = 36; GAP = 12
    BX = M + PAD + BD / 2                               # badge centre x (all steps)
    CX = M + PAD + BD + 14                              # card content left edge (titles, buttons, picture, box)
    CR = W - M - PAD                                    # card content right edge
    HDR = 96                                            # cards start
    H1, H2, H3 = 114, 233, 196                          # card heights: 18 px below the last content in every card
    Y1 = HDR; Y2 = Y1 + H1 + GAP; Y3 = Y2 + H2 + GAP; HH = Y3 + H3 + M
    TY = 30                                             # step title centre, from the card top (= badge centre)
    IW, IH = W - M - PAD - CX, 118                      # illustration box
    BOXW, BOXH = 300, 44
    G = {"lay": dict(W=W, BX=BX, CX=CX, CR=CR, Y=(Y1, Y2, Y3), H=(H1, H2, H3), TY=TY, GAP=GAP, BOXW=BOXW, BOXH=BOXH, IW=IW, IH=IH)}
    cv = tk.Canvas(win, width=even_px(W, S), height=even_px(HH, S), highlightthickness=0, bd=0); cv.pack()
    imgs = {}
    def rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    def rr_img(w, h, r, fill, outline=None, ow=0.0):
        k = ("rr", w, h, r, fill, outline, ow)
        if k not in imgs:
            Q = 4; Wp, Hp = even_px(w, S), even_px(h, S); im = Image.new("RGBA", (Wp * Q, Hp * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
            if outline and ow:
                d.rounded_rectangle([0, 0, Wp * Q - 1, Hp * Q - 1], r * S * Q, fill=rgb(outline))
                o = ow * S * Q; d.rounded_rectangle([o, o, Wp * Q - 1 - o, Hp * Q - 1 - o], max(0, r * S * Q - o), fill=rgb(fill))
            else: d.rounded_rectangle([0, 0, Wp * Q - 1, Hp * Q - 1], r * S * Q, fill=rgb(fill))
            imgs[k] = ImageTk.PhotoImage(im.resize((Wp, Hp), Image.LANCZOS), master=win)
        return imgs[k]
    def badge_img(n, fill, fg):
        k = ("badge", n, fill, fg)
        if k not in imgs:
            Q = 4; D = even_px(BD, S); B = D * Q; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); ImageDraw.Draw(im).ellipse([0, 0, B - 1, B - 1], fill=rgb(fill))
            tl = Image.new("RGBA", (B, B), (0, 0, 0, 0))
            try: fnt = ImageFont.truetype("segoeuib.ttf", int(17 * S * Q))
            except Exception: fnt = None
            ImageDraw.Draw(tl).text((B / 2, B / 2), str(n), font=fnt, fill=rgb(fg), anchor="mm")
            im = Image.alpha_composite(im, ink_centre(tl)); imgs[k] = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=win)
        return imgs[k]
    def check_img(fill, fg):
        k = ("check", fill, fg)
        if k not in imgs:
            Q = 4; D = even_px(26, S); B = D * Q; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
            d.ellipse([0, 0, B - 1, B - 1], fill=rgb(fill)); u = B / 26.0
            d.line([(7.5 * u, 13.5 * u), (11.2 * u, 17.2 * u), (18.5 * u, 9.3 * u)], fill=rgb(fg), width=int(2.6 * u), joint="curve")
            for x, y in ((7.5, 13.5), (18.5, 9.3)): d.ellipse([(x - 1.3) * u, (y - 1.3) * u, (x + 1.3) * u, (y + 1.3) * u], fill=rgb(fg))
            imgs[k] = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=win)
        return imgs[k]
    def illustration():
        p = P(); k_ = ("illu", th["light"])
        if k_ in imgs: return imgs[k_]
        Q = 4; Wp, Hp = even_px(IW, S), even_px(IH, S); u = Wp * Q / IW; L = lambda v: v * u; SW = 1.8                # one stroke width everywhere
        im = Image.new("RGBA", (Wp * Q, Hp * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        try:
            fb = ImageFont.truetype("segoeuib.ttf", int(L(10.5))); fr = ImageFont.truetype("segoeui.ttf", int(L(10))); fh = ImageFont.truetype("segoeuib.ttf", int(L(11.5)))
        except Exception: fb = fr = fh = None
        def line(pts, c, w=SW):
            d.line([(L(x), L(y)) for x, y in pts], fill=c, width=int(round(L(w))), joint="curve")
            for x, y in (pts[0], pts[-1]): r = w / 2; d.ellipse([L(x - r), L(y - r), L(x + r), L(y + r)], fill=c)   # round caps
        pw = (IW - 24) / 2                                   # two equal mini pages, 24 px gutter for the arrow
        lx0, lx1, rx0, rx1 = 0, pw, IW - pw, IW
        for x0, x1 in ((lx0, lx1), (rx0, rx1)): d.rounded_rectangle([L(x0), 0, L(x1) - 1, Hp * Q - 1], L(10), fill=p["pg"])
        # left page: Account -> pencil row
        d.text((L(lx0 + 12), L(18)), "Account", fill=p["pglab"], font=fh, anchor="lm")
        ry0, ry1 = 34, 62; cy = (ry0 + ry1) / 2
        d.rounded_rectangle([L(lx0 + 8), L(ry0), L(lx1 - 8), L(ry1)], L(8), fill=p["hl"], outline=p["hlo"], width=int(round(L(SW))))
        d.rounded_rectangle([L(lx0 + 14), L(cy - 8), L(lx0 + 30), L(cy + 8)], L(4), fill=p["pgline"])
        pc = (lx0 + 22, cy)                                   # pencil: shaft + tip, 45 degrees, crisp
        line([(pc[0] - 3.2, pc[1] + 3.2), (pc[0] + 3.6, pc[1] - 3.6)], p["hltx"], 2.2)
        d.polygon([(L(pc[0] - 5.2), L(pc[1] + 5.2)), (L(pc[0] - 4.6), L(pc[1] + 2.4)), (L(pc[0] - 2.4), L(pc[1] + 4.6))], fill=p["hltx"])
        d.text((L(lx0 + 37), L(cy)), "Edit personal info", fill=p["hltx"], font=fb, anchor="lm")
        line([(lx1 - 20, cy - 4), (lx1 - 16, cy), (lx1 - 20, cy + 4)], p["hltx"])
        for i, w_ in enumerate((0.62, 0.45)): d.rounded_rectangle([L(lx0 + 12), L(78 + i * 15), L(lx0 + 12 + (pw - 24) * w_), L(84 + i * 15)], L(3), fill=p["pgline"])
        # pointer (classic proportions: 12 x 18), tip on the row, white-ish edge so it reads on both themes
        px, py = lx1 - 44, cy + 2
        ptr = [(0, 0), (0, 15.5), (3.8, 12.2), (6.6, 18), (9.2, 16.8), (6.5, 11.2), (11.4, 11.2)]
        d.polygon([(L(px + x), L(py + y)) for x, y in ptr], fill=p["hltx"], outline=p["pg"], width=int(round(L(1.2))))
        # arrow between the pages
        ax0, ax1, ay = lx1 + 6, rx0 - 6, IH / 2
        line([(ax0, ay), (ax1, ay)], p["hlo"], 2.0); line([(ax1 - 4.5, ay - 4.5), (ax1, ay), (ax1 - 4.5, ay + 4.5)], p["hlo"], 2.0)
        # right page: Email field
        d.rounded_rectangle([L(rx0 + 12), L(15), L(rx0 + 12 + (pw - 24) * 0.55), L(21)], L(3), fill=p["pgline"])
        d.text((L(rx0 + 12), L(42)), "Email", fill=p["pglab"], font=fb, anchor="lm")
        d.rounded_rectangle([L(rx0 + 8), L(52), L(rx1 - 8), L(78)], L(8), fill=p["hl"], outline=p["hlo"], width=int(round(L(SW))))
        d.text((L(rx0 + 16), L(65)), "you@example.com", fill=p["hltx"], font=fr, anchor="lm")
        d.rounded_rectangle([L(rx0 + 12), L(92), L(rx0 + 12 + (pw - 24) * 0.7), L(98)], L(3), fill=p["pgline"])
        imgs[k_] = ImageTk.PhotoImage(im.resize((Wp, Hp), Image.LANCZOS), master=win); return imgs[k_]
    # ---- live widgets: email box (Entry on a rounded image), placeholder, check
    ev = tk.StringVar()
    e_ = tk.Entry(cv, textvariable=ev, font=F(15, False), relief="flat", bd=0, highlightthickness=0)
    ph = tk.Label(e_, text="your Spotify email", font=F(15, False), cursor="xterm", bd=0)
    ck = tk.Label(cv, text="", bd=0)                      # text kept for tests; shows the drawn check image
    def ph_upd(*_):
        if ev.get(): ph.place_forget()
        else: ph.place(x=0, rely=0.5, anchor="w")
    ph.bind("<Button-1>", lambda e: (e_.focus_set(), e_.icursor("end")))
    e_.bind("<FocusIn>", lambda e: (st.update(focus=True), draw())); e_.bind("<FocusOut>", lambda e: (st.update(focus=False), draw()))
    done = tk.Frame(win)
    class Btn:                                          # pill button drawn on the canvas; Tk-button-like config/state for callers
        def __init__(s, key): s.key = key
        def __getitem__(s, o): return st["b3"] if o == "state" else st["b3t"]
        def config(s, state=None, text=None, **_):
            if state: st["b3"] = state
            if text: st["b3t"] = text
            draw()
        configure = config
    class Note:
        def __getitem__(s, o): return st["note"][0]
        def config(s, text=None, fg=None, **_): st["note"] = (text if text is not None else st["note"][0], "err" if fg else st["note"][1]); draw()
        configure = config
    b3, note = Btn("b3"), Note()
    def valid(): return bool(EMAIL_RE.match(ev.get().strip()))
    def text(x, y, s_, sz, key, bold=True, anchor="w", tags=()):
        return cv.create_text(x * S, y * S, text=s_, fill=P()[key], font=F(sz, bold), anchor=anchor, tags=tags)
    def pill(x, y, w, h, label, kind, tag, enabled=True):
        p = P(); hv = st["hov"] == tag and enabled
        if kind == "g": fill, fg = (p["gact"] if hv else p["g"]) if enabled else p["gdis"], "gtx" if enabled else "gdtx"
        else: fill, fg = p["b2a"] if hv else p["b2"], "b2tx"
        cv.create_image(x * S, y * S, anchor="nw", image=rr_img(w, h, h / 2, fill), tags=(tag,))
        text(x + w / 2, y + h / 2, label, 15, fg, True, "center", (tag,))
    def draw():
        p = P()
        for i in cv.find_all():
            if "win" not in cv.gettags(i): cv.delete(i)
        cv.configure(bg=p["bg"]); win.configure(bg=p["bg"])
        e_.configure(bg=p["ent"], fg=p["enttx"], insertbackground=p["enttx"], disabledbackground=p["ent"]); ph.configure(bg=p["ent"], fg=p["dis"])
        ok_ = valid(); ck.configure(bg=p["card"], image=check_img(p["g"], p["gtx"]) if ok_ else "", text="\u2714" if ok_ else "")
        st["b3"] = "normal" if (on and ok_ and not st["sent"] and st["b3t"] == "Send request") else "disabled"
        text(M + 8, 38, "Not invited yet", 26, "tx", tags=("hdr",)); text(M + 8, 70, "Ask for access in 3 easy steps.", 15, "mu", False, tags=("hdr",))
        if st.get("donev"):                            # Done: same canvas, same header, same window size
            for i in cv.find_withtag("win"): cv.itemconfigure(i, state="hidden")
            if not cv.find_withtag("dwin"): cv.create_window((M + 8) * S, HDR * S, anchor="nw", window=done, tags=("dwin",))
            return
        titles = ("Open your Spotify page", "Find your email and copy it", "Paste or type your Spotify email")
        h3 = H3 if st["note"][0] else H3 - 24              # no note line: card 3 ends 18 px under the button
        hh = Y3 + h3 + M
        if int(cv.cget("height")) != even_px(hh, S): cv.configure(height=even_px(hh, S))
        G["lay"]["H"] = (H1, H2, h3)
        for i, (y0, h) in enumerate(zip((Y1, Y2, Y3), (H1, H2, h3))):
            cv.create_image(M * S, y0 * S, anchor="nw", image=rr_img(W - 2 * M, h, 12, p["card"]))
            cv.create_image(BX * S, (y0 + TY) * S, image=badge_img(i + 1, p["g"], p["gtx"]), tags=("badge",))
            text(CX, y0 + TY, titles[i], 17, "tx", tags=("title",))
        pill(CX, Y1 + 52, 200, 44, "Open Spotify page", "b2", "b1")
        cv.create_image(CX * S, (Y2 + 52) * S, anchor="nw", image=illustration(), tags=("illu",))
        text(CX, Y2 + 52 + IH + 16, "Click \u201cEdit personal info\u201d (the row with the pencil).", 14, "mu", False)
        text(CX, Y2 + 52 + IH + 36, "Then select your Email and press Ctrl + C.", 14, "mu", False)
        by = Y3 + 52
        cv.create_image(CX * S, by * S, anchor="nw", image=rr_img(BOXW, BOXH, 8, p["ent"], p["g"] if st["focus"] else p["b2"], 1.5), tags=("box",))
        if not cv.find_withtag("win"):                  # embedded widgets are created once and kept on top
            cv.create_window((CX + 14) * S, (by + BOXH / 2) * S, anchor="w", window=e_, width=int((BOXW - 28) * S), height=int(26 * S), tags=("win",))
            cv.create_window((CX + BOXW + 14) * S, (by + BOXH / 2) * S, anchor="w", window=ck, tags=("win",))
        cv.tag_raise("win")
        pill(CX, by + BOXH + 14, 200, 44, st["b3t"], "g", "b3", st["b3"] == "normal")
        if st["note"][0]: text(CX, by + BOXH + 14 + 44 + 16, st["note"][0], 13, st["note"][1], False)
    def hit(e):
        it = cv.find_overlapping(e.x, e.y, e.x, e.y)
        for i in reversed(it):
            for t in cv.gettags(i):
                if t in ("b1", "b3"): return t
    def motion(e):
        h = hit(e)
        if h != st["hov"]:
            st["hov"] = h; cv.config(cursor="hand2" if h == "b1" or (h == "b3" and st["b3"] == "normal") else ""); draw()
    def click(e):
        h = hit(e)
        if h == "b1": wb.open(ACCOUNT_URL)
        elif h == "b3": send()
    cv.bind("<Motion>", motion); cv.bind("<ButtonRelease-1>", click); cv.bind("<Leave>", lambda e: motion(e) if False else (st.update(hov=None), draw()))
    def refresh(*_): ph_upd(); draw()
    ev.trace_add("write", refresh)
    def retheme(): imgs.clear(); set_titlebar(win, not th["light"]); draw(); show_done() if (st["sent"] or st.get("donev")) else None
    uiq = []
    def poll_clip():                                   # fills the box as soon as an email is copied; also follows the theme
        while uiq:
            uiq.pop(0)()
            if st["allowed"]: return
        try:
            c = win.clipboard_get().strip()
            if c != st["clip"]:
                st["clip"] = c
                if EMAIL_RE.match(c) and not st["sent"]: ev.set(c)
        except Exception: pass
        st["tick"] = st.get("tick", 0) + 1
        if st["tick"] % 8 == 0:                        # ~2 s: Windows light/dark switch while open
            lt = windows_light()
            if lt != th["light"]: th["light"] = lt; retheme()
        try: win.after(250, poll_clip)
        except Exception: pass
    def show_done():
        p = P(); st["donev"] = True; done.configure(bg=p["bg"])
        for w_ in done.winfo_children(): w_.destroy()
        for t_, sz, key, pady in (("\u2714  Done!", 30, "g", (14, 0)), ("You'll get access soon.", 20, "tx", (8, 6)),
                                  ("Keep this window open or reopen the app later.\nIt continues by itself when it works.", 15, "mu", (0, 30))):
            tk.Label(done, text=t_, font=F(sz, sz != 15), bg=p["bg"], fg=p[key], justify="left").pack(anchor="w", pady=tuple(int(v * S) for v in pady))
        draw()
    def send():
        if not (on and valid()) or st["sent"] or st["b3t"] != "Send request": return
        b3.config(text="Sending\u2026"); em = ev.get().strip()
        def go():
            r = send_access_request(cfg, em, name)
            def fin():
                st["b3t"] = "Send request"
                if r in ("sent", "wait"): st["sent"] = True; show_done()     # 'wait': asked recently - same friendly end
                else: note.config(text="Couldn't send, try again", fg="err")
                win._res = r
            uiq.append(fin)                            # Tk is only touched on the UI thread
        threading.Thread(target=go, daemon=True).start()
    def recheck():
        def go():
            try: r = access_status(Spotify(load_config()))
            except Exception: r = None
            if r == "ok": uiq.append(allowed)
        threading.Thread(target=go, daemon=True).start()
        st["job"] = win.after(recheck_ms, recheck)
    def allowed():
        if st["allowed"]: return
        st["allowed"] = True; u = load_user_settings(); u.pop("access_pending", None); save_user(u)
        try: win.destroy()
        except Exception: pass
        if on_allowed: on_allowed()
    ph_upd(); draw()
    if load_user_settings().get("access_pending") and time.time() - float(load_user_settings().get("access_last") or 0) < ACCESS_GAP:
        st["sent"] = True; show_done()
    poll_clip(); st["job"] = win.after(recheck_ms, recheck)
    reveal(win, over=parent) if parent is not None else reveal(win)
    set_titlebar(win, not th["light"])
    if not st["sent"]:
        try: win.focus_force(); e_.focus_set()                  # ready to type / Ctrl+V straight away
        except Exception: pass
    win._acc = {"ev": ev, "send": send, "b3": b3, "ck": ck, "st": st, "note": note, "done": done, "recheck": recheck, "allowed": allowed,
                "th": th, "retheme": retheme, "show_done": show_done, "P": P, "entry": e_, "ph": ph, "cv": cv, "G": G, "draw": draw}
    if own:
        win.mainloop() if not test_env("AOE4SPOTIFY_TEST_NOLOOP") else None
    return win

def ImageColor_rgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

def login_flow(cfg):
    """No-arg start (installer Finish page): log in if needed, then show the result window."""
    if os.environ.get("AOE4SPOTIFY_GTG_DEMO"):    # testing/screenshots only: show the window with sample data
        good_to_go({"ok": True, "name": "Capstar", "steam": True, "spotify_app": True}); return
    sp = Spotify(cfg)
    while True:
        if not sp.tok:
            try: sp.login()
            except BaseException as e: log("Login failed: %r" % e)
        if access_status(sp) == "blocked":
            ok_ = []
            access_dialog(None, on_allowed=lambda: ok_.append(1))
            if not ok_: return
        st = setup_status(sp)
        again = []
        good_to_go(st, on_retry=lambda: again.append(1), fix=lambda: with_steam_closed(set_launch_option))
        if not again: return

def remove_old_startup_shortcut():
    lnk = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "AoE4 Spotify.lnk")
    if os.path.exists(lnk): os.remove(lnk); log("Removed old Startup shortcut")

# ---------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if args[:1] == ["--set-launch-option"]:
        with_steam_closed(set_launch_option); music_sync(load_config().get("enabled", True)); return   # no-op close if Setup already closed Steam
    if args[:1] == ["--remove-launch-option"]: remove_launch_option(); music_sync(False); return
    if args[:1] == ["--fade-selftest"]:                # diagnostics: is the local fader usable? (reads only)
        sess = SpotifySession.find(); msg = "local fader: " + ("Spotify session found, volume %.2f" % sess.get() if sess else "not available")
        try:
            import tkinter as _tk; from tkinterdnd2 import TkinterDnD; _r = _tk.Tk(); _r.withdraw(); TkinterDnD._require(_r); _r.destroy(); msg += "; drag-in: ok"
        except Exception as ex: msg += "; drag-in: %r" % ex
        log(msg)
        try: open(os.path.join(os.environ.get("TEMP", "."), "aoe4_fade_selftest.txt"), "w").write(msg)
        except Exception: pass
        return
    if args[:1] == ["--panel"]: panel(); return        # (--panel --updated: just upgraded, shows "Updated to x.y")
    cfg = load_config()
    local_guard_restore()
    if args[:1] == ["--dry-run"]:
        t = Tracker(cfg, lambda k, civ=None: log("   [dry-run] would play %s%s: %s" % (k, (" (%s intro for %s: %s)" % (k, civ, pick_boss_track(cfg, civ, k))) if civ and boss_age(cfg, k) else "", cfg["playlists"].get(k))))
        crcs = args[2:]
        for line in open(args[1], encoding="utf-8", errors="replace"):
            if RE_BEGIN.search(line) and crcs:
                t.crc_dir = None; t.feed(line); t.begin_t = 0
                t._crc = crcs.pop(0); continue
            if RE_START.search(line) and getattr(t, "_crc", None):
                t.my_id = slot_to_id(t._crc).get(t.my_slot)
                log("Identified you as player id %s (slot %s, from %s)" % (t.my_id, t.my_slot, os.path.basename(t._crc)))
            t.feed(line)
        return
    remove_old_startup_shortcut()
    sp = Spotify(cfg)
    if not args:
        # Started by hand / installer Finish page: log in to Spotify, show "You're good to go", exit.
        login_flow(cfg); return
    # Started by Steam with the game command (%command%) as args: start the game first.
    import subprocess
    game_dir = os.path.dirname(args[0]) if os.path.isfile(args[0]) else None
    music_sync(cfg.get("enabled", True))           # game reads its music volume at launch
    subprocess.Popen(args, env=child_env(), cwd=game_dir)
    log("Started game: %s" % " ".join(args))
    if not cfg.get("enabled", True): log("Disabled in the app - game started, doing nothing else"); return
    if not single_instance(): log("Another switcher is already running - exiting"); return
    if not sp.tok: sp.login()
    t0 = time.time()
    while not aoe_running():                    # wait for RelicCardinal.exe (max 5 min)
        if time.time() - t0 > 300: log("AoE4 did not start within 5 minutes - exiting"); return
        time.sleep(3)
    log("AoE4 is running")
    threading.Thread(target=sp.ensure_device, daemon=True).start()   # start Spotify now if closed
    def play(k, civ=None):
        uri = cfg["playlists"].get(k, "")
        if not uri.startswith("spotify:") or "PASTE" in uri: log("No playlist set for %s" % k); return
        fade = float(cfg.get("fade_seconds", 2))
        cur = load_config()                                                   # editor changes apply right away
        track = choose_intro(cur, k, civ)
        if track:
            log("%s intro for %s: %s" % (k.capitalize(), civ, track))
            threading.Thread(target=sp.boss_then, args=(track, uri, fade), daemon=True).start()
        else:
            threading.Thread(target=sp.switch, args=(uri, fade), daemon=True).start()
    path = os.path.expandvars(cfg.get("log_path") or DEFAULT_LOG)
    t = Tracker(cfg, play)
    t.crc_dir = os.path.join(os.path.dirname(path), "LogFiles")
    tail(path, t, stop=lambda: not aoe_running())   # returns ~10s after the game closes
    log("AoE4 closed - exiting")
    time.sleep(2); music_sync(load_config().get("enabled", True))   # game rewrote its settings on exit: re-mute / restore
    time.sleep(3)                                     # let a running fade finish

# ---------------------------------------------------------------- control panel (--panel)
# A small settings window. Settings are saved to %APPDATA%/AoE4Spotify/config.json and
# overlay the install config (which is never edited).
RELEASES_URL = "https://github.com/Capstar1/aoe4-spotify/releases"
NAMES_CACHE = os.path.join(DATA, "playlist_names.json")
COVERS = os.path.join(DATA, "covers")              # playlist cover thumbnails: <playlist id>_<snapshot>.jpg

def http_get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r: return r.read()

def pick_image(images, need):
    """Smallest Spotify image that is at least `need` px wide (else the largest one)."""
    imgs = [i for i in (images or []) if isinstance(i, dict) and i.get("url")]
    if not imgs: return None
    sized = sorted(imgs, key=lambda i: i.get("width") or 10 ** 6)
    for i in sized:
        if (i.get("width") or 10 ** 6) >= need: return i["url"]
    return sized[-1]["url"]

def cover_file(pid):
    """Cached cover for a playlist (newest snapshot), or None."""
    try: fs = [f for f in os.listdir(COVERS) if f.startswith(pid + "_")]
    except OSError: return None
    if not fs: return None
    return max((os.path.join(COVERS, f) for f in fs), key=os.path.getmtime)

def update_cover(sp, pid, need=96):
    """GET name + images + snapshot; download the cover if this snapshot isn't cached. Returns (name, path)."""
    c, r = sp._api("GET", "/playlists/%s?fields=name,images,snapshot_id" % pid)
    if c != 200 or not isinstance(r, dict): return None, cover_file(pid)
    snap = re.sub(r"[^A-Za-z0-9]", "", str(r.get("snapshot_id") or "0"))[:16] or "0"
    path = os.path.join(COVERS, "%s_%s.jpg" % (pid, snap))
    url = pick_image(r.get("images"), need)
    if url and not os.path.exists(path):
        try:
            data = http_get(url); os.makedirs(COVERS, exist_ok=True)
            open(path + ".part", "wb").write(data); os.replace(path + ".part", path)
            for f in os.listdir(COVERS):                          # drop older snapshots of this playlist
                if f.startswith(pid + "_") and os.path.join(COVERS, f) != path:
                    try: os.remove(os.path.join(COVERS, f))
                    except OSError: pass
        except Exception as e: log("Cover download failed: %r" % e)
    return r.get("name"), (path if os.path.exists(path) else cover_file(pid))

def open_playlist(pid):
    """Open a playlist in the Spotify app; fall back to the web player."""
    try: os.startfile("spotify:playlist:" + pid); return "app"
    except Exception:
        webbrowser.open("https://open.spotify.com/playlist/" + pid); return "web"
AGES = [("dark", "Dark"), ("feudal", "Feudal"), ("castle", "Castle"), ("imperial", "Imperial")]
RE_PLAYLIST = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z]+/)?playlist/|spotify:playlist:)([A-Za-z0-9]{22})")

# ---------------------------------------------------------------- Imperial Age Intro editor
# Which "For ..." theme each civ can get on reaching Imperial Age. Changes are saved as "boss_pools"
# in the user settings overlay and used from the next match. An empty civ = no intro (its playlist plays).
SONGS = [  # key, song, character (portrait), Spotify track, ring colour
    ("light", "For Light", "Ophilia", "spotify:track:5sEHThQpQWTZZVIbmFIx4k", "#e8d9a0"),
    ("truth", "For Truth", "Cyrus", "spotify:track:0iBkJlkxLIZvw64YMJEhpY", "#6fa8dc"),
    ("treasure", "For Treasure", "Tressa", "spotify:track:4RmbTKOJGdfKVEnwTUAobp", "#e0b040"),
    ("redemption", "For Redemption", "Olberic", "spotify:track:6bZVraEtKL5lQ7TtUrhX8K", "#b0b0b0"),
    ("revenge", "For Revenge", "Primrose", "spotify:track:6hdfIg76lNerf0bLt7ppAo", "#c0506a"),
    ("succor", "For Succor", "Alfyn", "spotify:track:0JhmuCu4N8XT9nRVFsngS9", "#7cc47c"),
    ("freedom", "For Freedom", "Therion", "spotify:track:3LxsqAQ0rXaLEHonDax63B", "#d9a066"),
    ("master", "For Master", "H'aanit", "spotify:track:5X8te47Qx2kIeAqAicMrgC", "#8fbf6a"),
]
BUILTIN_SONGS = list(SONGS)
SONG_BY_URI = {s[3]: s for s in SONGS}
def custom_key(uri): return "c_" + uri.split(":")[-1]
def load_custom_songs(u):
    """Your own intro songs (user settings "custom_songs": [{uri, name, artist}]) appended to SONGS."""
    SONGS[:] = BUILTIN_SONGS + [(custom_key(c["uri"]), c.get("name") or "Song", c.get("artist") or "", c["uri"], "#1DB954")
                                for c in (u.get("custom_songs") or []) if isinstance(c, dict) and str(c.get("uri", "")).startswith("spotify:track:")]
    SONG_BY_URI.clear(); SONG_BY_URI.update({s[3]: s for s in SONGS})
def song_sorted(lst):
    """One canonical chip order everywhere: tray order (built-ins, then your songs in add order); unknowns last."""
    idx = {x[3]: i for i, x in enumerate(SONGS)}; lst = list(dict.fromkeys(lst or []))
    return sorted(lst, key=lambda u: (idx.get(u, len(idx)), lst.index(u)))
def normalize_pools(u):
    """Sort every stored intro pool canonically (returns True if anything changed)."""
    ip = u.get("intro_pools"); ch = False
    if isinstance(ip, dict):
        for age in ip.values():
            if isinstance(age, dict):
                for civ, lst in age.items():
                    if isinstance(lst, list) and song_sorted(lst) != lst: age[civ] = song_sorted(lst); ch = True
    return ch
def track_cover(uri): return os.path.join(COVERS, "track_%s.jpg" % uri.split(":")[-1])
def fetch_track(sp, uri, need=96):
    """(name, artist) of a Spotify track; caches its album cover for the chip. None if not found."""
    c, r = sp._api("GET", "/tracks/" + uri.split(":")[-1])
    if c != 200 or not isinstance(r, dict) or not r.get("name"): return None
    url = pick_image((r.get("album") or {}).get("images"), need)
    if url:
        try:
            os.makedirs(COVERS, exist_ok=True); data = http_get(url); p = track_cover(uri)
            open(p + ".part", "wb").write(data); os.replace(p + ".part", p)
        except Exception as e: log("Track cover download failed: %r" % e)
    return r["name"], ", ".join(a_.get("name", "") for a_ in (r.get("artists") or [])[:2])
def store_track(r, need=96):
    """(uri, name, artist) from a Spotify track object; caches its album cover for the chip."""
    uri = r.get("uri") or ("spotify:track:" + r.get("id", ""))
    url = pick_image((r.get("album") or {}).get("images"), need)
    if url and not os.path.exists(track_cover(uri)):
        try:
            os.makedirs(COVERS, exist_ok=True); data = http_get(url); p = track_cover(uri)
            open(p + ".part", "wb").write(data); os.replace(p + ".part", p)
        except Exception as e: log("Track cover download failed: %r" % e)
    return uri, r.get("name") or "Song", ", ".join(a_.get("name", "") for a_ in (r.get("artists") or [])[:2])
def parse_tracks(text):
    """Every Spotify track in a text (links, URIs, one per line as the Spotify app drags them), in order."""
    ids = re.findall(r"(?:spotify:track:|open\.spotify\.com/(?:intl-[a-z]+/)?track/)([A-Za-z0-9]{22})", text or "")
    return ["spotify:track:" + i for i in dict.fromkeys(ids)]
def fetch_tracks(sp, uris):
    """Look up several tracks in one call -> [(uri, name, artist)]."""
    out = []
    for k in range(0, len(uris), 50):
        c, r = sp._api("GET", "/tracks?ids=" + ",".join(u.split(":")[-1] for u in uris[k:k + 50]))
        if c == 200 and isinstance(r, dict):
            out += [store_track(t) for t in (r.get("tracks") or []) if isinstance(t, dict) and t.get("name")]
    return out
def search_tracks(sp, q, limit=8):
    from urllib.parse import quote
    c, r = sp._api("GET", "/search?type=track&limit=%d&q=%s" % (limit, quote(q)))
    if c != 200 or not isinstance(r, dict): return None
    return [t for t in ((r.get("tracks") or {}).get("items") or []) if isinstance(t, dict) and t.get("uri")]
def now_playing(sp):
    c, r = sp._api("GET", "/me/player/currently-playing")
    if c == 200 and isinstance(r, dict) and isinstance(r.get("item"), dict) and str(r["item"].get("uri", "")).startswith("spotify:track:"):
        return r["item"]
    return None
def parse_track(text):
    m = re.search(r"(?:spotify:track:|open\.spotify\.com/(?:intl-[a-z]+/)?track/)([A-Za-z0-9]{22})", text or "")
    return "spotify:track:" + m.group(1) if m else None
CIV_LIST = [("french", "French"), ("hre", "HRE"), ("templar", "Templar"), ("french_ha_01", "Jeanne d'Arc"),
            ("abbasid", "Abbasid"), ("abbasid_ha_01", "Ayyubids"), ("byzantine", "Byzantines"), ("malian", "Malians"),
            ("sultanate", "Delhi"), ("ottoman", "Ottomans"), ("english", "English"), ("hre_ha_01", "Dragon"),
            ("lancaster", "Lancaster"), ("mongol", "Mongols"), ("mongol_ha_gol", "Golden Horde"), ("rus", "Rus"),
            ("chinese_ha_01", "Zhu Xi"), ("chinese", "Chinese"), ("japanese", "Japanese"), ("jin_dynasty", "Jin"),
            ("japanese_ha_sen", "Sengoku"), ("sultanate_ha_tug", "Tughlaq"), ("byzantine_ha_mac", "Macedonian")]

class Art:
    """Anti-aliased portrait chips and flag icons (Pillow, cached PhotoImages)."""
    def __init__(self, master, S):
        self.m, self.S, self.cache = master, S, {}
    def chip(self, key, r, dim=False):
        k = ("chip", key, r, dim)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageTk
        song = next((s for s in SONGS if s[0] == key), ("plus", "", "", "", "#3a3a3a"))
        D = chip_px(r, self.S); Q = 4; big = D * Q
        im = Image.new("RGBA", (big, big), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.ellipse([0, 0, big - 1, big - 1], fill=song[4])          # PIL boxes are inclusive: 0..big-1 is centred
        inner = big - 2 * int(round(2 * self.S * Q))                     # even margin: portrait exactly centred
        src = track_cover(song[3]) if key.startswith("c_") else os.path.join(ASSETS, "assets", "portraits", key + ".jpg")
        try: p = Image.open(src).convert("RGB").resize((inner, inner), Image.LANCZOS)
        except Exception:
            p = Image.new("RGB", (inner, inner), "#262626")
            if key == "plus" or key.startswith("c_"):                      # '+' chip / custom song without cover
                dd = ImageDraw.Draw(p); w_ = max(2, inner // 14); c_ = inner / 2; a_ = inner * 0.22
                if key == "plus":
                    dd.line([(c_ - a_, c_), (c_ + a_, c_)], fill="#1DB954", width=w_); dd.line([(c_, c_ - a_), (c_, c_ + a_)], fill="#1DB954", width=w_)
                else: dd.ellipse([c_ - a_, c_ - a_, c_ + a_, c_ + a_], outline="#1DB954", width=w_)
        if dim: p = Image.blend(p, Image.new("RGB", p.size, "#121212"), 0.6)
        m = Image.new("L", (inner, inner), 0); ImageDraw.Draw(m).ellipse([0, 0, inner - 1, inner - 1], fill=255)
        off = (big - inner) // 2; im.paste(p, (off, off), m)
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def plus(self, r, hover=False):
        """The YOURS '+' button: same image size/parity as a song chip (so it centres exactly like one), one
        thin ring and a '+' made of two centred strokes (no font glyph). Hover = slightly brighter + faint fill."""
        k = ("plus", r, hover)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageTk
        D = chip_px(r, self.S); Q = 4; B = D * Q; d_ = None
        im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
        g = (64, 222, 120) if hover else (29, 185, 84)
        def box(rad):
            R = int(round(rad)); C_ = B // 2; return [C_ - R, C_ - R, C_ + R - 1, C_ + R - 1]
        ring = (r + 0.5) * self.S * Q; lw = max(Q, int(round(1.6 * self.S * Q)))
        if hover: d_.ellipse(box(ring), fill=g + (38,))
        d_.ellipse(box(ring), outline=g + (255,), width=lw)
        arm = int(round(r * 0.42 * self.S * Q)); sw = max(Q, int(round(2.0 * self.S * Q))); sw += sw % 2
        C_ = B // 2
        d_.rectangle([C_ - arm, C_ - sw // 2, C_ + arm - 1, C_ + sw // 2 - 1], fill=g + (255,))
        d_.rectangle([C_ - sw // 2, C_ - arm, C_ + sw // 2 - 1, C_ + arm - 1], fill=g + (255,))
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def chevron(self, size, color, back=False, fill=None, w=7.0, h=14.0, lw=2.0):
        """Supersampled chevron (optionally on a round button of logical diameter `size`). The two arms are
        placed so their visual mass (centroid = midpoint between tip and arm ends) sits on the exact centre."""
        k = ("chev", size, color, back, fill, w, h, lw)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageTk
        D = even_px(size, self.S); Q = 4; B = D * Q
        im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im); c = (B - 1) / 2; k_ = self.S * Q
        if fill: d_.ellipse([0, 0, B - 1, B - 1], fill=fill)
        disc_im = im; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
        sgn = -1 if back else 1
        tip = (c + sgn * w / 2 * k_, c); a1 = (c - sgn * w / 2 * k_, c - h / 2 * k_); a2 = (c - sgn * w / 2 * k_, c + h / 2 * k_)
        L = max(Q, int(round(lw * k_)))
        d_.line([a1, tip, a2], fill=color, width=L, joint="curve")
        for p_ in (a1, a2, tip):                                       # round caps
            d_.ellipse([p_[0] - L / 2, p_[1] - L / 2, p_[0] + L / 2, p_[1] + L / 2], fill=color)
        im = Image.alpha_composite(disc_im, ink_centre(im))             # optical centre = ink centroid
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def disc(self, diam, fill, text=None, fg=None, tsize=None, cross=None, outline=None, ow=0.0):
        """Round badge as an even-sized supersampled image (exact centre at any DPI, unlike canvas ovals),
        with an optional glyph whose INK (not font metrics) is centred, or a cross drawn as two strokes."""
        k = ("disc", diam, fill, text, fg, tsize, cross, outline, ow)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        D = even_px(diam, self.S); Q = 4; B = D * Q; k_ = self.S * Q
        im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
        o = int(round(ow * k_)) if outline else 0
        d_.ellipse([0, 0, B - 1, B - 1], fill=outline or fill)
        if o: d_.ellipse([o, o, B - 1 - o, B - 1 - o], fill=fill)
        c = (B - 1) / 2
        if text:
            try: f = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "segoeuib.ttf"), int(round(tsize * k_)))
            except Exception: f = ImageFont.load_default()
            tl = Image.new("RGBA", (B, B), (0, 0, 0, 0)); ImageDraw.Draw(tl).text((c, c), text, font=f, fill=fg, anchor="mm")
            im = Image.alpha_composite(im, ink_centre(tl)); d_ = ImageDraw.Draw(im)      # centre the glyph INK
        if cross:
            base_im = im; im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
            a_ = cross * k_; L = max(Q, int(round(1.6 * k_)))
            for p_, q_ in (((c - a_, c - a_), (c + a_, c + a_)), ((c - a_, c + a_), (c + a_, c - a_))):
                d_.line([p_, q_], fill=fg, width=L)
                for e_ in (p_, q_): d_.ellipse([e_[0] - L / 2, e_[1] - L / 2, e_[0] + L / 2, e_[1] + L / 2], fill=fg)
            im = Image.alpha_composite(base_im, ink_centre(im))
        ph = ImageTk.PhotoImage(im.resize((D, D), Image.LANCZOS), master=self.m); self.cache[k] = ph; return ph
    def flag(self, civ, h=16):
        k = ("flag", civ, h)
        if k in self.cache: return self.cache[k]
        from PIL import Image, ImageTk, ImageDraw
        H = int(round(h * self.S)); W = int(round(H * 60 / 32))
        p = os.path.join(ASSETS, "assets", "flags", civ + ".png")
        if not os.path.exists(p): p = os.path.join(ASSETS, "assets", "flags", "_unknown.png")
        try: im = Image.open(p).convert("RGBA").resize((W, H), Image.LANCZOS)
        except Exception:
            im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(im).rounded_rectangle([0, 0, W - 1, H - 1], 3, fill="#555555")
        ph = ImageTk.PhotoImage(im, master=self.m); self.cache[k] = ph; return ph

def default_pool(base_cfg, civ):
    bi = base_cfg.get("boss_intro") or {}
    return list((bi.get("pools") or {}).get(civ) or bi.get("default") or [])

def pool_editor(parent, user, save):
    """Tier-list style editor. user: the panel's settings dict (shared); save(): persist + refresh panel."""
    if not single_window("editor", "Age Intros"): return None
    import tkinter as tk
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", line="#2e2e2e", dis="#4a4a4a")
    win = tk.Toplevel(parent); dark_window(win, C["bg"]); win.title("Age Intros"); win.resizable(False, False)
    win.bind("<Destroy>", lambda e: release_window("editor") if e.widget is win else None, add="+")
    S = win.winfo_fpixels("1i") / 96.0
    W, H, LT, RH, GAP = 600, 720, 196, 40, 4
    CR = 14                                            # civ-row chip radius
    BOT = H - 12; STEP = RH + GAP
    cv = tk.Canvas(win, width=int(W * S), height=int(H * S), bg=C["bg"], highlightthickness=0); cv.pack()
    art = Art(win, S)
    from PIL import Image, ImageDraw, ImageTk
    imgs = {}
    def rr_img(w, h, r, fill, outline=None, width=1.5):
        k = (w, h, r, fill, outline, width)
        if k not in imgs:
            Q = 4; Wp, Hp = max(1, int(round(w * S))), max(1, int(round(h * S)))
            im = Image.new("RGBA", (Wp * Q, Hp * Q), (0, 0, 0, 0))
            ImageDraw.Draw(im).rounded_rectangle([0, 0, Wp * Q - 1, Hp * Q - 1], r * S * Q, fill=fill, outline=outline,
                                                 width=int(width * S * Q) if outline else 0)
            imgs[k] = ImageTk.PhotoImage(im.resize((Wp, Hp), Image.LANCZOS), master=win)
        return imgs[k]
    def rr(x0, y0, x1, y1, r, fill, outline=None, width=1.5):
        cv.create_image(x0 * S, y0 * S, anchor="nw", image=rr_img(x1 - x0, y1 - y0, r, fill, outline, width))
    def text(x, y, s, sz, c=None, b=False, anchor="w"):
        cv.create_text(x * S, y * S, text=s, fill=c or C["tx"], anchor=anchor, font=("Segoe UI", -int(sz * S), "bold" if b else "normal"))
    def undo_glyph(cx, cy, c):
        k = ("undo", c)
        if k not in imgs:
            Q = 4; Z = int(18 * S); im = Image.new("RGBA", (Z * Q, Z * Q), (0, 0, 0, 0)); d = ImageDraw.Draw(im); m = Z * Q
            lw = max(2, int(2 * S * Q)); d.arc([m*.2, m*.2, m*.86, m*.86], 200, 470, fill=c, width=lw)
            d.polygon([(m*.06, m*.4), (m*.38, m*.4), (m*.2, m*.64)], fill=c)
            imgs[k] = ImageTk.PhotoImage(im.resize((Z, Z), Image.LANCZOS), master=win)
        cv.create_image(cx * S, cy * S, image=imgs[k])
    base = load_config(user=False)
    _bi = base.get("boss_intro") or {}
    if migrate_intros_v2(user, {**(_bi.get("pools") or {}), "__default__": _bi.get("default") or []}): save()   # v2 per-age lists
    load_custom_songs(user)
    if normalize_pools(user): save()                                   # same songs -> same chip order
    ed = {"age": "imperial", "page": "overview"}            # page: "overview" or the age being edited
    def ages_on(): return {a_: build_intros(base, user)[a_]["enabled"] for a_ in INTRO_AGES}
    def pools(age=None):
        age = age or ed["age"]; bp = (user.get("intro_pools") or {}).get(age) or {}
        if age == "imperial": return {c: song_sorted(bp[c] if c in bp else default_pool(base, c)) for c, _ in CIV_LIST}
        return {c: song_sorted(bp.get(c) or []) for c, _ in CIV_LIST}          # other ages: blank unless you add songs
    def row_default(civ): return default_pool(base, civ) if ed["age"] == "imperial" else []
    def age_custom(age=None):                          # anything to reset on this age?
        age = age or ed["age"]; return bool((user.get("intro_pools") or {}).get(age))
    st = {"sc": 0, "hov": None, "drag": None, "ghost": None, "drop": None, "press": None, "msg": None}
    max_sc = lambda: max(0, len(CIV_LIST) * STEP - GAP - (BOT - LT))
    def row_y(i): return LT + i * STEP - st["sc"]
    NB = len(BUILTIN_SONGS)
    def _ysp():
        m = len(SONGS) - NB; return min(50.0, 100.0 / max(1, m))
    def tray_xy(i):                                    # OCTOPATH group | divider | YOURS group (+ the '+' chip)
        if i < NB: return 53 + i * 48, 137
        return 438 + tray_rad(NB) + 2 + (i - NB) * _ysp(), 137      # left edge of the first chip under the YOURS label
    def tray_rad(i): return 19 if i < NB else max(9.0, min(19.0, _ysp() * 0.45))
    def tray_r(): return 19
    def chip_xy(i, j): return 205 + j * 34, row_y(i) + RH / 2
    def _bp(p):
        if ed["age"] != "imperial": return {c: song_sorted(v) for c, v in p.items() if v}
        return {c: song_sorted(v) for c, v in p.items() if song_sorted(v) != song_sorted(default_pool(base, c))}
    def snap():                                         # everything the editor can change (all ages)
        return json.loads(json.dumps({k: user.get(k) for k in ("intro_pools", "intro_ages", "custom_songs", "intro_preset")}))
    hist = {"cur": snap(), "undo": [], "redo": []}     # Ctrl+Z / Ctrl+Y history for this editor session (all tabs)
    def _apply(sn):
        for k, v in sn.items():
            if v: user[k] = json.loads(json.dumps(v))
            else: user.pop(k, None)
        load_custom_songs(user); normalize_pools(user); save()
    def age_empty(age): return not any(pools(age).values())
    def record():
        for a_ in INTRO_AGES:                          # an age with no songs at all can't be on (same undo step)
            if age_empty(a_) and ages_on()[a_]:
                ia = dict(user.get("intro_ages") or {}); ia[a_] = False; user["intro_ages"] = ia
        sn = snap()
        if sn != hist["cur"]:
            hist["undo"].append(hist["cur"]); hist["redo"].clear(); hist["cur"] = sn
            del hist["undo"][:-500]
        _apply(sn)
    def commit(p):
        ip = dict(user.get("intro_pools") or {}); bp = _bp(p)
        if bp: ip[ed["age"]] = bp
        else: ip.pop(ed["age"], None)
        if ip: user["intro_pools"] = ip
        else: user.pop("intro_pools", None)
        record()
    def set_age_on(a_, on):
        if on and age_empty(a_): return                # greyed out until the age has a song
        ia = dict(user.get("intro_ages") or {}); ia[a_] = bool(on); user["intro_ages"] = ia; record()
    def add_custom(uri, name, artist): add_customs([(uri, name, artist)])
    def add_customs(items):                            # several songs = one undo step
        items = [t for t in items if t[0] not in SONG_BY_URI or t[0] in {c.get("uri") for c in (user.get("custom_songs") or [])}]
        if not items: return 0
        new = {t[0] for t in items}
        cs = [c for c in (user.get("custom_songs") or []) if c.get("uri") not in new]
        cs += [{"uri": u, "name": n, "artist": a} for u, n, a in items]; user["custom_songs"] = cs; record(); draw()
        return len(items)
    uiq = []                                        # worker threads hand UI work to the Tk thread
    ui = uiq.append
    def uipump():
        while uiq:
            try: uiq.pop(0)()
            except Exception as ex: log('UI task: %r' % ex)
        try: win.after(30, uipump)
        except Exception: pass
    win.after(30, uipump)
    # ---- drag songs in from the Spotify app (OLE text drop on the editor window)
    def drop_text(data):
        uris = [u for u in parse_tracks(data) if u not in SONG_BY_URI]
        if not parse_tracks(data): toast("Drop Spotify songs here"); return
        if not uris: toast("Already in YOURS"); return
        toast("Adding\u2026")
        def go():
            try:
                sp = Spotify(load_config()); got = fetch_tracks(sp, uris) if sp.tok else "login"
            except Exception as ex: log("Drop songs: %r" % ex); got = None
            def done():
                if got == "login": toast("Log in to Spotify first")
                elif not got: toast("Couldn't find those songs")
                else:
                    n = add_customs(got); toast("Added %d song%s" % (n, "" if n == 1 else "s"))
            try: ui(done)
            except Exception: pass
        threading.Thread(target=go, daemon=True).start()
    def drop_over(on):
        if bool(st.get("dropover")) != on: st["dropover"] = on; draw()
    try:
        from tkinterdnd2 import TkinterDnD, DND_TEXT
        TkinterDnD._require(win); cv.drop_target_register(DND_TEXT)
        cv.dnd_bind("<<DropEnter>>", lambda e: (drop_over(True), "copy")[1])
        cv.dnd_bind("<<DropPosition>>", lambda e: "copy")
        cv.dnd_bind("<<DropLeave>>", lambda e: (drop_over(False), "copy")[1])
        cv.dnd_bind("<<Drop>>", lambda e: (drop_over(False), drop_text(e.data), "copy")[2])
        st["dnd"] = True
    except Exception as ex: log("Drag-in from Spotify unavailable: %r" % ex); st["dnd"] = False
    win._drop = (drop_text, drop_over)                 # (tests)
    def remove_custom(uri):
        user["custom_songs"] = [c for c in (user.get("custom_songs") or []) if c.get("uri") != uri]
        ip = user.get("intro_pools") or {}
        for a_ in list(ip):
            for civ in list(ip[a_]):
                ip[a_][civ] = [u_ for u_ in ip[a_][civ] if u_ != uri]
                if not ip[a_][civ] and a_ != "imperial": ip[a_].pop(civ)   # Imperial: [] = emptied (not the default)
        record(); draw()
    def undo_redo(back):
        src, dst = (hist["undo"], hist["redo"]) if back else (hist["redo"], hist["undo"])
        if not src or st["drag"]: return "break"
        dst.append(hist["cur"]); hist["cur"] = src.pop(); _apply(hist["cur"]); st["msg"] = None; draw()
        return "break"
    def open_page(page):
        ed["page"] = page
        if page != "overview": ed["age"] = page
        st["sc"] = 0; st["hov"] = None; draw()
        try:                                           # re-evaluate hover/cursor for the new page right away
            px, py = cv.winfo_pointerx() - cv.winfo_rootx(), cv.winfo_pointery() - cv.winfo_rooty()
            h = hit(px / S, py / S) if 0 <= px < cv.winfo_width() and 0 <= py < cv.winfo_height() else None
        except Exception: h = None
        set_hover(h)
    CARD_Y = lambda k: 132 + k * 136
    # ---- presets (overview bar)
    def cur_preset():
        n = user.get("intro_preset") or DEFAULT_PRESET_NAME
        return next((p for p in user_presets(user) if p["name"] == n), None)
    def dirty():
        p = cur_preset(); return p is None or preset_key(user, p) != preset_key(user)
    def switch_preset(name):
        p = next((p for p in user_presets(user) if p["name"] == name), None)
        if not p: return
        apply_preset(user, p); st["menu"] = None; record(); fetch_missing_covers(); draw()
    def save_preset(name=None):                        # name=None: overwrite the current one
        ps = [p for p in (user.get("intro_presets") or []) if isinstance(p, dict)]
        if name is None:
            cur = cur_preset()
            if not cur or cur.get("builtin"): return
            name = cur["name"]; ps = [p for p in ps if p.get("name") != name]
        else: name = unique_preset_name(user, name)
        ps.append(preset_from_user(user, name)); user["intro_presets"] = ps; user["intro_preset"] = name
        hist["cur"] = snap(); _apply(hist["cur"]); st["menu"] = None; draw()
    def share():
        p = preset_from_user(user, (cur_preset() or {}).get("name") or user.get("intro_preset") or "Shared")
        code = encode_preset(p); win.clipboard_clear(); win.clipboard_append(code)
        try: win.update()
        except Exception: pass
        win._last_code = code; toast("Code copied")
    def toast(msg):
        st["toast"] = msg
        if st.get("toastjob"): win.after_cancel(st["toastjob"])
        def clr(): st["toast"] = None; st["toastjob"] = None; draw()
        st["toastjob"] = win.after(1800, clr); draw()
    def import_preset(p):
        p = dict(p); p["name"] = unique_preset_name(user, p["name"]); p.pop("builtin", None)
        user["intro_presets"] = [q for q in (user.get("intro_presets") or [])] + [p]
        apply_preset(user, p); record(); fetch_missing_covers(); draw(); toast("Imported")
        return p["name"]
    def fetch_missing_covers():                        # imported songs: covers arrive in the background
        miss = [c["uri"] for c in (user.get("custom_songs") or []) if not os.path.exists(track_cover(c["uri"]))]
        if not miss: return
        def go():
            try:
                sp = Spotify(load_config())
                if not sp.tok: return
                for u_ in miss: fetch_track(sp, u_)
            except Exception as ex: log("Covers: %r" % ex); return
            try: win.after(0, lambda: (art.cache.clear(), draw()))
            except Exception: pass
        threading.Thread(target=go, daemon=True).start()
    def name_dialog(title, init, cb):
        d = tk.Toplevel(win); dark_window(d, C["card"]); d.title(title); d.resizable(False, False); d.transient(win)
        tk.Label(d, text=title, bg=C["card"], fg=C["tx"], font=("Segoe UI", 11, "bold")).pack(padx=16, pady=(14, 6), anchor="w")
        e_ = tk.Entry(d, width=32, bg="#2a2a2a", fg=C["tx"], insertbackground=C["tx"], relief="flat", font=("Segoe UI", 10)); e_.pack(padx=16, ipady=5)
        e_.insert(0, init); e_.select_range(0, "end")
        def ok(*_):
            v = e_.get().strip()
            if v: d.destroy(); cb(v)
        tk.Button(d, text="Save", command=ok, bg=C["acc"], fg="#121212", relief="flat", font=("Segoe UI", 10, "bold"), padx=14).pack(padx=16, pady=(10, 14), anchor="e")
        e_.bind("<Return>", ok); d.bind("<Escape>", lambda e: d.destroy())
        reveal(d, over=win); e_.focus_set(); win._name = (d, e_, ok); return "break"
    def import_dialog():
        d = tk.Toplevel(win); dark_window(d, "#1e1e1e"); d.title("Import"); d.resizable(False, False); d.transient(win)
        DW, DH = 480, 360; dc = tk.Canvas(d, width=int(DW * S), height=int(DH * S), bg="#1e1e1e", highlightthickness=0); dc.pack()
        e_ = tk.Entry(d, bg="#141414", fg="#c8c8c8", insertbackground=C["tx"], relief="flat", font=("Segoe UI", 10),
                      highlightthickness=max(1, int(S)), highlightbackground="#3e3e3e", highlightcolor=C["acc"])
        res = {"p": None, "err": None, "hov": None}; dimg = []
        def drr(x0, y0, x1, y1, r, fill, outline=None, width=1.5):
            dc.create_image(x0 * S, y0 * S, anchor="nw", image=rr_img(x1 - x0, y1 - y0, r, fill, outline, width), tags="g")
        def dtext(x, y, s_, sz, c=None, b=False, anchor="w"):
            dc.create_text(x * S, y * S, text=s_, fill=c or C["tx"], anchor=anchor, font=("Segoe UI", -int(sz * S), "bold" if b else "normal"), tags="g")
        def ddraw():
            dc.delete("g"); dimg.clear()
            if not dc.find_withtag("entry"): dc.create_window(24 * S, 66 * S, anchor="nw", width=int(432 * S), height=int(40 * S), window=e_, tags="entry")
            dc.create_image(38 * S, 36 * S, image=art.disc(30, "#1e3c28", outline=C["acc"], ow=1.5), tags="g"); dc.create_image(38 * S, 36 * S, image=bar_icon("import", C["acc"]), tags="g")
            dtext(62, 36, "Import", 17, b=True); dtext(452, 34, "×", 20, C["tx"] if res["hov"] == "x" else C["mu"], anchor="center")
            drr(24, 126, 456, 290, 14, "#262626")
            p, err = res["p"], res["err"]
            if p:
                for j, u_ in enumerate(preset_songs(base, p)[:3]):
                    sg = SONG_BY_URI.get(u_) or next(((None, c_["name"]) for c_ in p["custom"] if c_["uri"] == u_), None)
                    key = sg[0] if sg and sg[0] else None
                    if key: dc.create_image((56 + j * 20) * S, 158 * S, image=art.chip(key, 15), tags="g")
                    else: dc.create_image((56 + j * 20) * S, 158 * S, image=art.plus(15), tags="g")
                dtext(130, 150, p["name"], 16, b=True); dtext(130, 171, "from code", 10, C["mu"])
                cnt = preset_counts(base, p); on = {a_: bool(p["ages"].get(a_, a_ == "imperial")) for a_ in INTRO_AGES}
                for k_, a_ in enumerate(INTRO_AGES):
                    x = 40 + k_ * 102
                    dc.create_image((x + 15) * S, 219 * S, image=art.disc(30, "#1e3c28" if on[a_] and cnt[a_] else "#2c2c2c",
                                    ("I", "II", "III", "IV")[k_], C["acc"] if on[a_] and cnt[a_] else C["mu"], 11), tags="g")
                    dtext(x + 38, 212, str(cnt[a_]), 14, b=True); dtext(x + 38, 228, "civs", 9, C["mu"])
                dc.create_image(55 * S, 263 * S, image=art.plus(13), tags="g")
                dtext(78, 256, str(len(p["custom"])), 14, b=True); dtext(78, 272, "custom", 9, C["mu"])
                dc.create_line(*[v * S for v in (382, 263, 387, 268, 396, 257)], fill=C["acc"], width=max(1, 2.2 * S), capstyle="round", joinstyle="round", tags="g")
                dtext(404, 263, "Valid", 11, C["acc"], True)
            elif err:
                dc.create_image(240 * S, 186 * S, image=art.disc(34, "#3c1e1e", "!", "#e5534b", 17), tags="g")
                dtext(240, 228, err, 12, "#e5534b", True, "center")
            else:
                dtext(240, 208, "Paste a code someone shared with you", 11, C["mu"], anchor="center")
            drr(24, 306, 190, 346, 20, "#383838" if res["hov"] == "cancel" else "#2a2a2a"); dtext(107, 326, "Cancel", 13, b=True, anchor="center")
            gc = (C["acc"] if res["hov"] != "ok" else "#3be477") if p else "#24412e"
            drr(202, 306, 456, 346, 20, gc); dtext(329, 326, "Import as preset", 13, "#0a0a0a" if p else "#5f7a68", True, "center")
        def check(*_):
            v = e_.get().strip(); res["p"], res["err"] = decode_preset(v) if v else (None, None); ddraw()
        def dhit(e):
            x, y = e.x / S, e.y / S
            if 438 <= x <= 466 and 20 <= y <= 50: return "x"
            if 306 <= y <= 346: return "cancel" if 24 <= x <= 190 else ("ok" if 202 <= x <= 456 else None)
        def dmove(e):
            h = dhit(e)
            if h != res["hov"]: res["hov"] = h; dc.config(cursor="hand2" if h and (h != "ok" or res["p"]) else ""); ddraw()
        def go_import():
            if res["p"]: d.destroy(); import_preset(res["p"])
        def dclick(e):
            h = dhit(e)
            if h in ("x", "cancel"): d.destroy()
            elif h == "ok": go_import()
        dc.bind("<Motion>", dmove); dc.bind("<ButtonRelease-1>", dclick)
        e_.bind("<KeyRelease>", check); e_.bind("<<Paste>>", lambda e: d.after(1, check)); e_.bind("<Return>", lambda e: go_import())
        d.bind("<Escape>", lambda e: d.destroy())
        try:
            clip = win.clipboard_get()
            if isinstance(clip, str) and clip.strip().startswith("AOE4S"): e_.insert(0, clip.strip())
        except Exception: pass
        check(); reveal(d, over=win); e_.focus_set(); win._imp = (d, e_, res, go_import, check)
        return "break"
    BAR_Y = 92
    def add_dialog():
        """Search Spotify, add what's playing, or paste a link. Clicking a result adds it."""
        D = dict(bg=C["card"], row="#2a2a2a", fld="#232323", tx=C["tx"], mu=C["mu"], acc=C["acc"])
        d = tk.Toplevel(win); dark_window(d, D["bg"]); d.title("Add a song"); d.resizable(False, False); d.transient(win)
        Wd, RHd, NR = 400, 52, 6
        top = tk.Frame(d, bg=D["bg"]); top.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(top, text="Add a song", bg=D["bg"], fg=D["tx"], font=("Segoe UI", 12, "bold")).pack(side="left")
        fr = tk.Frame(d, bg=D["fld"], highlightthickness=1, highlightbackground="#3a3a3a", highlightcolor=D["acc"]); fr.pack(fill="x", padx=16)
        tk.Label(fr, text="\u2315", bg=D["fld"], fg=D["mu"], font=("Segoe UI Symbol", 12)).pack(side="left", padx=(8, 0))
        e_ = tk.Entry(fr, bg=D["fld"], fg=D["tx"], insertbackground=D["tx"], relief="flat", font=("Segoe UI", 11), width=36)
        e_.pack(side="left", fill="x", expand=True, ipady=7, padx=(4, 8))
        ph = tk.Label(fr, text="Search Spotify or paste a song link", bg=D["fld"], fg="#6f6f6f", font=("Segoe UI", 11))
        ph.place(x=30, rely=0.5, anchor="w"); ph.bind("<Button-1>", lambda e: e_.focus_set())
        np_ = tk.Label(d, text="\u266b  Add what's playing", bg=D["row"], fg=D["tx"], font=("Segoe UI", 10, "bold"), padx=12, pady=6, cursor="hand2")
        np_.pack(anchor="w", padx=16, pady=(10, 6))
        np_.bind("<Enter>", lambda e: np_.config(bg="#333333")); np_.bind("<Leave>", lambda e: np_.config(bg=D["row"]))
        rc = tk.Canvas(d, width=Wd * S, height=NR * RHd * S, bg=D["bg"], highlightthickness=0); rc.pack(padx=16 - 8, pady=(0, 4))
        msg = tk.Label(d, text="", bg=D["bg"], fg=D["mu"], font=("Segoe UI", 9)); msg.pack(anchor="w", padx=16, pady=(0, 12))
        R = {"items": [], "hov": None, "job": None, "seq": 0, "thumbs": {}, "busy": False}
        def say(t, err=False): msg.config(text=t, fg="#e5534b" if err else D["mu"])
        def thumb(item):
            u = item["uri"]
            if u in R["thumbs"]: return R["thumbs"][u]
            return None
        def paint():
            rc.delete("all")
            have = {c.get("uri") for c in (user.get("custom_songs") or [])} | set(SONG_BY_URI)
            for k, it in enumerate(R["items"][:NR]):
                y0 = k * RHd; added = it["uri"] in have
                if R["hov"] == k and not added: rc.create_image(0, y0 * S, anchor="nw", image=rr_img(Wd, RHd - 4, 10, D["row"]))
                im = thumb(it)
                if im: rc.create_image((8 + 20) * S, (y0 + 24) * S, image=im)
                else: rc.create_image(8 * S, (y0 + 4) * S, anchor="nw", image=rr_img(40, 40, 8, "#333333"))
                name = it.get("name", ""); art_ = ", ".join(a_.get("name", "") for a_ in (it.get("artists") or [])[:2])
                rc.create_text(58 * S, (y0 + 16) * S, text=name[:44], anchor="w", fill=D["mu"] if added else D["tx"], font=("Segoe UI", -int(12 * S), "bold"))
                rc.create_text(58 * S, (y0 + 33) * S, text=art_[:52], anchor="w", fill=D["mu"], font=("Segoe UI", -int(10.5 * S)))
                if added: rc.create_text((Wd - 12) * S, (y0 + 24) * S, text="\u2713 Added", anchor="e", fill=D["acc"], font=("Segoe UI", -int(10 * S), "bold"))
                elif R["hov"] == k: rc.create_text((Wd - 12) * S, (y0 + 24) * S, text="+ Add", anchor="e", fill=D["acc"], font=("Segoe UI", -int(10 * S), "bold"))
        def load_thumbs(items, seq):
            from PIL import Image, ImageDraw
            import io
            for it in items[:NR]:
                if it["uri"] in R["thumbs"] or seq != R["seq"]: continue
                url = pick_image((it.get("album") or {}).get("images"), 64)
                try: im = Image.open(io.BytesIO(http_get(url))).convert("RGB") if url else None
                except Exception: im = None
                if im is None: continue
                Z = int(40 * S); Q = 4; im = im.resize((Z * Q, Z * Q), Image.LANCZOS)
                m = Image.new("L", im.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, Z * Q - 1, Z * Q - 1], 8 * S * Q, fill=255)
                out = Image.new("RGBA", im.size, (0, 0, 0, 0)); out.paste(im, (0, 0), m); out = out.resize((Z, Z), Image.LANCZOS)
                def put(u=it["uri"], o=out):
                    try: R["thumbs"][u] = ImageTk.PhotoImage(o, master=d); paint()
                    except Exception: pass
                try: ui(put)
                except Exception: return
        def sp_():
            sp = Spotify(load_config())
            return sp if sp.tok else None
        def show(items, seq):
            if seq != R["seq"]: return
            R["items"] = items or []; R["hov"] = None; paint()
            if items is None: say("Couldn't search (offline?)", True)
            elif not items: say("No songs found")
            else: say("Click a song to add it")
            if items: threading.Thread(target=load_thumbs, args=(items, seq), daemon=True).start()
        def search(q):
            R["seq"] += 1; seq = R["seq"]; say("Searching\u2026")
            def go():
                try:
                    sp = sp_(); res = search_tracks(sp, q) if sp else "login"
                except Exception as ex: log("Search: %r" % ex); res = None
                def done():
                    if res == "login": say("Log in to Spotify in AoE4 Spotify first", True)
                    else: show(res, seq)
                try: ui(done)
                except Exception: pass
            threading.Thread(target=go, daemon=True).start()
        def add_items(objs, close=False):
            got = [store_track(o) for o in objs]          # (cover download happens on a worker)
            def done():
                n = add_customs(got); paint()
                say("Added \u2713" if n else "Already in YOURS")
                if close and n:
                    try: d.destroy()
                    except Exception: pass
            try: ui(done)
            except Exception: pass
        def add_links(uris):
            say("Looking it up\u2026")
            def go():
                try:
                    sp = sp_(); got = fetch_tracks(sp, uris) if sp else "login"
                except Exception as ex: log("Add song: %r" % ex); got = None
                def done():
                    if got == "login": say("Log in to Spotify in AoE4 Spotify first", True)
                    elif not got: say("Couldn't find that song (offline?)", True)
                    else:
                        n = add_customs(got); say("Added \u2713" if n else "Already in YOURS")
                        if n: d.destroy()
                try: ui(done)
                except Exception: pass
            threading.Thread(target=go, daemon=True).start()
        def on_key(*_):
            t = e_.get().strip(); ph.place_forget() if t else ph.place(x=30, rely=0.5, anchor="w")
            if R["job"]: d.after_cancel(R["job"]); R["job"] = None
            if not t: R["seq"] += 1; R["items"] = []; paint(); say(""); return
            uris = parse_tracks(t)
            if uris:
                new = [u for u in uris if u not in SONG_BY_URI]
                if not new: say("Already in YOURS"); return
                say("Press Enter to add" + (" %d songs" % len(new) if len(new) > 1 else "")); return
            R["job"] = d.after(350, lambda: search(t))      # debounced
        def ok(*_):
            t = e_.get().strip(); uris = parse_tracks(t)
            if uris:
                new = [u for u in uris if u not in SONG_BY_URI]
                if new: add_links(new)
                else: say("Already in YOURS")
            elif t:
                if R["items"]: threading.Thread(target=add_items, args=([R["items"][0]],), daemon=True).start()
                else: search(t)
            else: say("Type a song name or paste a Spotify song link", True)
        def what_playing(*_):
            say("Checking Spotify\u2026")
            def go():
                try:
                    sp = sp_(); it = now_playing(sp) if sp else "login"
                except Exception as ex: log("Now playing: %r" % ex); it = None
                def done():
                    if it == "login": say("Log in to Spotify in AoE4 Spotify first", True)
                    elif not it: say("Nothing is playing on Spotify", True)
                    elif it["uri"] in SONG_BY_URI: say("\u201c%s\u201d is already in YOURS" % it.get("name", ""))
                    else: threading.Thread(target=add_items, args=([it], True), daemon=True).start()
                try: ui(done)
                except Exception: pass
            threading.Thread(target=go, daemon=True).start()
        def row_at(ev):
            k = int(ev.y / S // RHd)
            return k if 0 <= k < min(NR, len(R["items"])) else None
        def on_motion(ev):
            k = row_at(ev)
            if k != R["hov"]: R["hov"] = k; rc.config(cursor="hand2" if k is not None else ""); paint()
        def on_click(ev):
            k = row_at(ev)
            if k is None: return
            it = R["items"][k]
            if it["uri"] in SONG_BY_URI: return
            threading.Thread(target=add_items, args=([it],), daemon=True).start()
        rc.bind("<Motion>", on_motion); rc.bind("<Leave>", lambda e: (R.update(hov=None), rc.config(cursor=""), paint()))
        rc.bind("<ButtonRelease-1>", on_click); np_.bind("<Button-1>", what_playing)
        e_.bind("<KeyRelease>", on_key); e_.bind("<<Paste>>", lambda e: d.after(1, on_key))
        e_.bind("<Return>", ok); d.bind("<Escape>", lambda e: d.destroy())
        reveal(d, over=win); e_.focus_set()
        win._add = (d, e_, ok, msg, {"R": R, "on_key": on_key, "search": search, "what_playing": what_playing, "click_row": lambda k: on_click(type("E", (), {"y": (k * RHd + 10) * S})()), "paint": paint})   # (tests)
        return "break"
    win.bind("<Control-z>", lambda e: undo_redo(True)); win.bind("<Control-Z>", lambda e: undo_redo(False))   # Ctrl+Shift+Z
    win.bind("<Control-y>", lambda e: undo_redo(False)); win.bind("<Control-Y>", lambda e: undo_redo(False))
    win.bind("<Control-Shift-Z>", lambda e: undo_redo(False)); win.bind("<Control-Shift-z>", lambda e: undo_redo(False))
    # ---- hit testing (logical coords)
    def hit(x, y):
        if ed["page"] == "overview":
            m = st.get("menu")
            if m == "presets":
                ps = user_presets(user)
                for i_, p in enumerate(ps):
                    if 26 <= x <= 324 and 126 + i_ * 46 <= y <= 168 + i_ * 46: return ("pm", p["name"])
                yn = 126 + len(ps) * 46
                if 26 <= x <= 324 and yn + 2 <= y <= yn + 32: return ("pnew",)
                if 20 <= x <= 330 and 116 <= y <= yn + 40: return ("menu",)
            elif m == "save":
                if 344 <= x <= 544 and 116 <= y <= 148: return ("ssave",) if not (cur_preset() or {}).get("builtin") else ("menu",)
                if 344 <= x <= 544 and 148 <= y <= 182: return ("snew",)
            if 74 <= y <= 110:
                if 20 <= x <= 330: return ("preset",)
                if 344 <= x <= 436: return ("save",)
                if (x - 494) ** 2 + (y - BAR_Y) ** 2 <= 16 ** 2: return ("share",)
                if (x - 542) ** 2 + (y - BAR_Y) ** 2 <= 16 ** 2: return ("import",)
            if m: return None
            for k, a_ in enumerate(INTRO_AGES):
                y0 = CARD_Y(k)
                if 20 <= x <= 580 and y0 <= y <= y0 + 128:
                    if 490 <= x <= 544 and y0 + 26 <= y <= y0 + 58: return ("swoff", a_, 515, y0 + 58) if age_empty(a_) else ("cardtog", a_)
                    return ("card", a_)
            return None
        for i in range(len(SONGS) + 1):
            cx, cy = tray_xy(i); rt = tray_rad(i) + 2
            if (x - cx) ** 2 + (y - cy) ** 2 <= rt ** 2: return ("tray", i) if i < len(SONGS) else ("plus",)
        if 18 <= x <= 50 and 42 <= y <= 74: return ("back",)
        if 520 <= x <= 566 and 44 <= y <= 72: return ("swoff", ed["age"], 544, 74) if age_empty(ed["age"]) else ("tabtog", ed["age"])
        if age_custom() and 568 <= x <= 590 and 46 <= y <= 70: return ("reset",)
        if LT <= y <= BOT and 20 <= x <= 568:
            i = int((y - LT + st["sc"]) // STEP)
            if 0 <= i < len(CIV_LIST) and row_y(i) <= y <= row_y(i) + RH:
                p = pools()[CIV_LIST[i][0]]; minn = 0
                for j in range(len(p)):
                    cx, cy = chip_xy(i, j)
                    if len(p) > minn and (x - cx - 11) ** 2 + (y - cy + 11) ** 2 <= 7 ** 2 and st["hov"] in (("chip", i, j), ("x", i, j)):
                        return ("x", i, j)
                    if (x - cx) ** 2 + (y - cy) ** 2 <= 16 ** 2: return ("chip", i, j)
                if ed["age"] == "imperial" and 532 <= x <= 562: return ("undo", i)
                return ("row", i)
        return None
    def sw(x0, y0, on, disabled=False):                # small anti-aliased switch (greyed = can't be turned on)
        rr(x0, y0, x0 + 36, y0 + 20, 10, "#2e2e2e" if disabled else (C["acc"] if on else "#464646"))
        kx = x0 + 26 if on else x0 + 10
        cv.create_image(kx * S, (y0 + 10) * S, image=art.disc(14, "#6a6a6a" if disabled else "#ffffff"))
    def badge(x, y, age, on, r):
        cv.create_image(x * S, y * S, image=art.disc(2 * r, "#1e3c28" if on else "#2c2c2c",
                        {"dark": "I", "feudal": "II", "castle": "III", "imperial": "IV"}[age], C["acc"] if on else C["mu"], r * 0.62))
    def chev(x, y, c, back=False):
        cv.create_image(x * S, y * S, image=art.chevron(22, c, back)); return
        k = -1 if back else 1
        cv.create_line((x - 4 * k) * S, (y - 7) * S, (x + 3 * k) * S, y * S, (x - 4 * k) * S, (y + 7) * S, fill=c,
                       width=max(1, 2 * S), capstyle="round", joinstyle="round")
    def draw_overview():
        cv.delete("all"); on = ages_on(); hov = st["hov"]
        cv.create_polygon(*[v * S for v in (20, 58, 20, 42, 27, 49, 32, 38, 37, 49, 44, 42, 44, 58)], fill=C["acc"])
        text(52, 49, "Age Intros", 18, b=True)
        for k, a_ in enumerate(INTRO_AGES):
            y = CARD_Y(k); p = pools(a_); n = sum(1 for v in p.values() if v); hv = hov and hov[1:] == (a_,)
            rr(20, y, 580, y + 128, 18, "#262626" if hv else C["card"], "#464646" if hv else None)
            badge(62, y + 42, a_, on[a_], 24)
            text(100, y + 30, a_.capitalize(), 17, b=True)
            text(100, y + 54, ("%d/%d civs" % (n, len(CIV_LIST))) if n else "Empty", 11, C["acc"] if (n and on[a_]) else C["mu"], True)
            sw(498, y + 32, on[a_], age_empty(a_)); chev(560, y + 42, C["mu"])
            rr(100, y + 82, 330, y + 88, 3, "#323232")
            if n: rr(100, y + 82, 100 + max(6, 230 * n // len(CIV_LIST)), y + 88, 3, C["acc"] if on[a_] else "#5a5a5a")
            allu = [u for u in song_sorted([u for v in p.values() for u in v]) if u in SONG_BY_URI]; used = allu[:5]
            if used:
                for j, u in enumerate(used):
                    cv.create_image((375 + j * 24) * S, (y + 85) * S, image=art.chip(SONG_BY_URI[u][0], 13))
                more = len(allu) - len(used)
                if more > 0:                               # '+X' overflow chip (variant A): same size, overlapping
                    ox = (375 + len(used) * 24) * S
                    cv.create_image(ox, (y + 85) * S, image=art.disc(33, "#262626" if hv else C["card"]))
                    cv.create_image(ox, (y + 85) * S, image=art.disc(30, "#2c2c2c", "+%d" % more, "#dcdcdc", 11, outline="#6e6e6e", ow=2.5))
            else:
                for j in range(3):
                    cv.create_oval((360 + j * 24) * S, (y + 70) * S, (390 + j * 24) * S, (y + 100) * S, outline="#464646", width=max(1, S), fill=C["card"])
        if st.get("toast"):
            import tkinter.font as tkfont
            tw = tkfont.Font(root=win, family="Segoe UI", size=-int(13 * S), weight="bold").measure(st["toast"]) / S + 70
            x0 = W / 2 - tw / 2; rr(x0, H - 46, x0 + tw, H - 8, 19, "#282828", C["acc"], 1.2)
            cv.create_image((x0 + 25) * S, (H - 27) * S, image=art.disc(22, C["acc"]))
            cv.create_line(*[v * S for v in (x0 + 19, H - 27, x0 + 23, H - 23, x0 + 30, H - 31)], fill="#0a0a0a", width=max(1, 2.4 * S), capstyle="round", joinstyle="round")
            text(x0 + 45, H - 27, st["toast"], 13, b=True)
        else: text(W / 2, H - 20, "Click an age to edit", 10, "#5a5a5a", anchor="center")
        draw_bar()
    def chev_down(x, y, c):
        cv.create_line(*[v * S for v in (x - 4, y - 2, x, y + 2, x + 4, y - 2)], fill=c, width=max(1, 2 * S), capstyle="round", joinstyle="round")
    def bar_icon(kind, c):
        k = ("baricon", kind, c)
        if k not in imgs:
            Q = 4; Z = even_px(30, S); im = Image.new("RGBA", (Z * Q, Z * Q), (0, 0, 0, 0)); d_ = ImageDraw.Draw(im)
            u = Z * Q / 30.0; cx = cy = Z * Q / 2; lw = max(Q, int(round(1.8 * S * Q)))
            P = lambda pts: [(cx + a * u, cy + b * u) for a, b in pts]
            if kind == "save":
                d_.line(P([(0, -7), (0, 3)]), fill=c, width=lw); d_.line(P([(-4, -1), (0, 3), (4, -1)]), fill=c, width=lw, joint="curve")
                d_.line(P([(-7, 2), (-7, 7), (7, 7), (7, 2)]), fill=c, width=lw, joint="curve")
            elif kind == "share":
                for a, b in ((-5, 0), (5, -6), (5, 6)): d_.ellipse([cx + (a - 2.6) * u, cy + (b - 2.6) * u, cx + (a + 2.6) * u, cy + (b + 2.6) * u], fill=c)
                d_.line(P([(-5, 0), (5, -6)]), fill=c, width=max(Q, int(1.5 * S * Q))); d_.line(P([(-5, 0), (5, 6)]), fill=c, width=max(Q, int(1.5 * S * Q)))
            else:
                d_.rounded_rectangle([cx - 6 * u, cy - 6 * u, cx + 6 * u, cy + 8 * u], 2.5 * u, outline=c, width=lw)
                d_.rounded_rectangle([cx - 3 * u, cy - 8 * u, cx + 3 * u, cy - 4 * u], 1.5 * u, fill=c)
            imgs[k] = ImageTk.PhotoImage(im.resize((Z, Z), Image.LANCZOS), master=win)
        return imgs[k]
    def draw_bar():
        hov = st["hov"] or ("",); m = st.get("menu"); y = BAR_Y; cur = cur_preset()
        op = m == "presets" or hov[0] == "preset"
        rr(20, y - 18, 330, y + 18, 18, "#2a2a2a" if op else C["card"], C["acc"] if m == "presets" else "#3e3e3e", 1.2)
        cv.create_image(40 * S, y * S, image=art.disc(12, C["acc"]))
        text(56, y, user.get("intro_preset") or DEFAULT_PRESET_NAME, 13, b=True)
        if dirty(): cv.create_image(292 * S, y * S, image=art.disc(8, "#c8a24a"))
        chev_down(310, y, C["tx"] if op else C["mu"])
        so = m == "save" or hov[0] == "save"
        rr(344, y - 15, 436, y + 15, 15, "#2a2a2a" if so else C["card"], C["acc"] if m == "save" else "#3e3e3e", 1.2)
        cv.create_image(364 * S, y * S, image=bar_icon("save", C["tx"])); text(378, y, "Save", 12, b=True)
        for cx_, kind in ((494, "share"), (542, "import")):
            hv = hov[0] == kind
            cv.create_image(cx_ * S, y * S, image=art.disc(30, "#383838" if hv else "#2a2a2a"))
            cv.create_image(cx_ * S, y * S, image=bar_icon(kind, "#ffffff" if hv else "#cdcdcd"))
        if m == "presets":
            ps = user_presets(user); yb = 126 + len(ps) * 46
            rr(18, 114, 332, yb + 44, 15, "#0c0c0c"); rr(20, 116, 330, yb + 40, 14, "#242424", "#3e3e3e", 1)
            for i_, p in enumerate(ps):
                yy = 126 + i_ * 46; is_cur = p["name"] == (user.get("intro_preset") or DEFAULT_PRESET_NAME)
                if is_cur: rr(26, yy, 324, yy + 42, 10, "#1e3426")
                elif hov == ("pm", p["name"]): rr(26, yy, 324, yy + 42, 10, "#2e2e2e")
                for j, u_ in enumerate(preset_songs(base, p)[:3]):
                    sg = SONG_BY_URI.get(u_)
                    if sg: cv.create_image((48 + j * 16) * S, (yy + 21) * S, image=art.chip(sg[0], 10))
                text(100, yy + 21, p["name"], 13, C["acc"] if is_cur else C["tx"], True)
                cnt = preset_counts(base, p)
                ag = " ".join(r for r, a_ in zip(("I", "II", "III", "IV"), INTRO_AGES) if cnt[a_] and (p.get("ages") or {}).get(a_, a_ == "imperial"))
                text(250, yy + 21, ag, 10, C["mu"], True)
                if is_cur: cv.create_line(*[v * S for v in (300, yy + 21, 305, yy + 26, 314, yy + 15)], fill=C["acc"], width=max(1, 2.2 * S), capstyle="round", joinstyle="round")
            cv.create_line(32 * S, (yb + 1) * S, 318 * S, (yb + 1) * S, fill="#3e3e3e", width=max(1, int(S)))
            nh = hov[0] == "pnew"
            if nh: rr(26, yb + 4, 324, yb + 32, 8, "#2e2e2e")
            text(48, yb + 18, "+", 16, C["acc"], anchor="center"); text(62, yb + 18, "New preset", 12, C["acc"], True)
        elif m == "save":
            rr(342, 114, 546, 186, 13, "#0c0c0c"); rr(344, 116, 544, 184, 12, "#242424", "#3e3e3e", 1)
            cp = cur_preset(); ro = not cp or cp.get("builtin")
            if hov[0] == "ssave" and not ro: rr(348, 120, 540, 148, 8, "#2e2e2e")
            if hov[0] == "snew": rr(348, 152, 540, 180, 8, "#2e2e2e")
            nm = user.get("intro_preset") or DEFAULT_PRESET_NAME
            text(360, 134, ("Save to \u201c%s\u201d" % nm) if len(nm) <= 14 else "Save to this preset", 12, "#5a5a5a" if ro else C["tx"], True)
            text(360, 166, "Save as new\u2026", 12, C["tx"], True)
    def draw():
        if ed["page"] == "overview": draw_overview(); return
        cv.delete("all"); p = pools(); hov = st["hov"]; drag = st["drag"]
        # list (drawn first; header/tray cover what scrolls above)
        for i, (civ, name) in enumerate(CIV_LIST):
            y = row_y(i)
            if y > BOT or y + RH < LT - 60: continue
            drop = st["drop"] == i
            rr(20, y, 568, y + RH, 10, "#1c2a20" if drop else C["card"], C["acc"] if drop else None)
            cv.create_image(32 * S, (y + RH / 2) * S, anchor="w", image=art.flag(civ))
            text(72, y + RH / 2, name, 12, b=True)
            for j, uri in enumerate(p[civ]):
                s = SONG_BY_URI.get(uri)
                if not s: continue
                cx, cy = chip_xy(i, j)
                moving = drag and drag["src"] == ("row", i, j)
                cv.create_image(cx * S, cy * S, image=art.chip(s[0], CR, dim=bool(moving)))
            cy = y + RH / 2
            if drop:
                x = 205 + len(p[civ]) * 34
                cv.create_oval((x - 15) * S, (cy - 15) * S, (x + 15) * S, (cy + 15) * S, outline=C["acc"], width=max(1, int(1.5 * S)))
                text(x, cy, "+", 13, C["acc"], True, "center")
            elif not p[civ]:                               # empty civ: dashed drop slot (+ hint on the first one)
                cv.create_oval(190 * S, (cy - 15) * S, 220 * S, (cy + 15) * S, outline="#4b4b4b", width=max(1, S), dash=(3, 3))
                if i == next((k for k, (c_, _) in enumerate(CIV_LIST) if not p[c_]), -1):
                    text(205, cy, "+", 13, "#6e6e6e", anchor="center"); text(232, cy, "Drag songs here", 10, "#646464")
            if ed["age"] == "imperial" and p[civ] != song_sorted(default_pool(base, civ)):
                undo_glyph(547, cy, C["mu"])
        # scrollbar
        ms = max_sc()
        if ms:
            th = (BOT - LT) * (BOT - LT) / (BOT - LT + ms); ty = LT + (BOT - LT - th) * st["sc"] / ms
            rr(572, LT, 576, BOT, 2, "#2a2a2a"); rr(572, ty, 576, ty + th, 2, "#5a5a5a")
        # header + tray (opaque, on top of the scrolled list)
        cv.create_rectangle(0, 0, W * S, (LT - 4) * S, fill=C["bg"], outline="", tags="cover")
        cv.create_rectangle(0, BOT * S, W * S, H * S, fill=C["bg"], outline="", tags="cover")
        a_ = ed["age"]; on = ages_on()
        cv.create_image(34 * S, 58 * S, image=art.chevron(32, C["tx"], True, "#2a2a2a" if (st["hov"] or ("",))[0] == "back" else C["card"], w=6, h=12))
        badge(78, 58, a_, on[a_], 15); text(102, 58, a_.capitalize(), 18, b=True)
        sw(526, 48, on[a_], age_empty(a_))
        if age_custom(): undo_glyph(578, 58, C["mu"])
        rr(20, 88, 580, 180, 18, "#1a1a1a", C["line"])
        text(36, 99, "OCTOPATH", 8.5, C["mu"], True)
        if st.get("dropover"):                         # dragging songs in from Spotify
            rr(430, 92, 576, 176, 14, "#16261b", C["acc"], 2); text(438, 99, "DROP TO ADD", 8.5, C["acc"], True)
        else: text(438, 99, "YOURS", 8.5, C["acc"], True)
        cv.create_line(424 * S, 102 * S, 424 * S, 168 * S, fill=C["line"], width=max(1, S))
        for i, s_ in enumerate(SONGS):
            cx, cy = tray_xy(i); tr = tray_rad(i)
            if drag and drag["src"] == ("tray", i):
                cv.create_oval((cx - tr - 3) * S, (cy - tr - 3) * S, (cx + tr + 3) * S, (cy + tr + 3) * S, outline=C["acc"], width=max(1, int(1.5 * S)))
            cv.create_image(cx * S, cy * S, image=art.chip(s_[0], tr))
        cx, cy = tray_xy(len(SONGS)); cv.create_image(cx * S, cy * S, image=art.plus(tray_rad(len(SONGS))))
        # drag ghost
        if drag and drag.get("xy"):
            gx, gy = drag["xy"]; s = SONGS[drag["song"]]
            cv.create_image(gx * S, gy * S, image=art.chip(s[0], 19), tags="ghost")
        overlay()
    # click a chip (no drag) = play that theme on Spotify now; click it again = pause
    pv = {"song": None, "busy": False, "phase": 0, "sp": None, "q": [], "msgjob": None, "env": 0.0, "gsong": None, "gt": 0, "gjob": None,
          "lock": threading.Lock()}
    def _warm():                                       # token + keep-alive connection + device id, before the first click
        try:
            with pv["lock"]:
                if pv["sp"] is None: pv["sp"] = Spotify(load_config())
                sp = pv["sp"]
            if sp.tok and hasattr(sp, "warm"): sp.warm()
        except Exception as e: log("Preview warm-up: %r" % e)
    threading.Thread(target=_warm, daemon=True).start()
    glow_cache = {}
    def hint(msg, x, y):
        st["msg"] = (msg, x, y + 26)
        if pv["msgjob"]: win.after_cancel(pv["msgjob"])
        def clear():
            pv["msgjob"] = None
            if st["msg"] and st["msg"][0] == msg: st["msg"] = None; overlay()
        pv["msgjob"] = win.after(2600, clear); overlay()
    def preview(i, xy):
        if pv["busy"]: return
        action = "pause" if pv["song"] == SONGS[i][0] else "play"
        pv["busy"] = True; pv["xy"] = xy; pv["prev"] = pv["song"]; pv["t_click"] = time.perf_counter()
        pv["song"] = SONGS[i][0] if action == "play" else None          # optimistic: glow reacts on the click
        if action == "play" and pv.get("gsong") != SONGS[i][0]: pv["env"] = 0.0      # new song: one fade-in from 0
        overlay(); glow_kick()
        def go():
            try:
                with pv["lock"]:
                    if pv["sp"] is None: pv["sp"] = Spotify(load_config())
                sp = pv["sp"]
                if not sp.tok: res = "login"
                else: res = bool(sp.preview(SONGS[i][3]) if action == "play" else sp.pause())
            except Exception as e:
                log("Preview failed: %r" % e); res = False
            pv["q"].append((action, i, res))
        threading.Thread(target=go, daemon=True).start()
    def pvpump():
        changed = False
        while pv["q"]:
            action, i, res = pv["q"].pop(0); pv["busy"] = False; changed = True
            pv["t_done"] = time.perf_counter()
            if res == "login": pv["song"] = pv.get("prev"); hint("Log in to Spotify in AoE4 Spotify to preview", *pv["xy"])
            elif action == "play":
                if res: pv["song"] = SONGS[i][0]; log("Preview: %s" % SONGS[i][1])
                else: pv["song"] = pv.get("prev") if pv.get("prev") != SONGS[i][0] else None; hint("Couldn't play - is Spotify (Premium) running?", *pv["xy"])
            else:
                if not res and pv.get("prev"): pv["song"] = pv["prev"]       # pause failed: still playing
                else: pv["song"] = None
        if changed: overlay(); glow_kick()
        try: win.after(30, pvpump)
        except Exception: pass
    def glow_spots(song):
        if ed["page"] == "overview": return []
        spots = [(tray_xy(i), tray_rad(i)) for i, s in enumerate(SONGS) if s[0] == song]
        p = pools()
        for i, (civ, _) in enumerate(CIV_LIST):
            y = row_y(i)
            if y + RH < LT or y > BOT: continue
            for j, uri in enumerate(p[civ]):
                if SONG_BY_URI.get(uri, ("",))[0] == song: spots.append((chip_xy(i, j), CR))
        return spots
    def glow_img(r, ph, env):
        k = (r, ph, env)
        if k not in glow_cache: glow_cache[k] = ImageTk.PhotoImage(render_glow(r, S, ph, env))
        return glow_cache[k]
    def glow_tick():                                   # 'now playing' breathing glow, ~30 fps while active
        pv["gjob"] = None
        if pv["song"]: pv["gsong"] = pv["song"]
        pv["env"] = min(1.0, pv["env"] + 0.1) if pv["song"] else max(0.0, pv["env"] - 0.1)
        pv["gt"] = (pv["gt"] + 1) % GLOW_N
        try:
            glow_sync()
            if pv["song"] or pv["env"] > 0: pv["gjob"] = win.after(33, glow_tick)
        except Exception as ex: log("Glow: %r" % ex)
    def glow_sync():
        """Place the glow items at their chips' *current* positions. Called by the animation timer and at the
        end of every redraw (scroll, drag, edits), so the glow moves in lockstep with its chip: existing items
        are moved/re-imaged in place (coords + itemconfigure), never left at stale coordinates."""
        items = [it for it in pv.setdefault("gitems", []) if cv.type(it)]   # a full redraw deletes them
        moving = st["drag"] and st["drag"].get("xy") is not None          # a press alone is not a drag: keep the glow
        spots = glow_spots(pv["gsong"]) if (pv["env"] > 0 and not moving and pv.get("gsong")) else []
        for n, ((cx, cy), r) in enumerate(spots):
            img = glow_img(r, pv["gt"], round(pv["env"], 1)); tray = cy < LT - 4
            tags = ("glow",) if tray else ("glow", "glowlist")       # list glows scroll under header/bottom covers
            if n < len(items):
                cv.coords(items[n], cx * S, cy * S); cv.itemconfigure(items[n], image=img, tags=tags)
            else:
                items.append(cv.create_image(cx * S, cy * S, image=img, anchor="center", tags=tags))
        for it in items[len(spots):]: cv.delete(it)
        pv["gitems"] = items[:len(spots)]
        # z-order: each glow sits directly ABOVE its own chip (halo, ring and badge over the chip edge; the
        # face shows through the cut-out), but list glows stay below the header/bottom covers that the
        # list scrolls under. Restacked every redraw and tick; items are never recreated for this.
        for it, ((cx, cy), r) in zip(pv["gitems"], spots):
            under = [i for i in cv.find_overlapping(cx * S, cy * S, cx * S, cy * S)
                     if cv.type(i) == "image" and not set(cv.gettags(i)) & {"glow", "cover", "tip", "ghost"}]
            if under: cv.tag_raise(it, under[-1])
            else: cv.tag_raise(it)
        if cv.find_withtag("ovl"): cv.tag_raise("ovl")             # hover ring, x badge, tooltip: always on top
        if cv.find_withtag("ghost"): cv.tag_raise("ghost")
    def glow_kick():
        if not pv["gjob"]: glow_tick()
    _draw_base = draw
    def draw():                                        # every redraw re-places the glow in the same pass
        _draw_base()
        try: glow_sync()
        except Exception as ex: log("Glow: %r" % ex)
    def playing_marks():
        return                                         # replaced by the glow layer (glow_tick)
        import math
        k = 1.5 + 1.5 * math.sin(pv["phase"] / 24 * 2 * math.pi)            # gentle pulse
        lw = max(1, int(2 * S))
        spots = [(tray_xy(i), 20) for i, s in enumerate(SONGS) if s[0] == pv["song"]]
        p = pools()
        for i, (civ, _) in enumerate(CIV_LIST):
            y = row_y(i)
            if y + RH < LT or y > BOT: continue
            for j, uri in enumerate(p[civ]):
                if SONG_BY_URI.get(uri, ("",))[0] == pv["song"]: spots.append((chip_xy(i, j), 15))
        for (cx, cy), r in spots:
            R = r + 3 + k
            cv.create_oval((cx - R) * S, (cy - R) * S, (cx + R) * S, (cy + R) * S, outline=C["acc"], width=lw)
            bx, by = cx + r * 0.72, cy + r * 0.72                             # small speaker badge
            cv.create_oval((bx - 7) * S, (by - 7) * S, (bx + 7) * S, (by + 7) * S, fill=C["acc"], outline=C["bg"], width=lw)
            text(bx, by - 0.5, "\u266a", 9, "#121212", True, "center")

    def overlay():
        """Hover-only layer (highlights, x badge, tooltip): redrawn alone, so hovering never re-renders the list."""
        cv.delete("ovl"); mark = max(cv.find_all() or (0,)); hov = st["hov"]; drag = st["drag"]
        playing_marks()
        if hov and not drag:
            p = pools()
            if ed["page"] == "overview": pass
            elif hov[0] in ("chip", "x") and len(p[CIV_LIST[hov[1]][0]]) > 0:
                cx, cy = chip_xy(hov[1], hov[2]); xc = C["acc"] if hov[0] == "x" else "#3a3a3a"
                cv.create_image((cx + 11) * S, (cy - 11) * S, image=art.disc(14, xc, fg=C["tx"], cross=2.6, outline=C["bg"], ow=1.5))
            elif hov[0] == "undo" and p[CIV_LIST[hov[1]][0]] != song_sorted(default_pool(base, CIV_LIST[hov[1]][0])):
                y = row_y(hov[1]) + RH / 2
                if LT <= y <= BOT: undo_glyph(547, y, C["tx"])
            elif hov[0] == "reset" and age_custom():
                undo_glyph(578, 58, C["tx"])
            elif hov[0] == "back":
                cv.create_image(34 * S, 58 * S, image=art.chevron(32, C["tx"], True, "#2a2a2a", w=6, h=12))
            elif hov[0] == "plus":                     # brighter '+' instead of a second ring
                cx, cy = tray_xy(len(SONGS)); cv.create_image(cx * S, cy * S, image=art.plus(tray_rad(len(SONGS)), hover=True))
            elif hov[0] == "tray":
                ii = hov[1]; cx, cy = tray_xy(ii); R_ = tray_rad(ii) + 3
                cv.create_oval((cx - R_) * S, (cy - R_) * S, (cx + R_) * S, (cy + R_) * S, outline=C["acc"], width=max(1, int(1.5 * S)))
        hov = hov if st.get("tipok") else None
        p = pools()
        tip = None
        if not drag and hov and hov[0] in ("tray", "chip"):
            s = SONGS[hov[1]] if hov[0] == "tray" else SONG_BY_URI.get(p[CIV_LIST[hov[1]][0]][hov[2]])
            if s:
                cx, cy = tray_xy(hov[1]) if hov[0] == "tray" else chip_xy(hov[1], hov[2])
                tip = ("%s \u2014 %s" % (s[1], s[2]) if s[2] else s[1], cx, cy + 26)

        if hov and hov[0] == "swoff": tip = ("Add a song first", hov[2], hov[3])
        if st.get("press") and not st.get("released", True): tip = None       # mouse button down: no tooltips
        if st["msg"]: tip = st["msg"]
        if tip:                                        # measured text, even padding, same look as the panel tooltips
            import tkinter.font as tkfont
            fnt = tkfont.Font(root=win, family="Segoe UI", size=-int(10 * S))
            tw = fnt.measure(tip[0]) / S + 20; x0 = min(max(8, tip[1] - tw / 2), W - 8 - tw)
            rr(x0, tip[2], x0 + tw, tip[2] + 24, 8, "#2a2a2a", "#3d3d3d", 1)
            text(x0 + tw / 2, tip[2] + 12, tip[0], 10, C["tx"], anchor="center")
        for it in cv.find_all():
            if it > mark: cv.addtag_withtag("ovl", it)
    tipjob = {"id": None}
    def set_hover(h):
        """Hover changed: update the overlay now, show the tooltip after a short delay."""
        OV = ("card", "cardtog", "swoff", "preset", "save", "share", "import", "pm", "pnew", "ssave", "snew")
        redraw = ed["page"] == "overview" and (st["hov"] or ("",))[0] in OV or (h or ("",))[0] in OV
        st["hov"] = h; st["msg"] = None; st["tipok"] = False
        if redraw and ed["page"] == "overview": draw()                 # card hover highlight
        if tipjob["id"]: win.after_cancel(tipjob["id"]); tipjob["id"] = None
        if h and h[0] in ("tray", "chip", "swoff"):
            tipjob["id"] = win.after(300, lambda: (st.update(tipok=True), tipjob.update(id=None), overlay()))
        overlay()
        cur = "hand2" if h and h[0] in ("tray", "chip", "x", "undo", "reset", "plus", "tabtog", "card", "cardtog", "back",
                                        "preset", "save", "share", "import", "pm", "pnew", "ssave", "snew") else ("no" if h and h[0] == "swoff" else "")
        if cv.cget("cursor") != cur: cv.config(cursor=cur)
    def L(e): return e.x / S, e.y / S
    def on_motion(e):
        t0 = time.perf_counter(); h = hit(*L(e))
        if h != st["hov"]: set_hover(h)
        st["mt"] = max(st.get("mt", 0), time.perf_counter() - t0)     # slowest motion handler (tests)
    def on_press(e):
        cv.focus_set()                                     # keep keyboard focus here (Ctrl+Z / Ctrl+Y)
        x, y = L(e); h = hit(x, y); st["press"] = (x, y, h); st["released"] = False
        if h and h[0] == "tray": st["drag"] = {"src": h, "song": h[1], "xy": None}
        elif h and h[0] == "chip" and pools()[CIV_LIST[h[1]][0]][h[2]] in SONG_BY_URI:
            uri = pools()[CIV_LIST[h[1]][0]][h[2]]
            st["drag"] = {"src": ("row", h[1], h[2]), "song": [s[3] for s in SONGS].index(uri), "xy": None}
    def on_drag(e):
        d = st["drag"]
        if not d: return
        x, y = L(e); px, py, _ = st["press"]
        if d["xy"] is None and abs(x - px) + abs(y - py) < 4: return       # < 4 px = a click (preview)
        d["xy"] = (x, y)
        if y > BOT - 24 and st["sc"] < max_sc(): st["sc"] = min(max_sc(), st["sc"] + 8)     # auto-scroll while dragging
        elif LT < y < LT + 24 and st["sc"] > 0: st["sc"] = max(0, st["sc"] - 8)
        sc0, drop0 = st["sc"], st["drop"]
        h = hit(x, y); st["drop"] = h[1] if h and h[0] in ("row", "chip", "x", "undo") else None
        if st["drop"] is not None and d["src"][0] == "row" and d["src"][1] == st["drop"]: st["drop"] = None
        if st["drop"] is not None and SONGS[d["song"]][3] in pools()[CIV_LIST[st["drop"]][0]]: st["drop"] = None   # no duplicates
        if st["sc"] == sc0 and st["drop"] == drop0 and cv.find_withtag("ghost"): cv.coords("ghost", x * S, y * S)
        else: draw()
    def on_release(e):
        st["released"] = True; d, st["drag"] = st["drag"], None; drop, st["drop"] = st["drop"], None
        x, y = L(e); h = hit(x, y); p = pools()
        if d and d["xy"] is not None:
            uri = SONGS[d["song"]][3]
            if drop is not None:
                civ = CIV_LIST[drop][0]
                if uri not in p[civ]: p[civ].append(uri)
                if d["src"][0] == "row" and len(p[CIV_LIST[d["src"][1]][0]]) > 1: p[CIV_LIST[d["src"][1]][0]].remove(uri)   # move
                commit(p)
            elif d["src"][0] == "row" and not (h and h[0] in ("row", "chip", "x", "undo") and h[1] == d["src"][1]):
                remove(d["src"][1], d["src"][2])        # dragged out of its row
            st["hov"] = hit(x, y); draw(); return
        ph = st["press"][2] if st["press"] else None
        if d and ph and ph[0] in ("tray", "chip") and h == ph:                 # click on a chip: preview
            preview(d["song"], tray_xy(ph[1]) if ph[0] == "tray" else chip_xy(ph[1], ph[2]))
        elif ed["page"] == "overview" and st.get("menu") and not (h and h[0] in ("pm", "pnew", "ssave", "snew", "menu", "preset", "save")):
            st["menu"] = None                              # click outside an open menu just closes it
        elif h and h[0] == "preset": st["menu"] = None if st.get("menu") == "presets" else "presets"
        elif h and h[0] == "save": st["menu"] = None if st.get("menu") == "save" else "save"
        elif h and h[0] == "pm": switch_preset(h[1]); return
        elif h and h[0] == "pnew": st["menu"] = None; draw(); win.after_idle(lambda: name_dialog("New preset", "My preset", save_preset)); return
        elif h and h[0] == "ssave": save_preset(); toast("Saved"); return
        elif h and h[0] == "snew": st["menu"] = None; draw(); win.after_idle(lambda: name_dialog("Save as new preset", "My preset", save_preset)); return
        elif h and h[0] == "share": share(); return
        elif h and h[0] == "import": win.after_idle(import_dialog)
        elif h and h[0] == "card": open_page(h[1]); return
        elif h and h[0] == "cardtog": set_age_on(h[1], not ages_on()[h[1]])
        elif h and h[0] == "back": open_page("overview"); return
        elif h and h[0] == "x": remove(h[1], h[2])
        elif h and h[0] == "undo":
            p = pools(); p[CIV_LIST[h[1]][0]] = row_default(CIV_LIST[h[1]][0]); commit(p)
        elif h and h[0] == "reset": commit({c: row_default(c) for c, _ in CIV_LIST})
        elif h and h[0] == "tabtog": set_age_on(h[1], not ages_on()[h[1]])
        elif h and h[0] == "plus": win.after_idle(add_dialog)
        st["hov"] = hit(x, y); draw()
    def remove(i, j):
        p = pools(); civ = CIV_LIST[i][0]
        p[civ].pop(j); commit(p)
    def on_right(e):
        h = hit(*L(e))
        if h and h[0] in ("chip", "x"): remove(h[1], h[2]); st["hov"] = hit(*L(e)); draw()
        elif h and h[0] == "tray" and SONGS[h[1]][0].startswith("c_"):          # your own song: right-click > Remove
            uri = SONGS[h[1]][3]; m = tk.Menu(win, tearoff=0, bg=C["card"], fg=C["tx"], activebackground="#2a2a2a", activeforeground=C["tx"])
            m.add_command(label="Remove song", command=lambda: remove_custom(uri)); win._menu = m
            try: m.tk_popup(e.x_root, e.y_root)
            finally: m.grab_release()
    def on_wheel(e):
        if ed["page"] == "overview": return
        st["sc"] = max(0, min(max_sc(), st["sc"] - (e.delta / 120) * 46)); st["hov"] = hit(*L(e)); draw()
    cv.bind("<Motion>", on_motion); cv.bind("<ButtonPress-1>", on_press); cv.bind("<B1-Motion>", on_drag)
    cv.bind("<ButtonRelease-1>", on_release); cv.bind("<Button-3>", on_right); cv.bind("<MouseWheel>", on_wheel)
    cv.bind("<Leave>", lambda e: set_hover(None) if not st["drag"] else None)
    win.bind("<Escape>", lambda e: open_page("overview") if ed["page"] != "overview" else (st.update(menu=None), draw()))
    win.bind("<BackSpace>", lambda e: open_page("overview") if ed["page"] != "overview" else None)
    set_app_icon(win)
    draw(); fetch_missing_covers()
    pvpump()
    win._ed = {"record": record, "undo_redo": undo_redo, "pv": pv, "cv": cv, "st": st, "pools": pools, "tray_xy": tray_xy, "chip_xy": chip_xy, "row_y": row_y, "S": S, "draw": draw,
               "ed": ed, "ages_on": ages_on, "add_custom": add_custom, "remove_custom": remove_custom, "add_dialog": add_dialog, "hist": hist, "glow_kick": glow_kick,
               "open_page": open_page, "set_age_on": set_age_on, "tray_rad": tray_rad, "CARD_Y": CARD_Y,
               "switch_preset": switch_preset, "save_preset": save_preset, "share": share, "import_preset": import_preset,
               "import_dialog": import_dialog, "dirty": dirty, "toast": toast}  # tests
    reveal(win, over=parent); note_window("editor", win); win.lift(); win.focus_force()
    return win

# ---- shared glow renderer (also used standalone for the frame strip)
GLOW_N = 54                                        # frames per breathing cycle (54 x 33 ms = 1.8 s)
def ink_centre(layer):
    """Shift a glyph layer (RGBA, supersampled) so the centroid of its ink sits on the image centre."""
    from PIL import ImageChops
    al = layer.getchannel("A"); W_, H_ = al.size; data = al.load(); sx = sy = tot = 0
    for y in range(0, H_):
        for x in range(0, W_):
            v = data[x, y]
            if v: sx += x * v; sy += y * v; tot += v
    if not tot: return layer
    dx = int(round((W_ - 1) / 2 - sx / tot)); dy = int(round((H_ - 1) / 2 - sy / tot))
    return ImageChops.offset(layer, dx, dy)

def even_px(logical, S):
    """Pixel size rounded to an EVEN number: Tk centres images at coord - size//2, so even sizes put the
    image centre exactly on the coordinate (odd ones land half a pixel off)."""
    n = int(round(logical * S)); return n + (n % 2)

def chip_px(r, S): n = int(round((2 * r + 4) * S)); return n + (n % 2)   # always even: centred on whole pixels   # chip image size; the glow shares its parity

def render_glow(r, S, phase, env, Q=4, badge=True):
    """One frame of the 'now playing' glow around a round chip of logical radius r (RGBA PIL image).
    Feathered radial halo (opacity ~35%..75%, breathing scale), crisp thin inner ring, tiny equalizer badge."""
    import math
    from PIL import Image, ImageDraw
    t = 0.5 - 0.5 * math.cos(2 * math.pi * phase / GLOW_N)          # ease-in-out sine 0..1..0
    # Same parity as the chip image: Tk centres an image at coord - size//2, so an odd chip with an even
    # glow (or vice versa) lands half a pixel off. D = chip + 2*pad keeps both centres on the same pixel.
    D = chip_px(r, S) + 2 * int(round(16 * S)); B = D * Q; c = B / 2; k = S * Q
    im = Image.new("RGBA", (B, B), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    def box(rad):                         # integer, inclusive box symmetric about the image centre (PIL rounds otherwise)
        R = int(round(rad)); C = B // 2; return [C - R, C - R, C + R - 1, C + R - 1]
    g = (29, 185, 84)
    a_max = (0.35 + 0.40 * t) * env
    r0 = r * k; r1 = (r + 9 + 7 * t) * k                             # halo from chip edge out to r1 (breathes)
    steps = 48
    for s in range(steps, -1, -1):                                   # outer -> inner, each ring overwrites
        f = s / steps; rad = r0 + (r1 - r0) * f
        a = a_max * (1 - f) ** 2.2                                   # smooth falloff, no hard edge
        d.ellipse(box(rad), fill=g + (int(255 * a),))
    ri = (r - 0.5) * k; d.ellipse(box(ri), fill=(0, 0, 0, 0))   # keep the portrait clean
    br = 0.25 + 0.35 * t                                              # ring brightness modulation
    rc = tuple(int(g[i] + (255 - g[i]) * br * 0.6) for i in range(3))
    rr_ = (r + 1.6) * k; w = max(1, int(1.4 * k))
    d.ellipse(box(rr_), outline=rc + (int(235 * env),), width=w)
    if not badge: return im.resize((D, D), Image.LANCZOS)
    bx, by, br_ = c + r * 0.86 * k, c + r * 0.86 * k, 6.0 * k       # equalizer badge: small, bottom-right, off the face
    d.ellipse([bx - br_, by - br_, bx + br_, by + br_], fill=(18, 18, 18, int(255 * env)), outline=g + (int(255 * env),), width=max(1, int(1.2 * k)))
    for i in range(3):
        h = (1.8 + 3.6 * (0.5 + 0.5 * math.sin(2 * math.pi * (2 * phase / GLOW_N + i * 0.37) + i))) * k
        x = bx + (i - 1) * 2.6 * k; bw = 0.85 * k
        d.rounded_rectangle([x - bw, by + 2.7 * k - h, x + bw, by + 2.7 * k], bw, fill=g + (int(255 * env),))
    return im.resize((D, D), Image.LANCZOS)

LATEST_API = "https://api.github.com/repos/Capstar1/aoe4-spotify/releases/latest"

def parse_ver(v):
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:3]) + (0,) * (3 - len(nums[:3])) if nums else (0, 0, 0)

def check_update(timeout=6, report=False):
    """{version, url, size, sha256} if GitHub has a newer release (with a Setup .exe) than VERSION, else None.
    Offline or any error -> None (silently)."""
    try:
        api = os.environ.get("AOE4SPOTIFY_UPDATE_API") or LATEST_API     # env var: testing only (fake release)
        req = urllib.request.Request(api, headers={"Accept": "application/vnd.github+json", "User-Agent": "AoE4-Spotify"})
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
    req = urllib.request.Request(info["url"], headers={"User-Agent": "AoE4-Spotify"})
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
                      "/LOG=" + os.path.join(DATA, "update_setup.log")], env=child_env(), close_fds=True)

def load_user(): return load_user_settings()

def save_user(u):
    tmp = USER_CONFIG + ".tmp"                      # write-then-rename: never leaves a half-written file
    with open(tmp, "w", encoding="utf-8") as f: json.dump(u, f, indent=2)
    os.replace(tmp, USER_CONFIG)

def panel():
    if not single_window("panel", "AoE4 Spotify"): return
    import tkinter as tk, subprocess, webbrowser as wb
    try: import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", off="#3a3a3a", line="#2a2a2a",
             ib="#2a2a2a", idle="#8a8a8a", red="#e5484d", acc="#1DB954", dis="#555555", org="#f0a030")
    root = tk.Tk(); dark_window(root, C["bg"]); root.title("AoE4 Spotify"); root.resizable(False, False)
    S = root.winfo_fpixels("1i") / 96.0
    W, H = 430, 420
    M = 16; R_ = W - M                              # content left / right edge
    cv = tk.Canvas(root, width=int(W * S), height=int(H * S), bg=C["bg"], highlightthickness=0); cv.pack()
    FONT = "Segoe UI"
    def F(sz, b=False): return (FONT, -int(sz * S), "bold" if b else "normal")
    def P(*v): return [x * S for x in v]
    # Shapes are drawn with Pillow at 4x and downscaled, so corners and circles are anti-aliased.
    from PIL import Image, ImageDraw, ImageTk
    imgs = {}
    def _img(key, w, h, paint):
        k = (key, w, h)
        if k not in imgs:
            Q = 4; im = Image.new("RGBA", (max(1, w) * Q, max(1, h) * Q), (0, 0, 0, 0))
            paint(ImageDraw.Draw(im), Q)
            imgs[k] = ImageTk.PhotoImage(im.resize((max(1, w), max(1, h)), Image.LANCZOS))
        return imgs[k]
    def rr(x0, y0, x1, y1, r, fill, outline="", tag=None, width=1):
        X0, Y0, X1, Y1 = [int(round(v)) for v in P(x0, y0, x1, y1)]
        w, h = X1 - X0, Y1 - Y0; rad = min(r * S, w / 2, h / 2)
        def paint(d, Q):
            d.rounded_rectangle([0, 0, w * Q - 1, h * Q - 1], radius=rad * Q, fill=fill or None,
                                outline=outline or None, width=int(width * S * Q) if outline else 0)
        return cv.create_image(X0, Y0, image=_img(("rr", r, fill, outline, width), w, h, paint), anchor="nw", tags=tag)
    def oval_(box, fill="", outline="", width=0, tags=None):
        X0, Y0, X1, Y1 = [int(round(v)) for v in box]
        w, h = X1 - X0, Y1 - Y0
        def paint(d, Q):
            d.ellipse([0, 0, w * Q - 1, h * Q - 1], fill=fill or None, outline=outline or None, width=int(width * Q) if outline else 0)
        return cv.create_image(X0, Y0, image=_img(("ov", fill, outline, width), w, h, paint), anchor="nw", tags=tags)
    def undo_icon(cx, cy, c, tag):
        sz = int(18 * S)
        def paint(d, Q):
            m = sz * Q; lw = max(2, int(2.2 * S * Q))
            d.arc([m*0.18, m*0.2, m*0.86, m*0.88], start=200, end=470, fill=c, width=lw)
            d.polygon([(m*0.04, m*0.42), (m*0.36, m*0.42), (m*0.18, m*0.66)], fill=c)
        return cv.create_image(int(cx * S), int(cy * S), image=_img(("undo", c), sz, sz, paint), anchor="center", tags=tag)
    badge = app_badge
    logo = ImageTk.PhotoImage(badge(int(32 * S)))
    def _icon(px, paint):
        px += px % 2                                       # even size: centre-anchored icons land exactly on their point
        Q = 4; im = Image.new("RGBA", (px * Q, px * Q), (0, 0, 0, 0)); paint(ImageDraw.Draw(im), px * Q, Q)
        return ImageTk.PhotoImage(im.resize((px, px), Image.LANCZOS))
    def _power(d, m, Q):
        lw = int(3 * S * Q); d.arc([m*0.12, m*0.16, m*0.88, m*0.92], start=-60, end=240, fill=C["acc"], width=lw)
        d.rounded_rectangle([m/2 - lw/2, m*0.04, m/2 + lw/2, m*0.5], radius=lw/2, fill=C["acc"])
    def _fade(d, m, Q):
        lw = int(2 * S * Q)
        for k in range(3):     # ink spans x 0.25..0.76 of the box, i.e. centred like the other row icons
            d.arc([m*(-0.2+k*0.18), m*0.12, m*(0.4+k*0.18), m*0.88], start=-60, end=60, fill=C["acc"], width=lw)
    def _chev(up):
        def p(d, m, Q):
            lw = int(2.4 * S * Q); a, b = (0.62, 0.36) if up else (0.38, 0.64)
            d.line([(m*0.22, m*a), (m*0.5, m*b), (m*0.78, m*a)], fill=C["mu"], width=lw, joint="curve")
            for x, yy in ((0.22, a), (0.5, b), (0.78, a)): d.ellipse([m*x - lw/2, m*yy - lw/2, m*x + lw/2, m*yy + lw/2], fill=C["mu"])
        return p
    chev_up = _icon(int(18 * S), _chev(True)); chev_down = _icon(int(18 * S), _chev(False))
    _chevr = {}
    def chev_right(cx, cy, col, tag, size=14):
        """Anti-aliased '>' centred exactly on (cx, cy) - no font baseline involved."""
        k = (col, size)
        if k not in _chevr:
            def p(d, m, Q):
                lw = int(2.2 * S * Q)
                pts = [(m*0.38, m*0.2), (m*0.64, m*0.5), (m*0.38, m*0.8)]
                d.line(pts, fill=col, width=lw, joint="curve")
                for x, yy in pts: d.ellipse([x - lw/2, yy - lw/2, x + lw/2, yy + lw/2], fill=col)
            _chevr[k] = _icon(int(size * S), p)
        cv.create_image(*P(cx, cy), image=_chevr[k], anchor="center", tags=tag)
    ui = {"open": os.environ.get("AOE4SPOTIFY_PANEL_OPEN") == "1"}   # env var: screenshots/testing only
    power_img = _icon(int(30 * S), _power); fade_img = _icon(int(24 * S), _fade)
    def _gear(col):
        def p(d, m, Q):
            import math
            c = m / 2
            for k in range(8):
                a = k * math.pi / 4; d.line([(c, c), (c + m*0.42*math.cos(a), c + m*0.42*math.sin(a))], fill=col, width=int(m * 0.18))
            d.ellipse([c - m*0.32, c - m*0.32, c + m*0.32, c + m*0.32], fill=col)
            d.ellipse([c - m*0.13, c - m*0.13, c + m*0.13, c + m*0.13], fill="#2a2a2a")
        return p
    gear_img = {False: _icon(int(20 * S), _gear(C["tx"])), True: _icon(int(20 * S), _gear(C["acc"]))}
    import tkinter.font as tkfont
    root.iconphoto(True, ImageTk.PhotoImage(badge(64)), ImageTk.PhotoImage(badge(32)))
    set_app_icon(root)
    def text(x, y, s, sz, c=None, b=False, anchor="w", tag=None):
        return cv.create_text(*P(x, y), text=s, font=F(sz, b), fill=c or C["tx"], anchor=anchor, tags=tag)
    # Each tag is bound once; draw() only updates the handler table. (Re-binding inside a click
    # would free the running Tcl callback and crash Tk.) Handlers run after the event finishes.
    handlers, bound = {}, set()
    def hover_hl(i): pass                           # (row highlight is handled by on_pointer)
    hov = {"cursor": "", "row": None, "hl": None, "tip": None, "n": 0}   # what the pointer is over right now
    def on_pointer(e=None, force=False):
        """Single hover handler: everything is derived from the pointer position, and the cursor / Change
        button / highlight / tooltip are only touched when they actually change (no Enter/Leave ping-pong)."""
        if e is not None:
            px, py = e.x, e.y
            if str(e.type) in ("Motion", "6") and not (int(getattr(e, "state", 0) or 0) & 0x100): hov["down"] = False
            hov["xy"] = None if str(e.type) in ("Leave", "8") else (px, py)
        elif hov.get("xy"): px, py = hov["xy"]                # redraw: re-apply hover at the last known pointer spot
        else:
            try: px, py = cv.winfo_pointerx() - cv.winfo_rootx(), cv.winfo_pointery() - cv.winfo_rooty()
            except Exception: return
        inside = 0 <= px < cv.winfo_width() and 0 <= py < cv.winfo_height()
        tags = set()
        if inside:
            for it in cv.find_overlapping(px, py, px, py):
                if cv.itemcget(it, "state") != "hidden": tags.update(cv.gettags(it))
        x, y = px / S, py / S; row = None
        if inside and ui.get("open") and not ui.get("menu") and M + 22 <= x <= R_:
            for i in range(len(AGES)):
                if 216 + i * 50 <= y <= 258 + i * 50: row = i
        if force: hov.update(row="?", hl="?")                 # (cursor/tooltip kept unless they really change)
        if row != hov["row"]:                       # Change button: hover-only, its space is always reserved
            cv.itemconfigure("chgx", state="hidden")
            if row is not None: cv.itemconfigure("chg%d" % row, state="normal")
            hov["row"] = row
        hl = next((int(t[3:]) for t in tags if t.startswith("opn") and t[3:].isdigit()), None)
        if hl != hov["hl"]:
            if isinstance(hov["hl"], int): cv.itemconfigure("hl%d" % hov["hl"], state="hidden")
            if hl is not None: cv.itemconfigure("hl%d" % hl, state="normal")
            hov["hl"] = hl
        cur = "hand2" if any(t in handlers for t in tags) else ""
        if cur != cv.cget("cursor"): cv.config(cursor=cur); hov["n"] += 1
        ctrl = any(t.startswith(CTRL_TAGS) for t in tags)     # switches, slider, buttons, gear, menu
        tg = None if (ctrl or hov.get("down")) else next((t for t in sorted(tags) if tips.get(t)), None)
        if tg != hov["tip"]:
            hov["tip"] = tg; hide_tip()
            if tg: show_tip_later(tg)
    root._hov = hov                                   # (tests)
    CTRL_TAGS = ("rev", "chg", "fade", "en", "boss", "gear", "upd", "m_", "plh", "menubg", "spot")
    def _down(e, v): hov["down"] = v; on_pointer(e)
    cv.bind("<Motion>", on_pointer, add="+"); cv.bind("<Leave>", lambda e: on_pointer(e), add="+")
    cv.bind("<ButtonPress-1>", lambda e: _down(e, True), add="+"); cv.bind("<ButtonRelease-1>", lambda e: _down(e, False), add="+")
    cv.bind("<B1-Motion>", on_pointer, add="+")
    def click(tag, fn):
        handlers[tag] = fn
        if tag in bound: return
        bound.add(tag)
        cv.tag_bind(tag, "<Button-1>", lambda e, t=tag: root.after_idle(lambda: handlers[t]() if t in handlers else None), add="+")

    base = load_config(user=False); user = load_user()
    defaults = base.get("default_playlists") or base.get("playlists", {})
    try: names = json.load(open(NAMES_CACHE, encoding="utf-8"))
    except Exception: names = {}
    state = {"spotify": None, "game": None}
    upd = {"info": None, "phase": "idle", "pct": 0, "msg": ""}   # update pill state
    if "--updated" in sys.argv:                                  # just relaunched by the silent upgrade
        upd.update(phase="done", msg="Updated to %s" % VERSION)
    ui_q = []
    def post(fn): ui_q.append(fn)                 # called from worker threads

    def cur(): return apply_user(load_config(user=False), user)
    def set_user(k, v): user[k] = v; save_user(user); draw()

    def toggle(x, y, on, tag, w=44, h=24):
        rr(x, y, x + w, y + h, h / 2, C["acc"] if on else C["off"], tag=tag)
        cx = x + w - h / 2 if on else x + h / 2
        oval_(P(cx - h/2 + 3, y + 3, cx + h/2 - 3, y + h - 3), fill="white", outline="", tags=tag)

    def icon(i, cx, cy, c):
        if i == 0:
            oval_(P(cx-8, cy-8, cx+8, cy+8), fill=c, outline=""); oval_(P(cx-3, cy-11, cx+11, cy+3), fill=C["ib"], outline="")
        elif i == 1:
            cv.create_polygon(P(cx-9, cy-1, cx, cy-9, cx+9, cy-1), fill=c); cv.create_rectangle(*P(cx-6, cy-1, cx+6, cy+8), fill=c, outline="")
        elif i == 2:
            cv.create_rectangle(*P(cx-8, cy-3, cx+8, cy+9), fill=c, outline="")
            for k in (-8, -2, 4): cv.create_rectangle(*P(cx+k, cy-8, cx+k+4, cy-3), fill=c, outline="")
        else:
            cv.create_polygon(P(cx-9, cy+6, cx-9, cy-6, cx-4, cy, cx, cy-9, cx+4, cy, cx+9, cy-6, cx+9, cy+6), fill=c)

    def pl_name(uri):
        pid = uri.split(":")[-1]
        return names.get(pid) or "Playlist"

    covers = {}; cover_cache = {}
    def cover_img(path):
        """Rounded, anti-aliased 30 px thumbnail of a cached cover file (None if missing/broken)."""
        if not path or not os.path.exists(path): return None
        k = (path, os.path.getmtime(path))
        if k not in cover_cache:
            try:
                px = int(round(30 * S)); Q = 4
                im = Image.open(path).convert("RGB").resize((px, px), Image.LANCZOS)
                m = Image.new("L", (px * Q, px * Q), 0)
                ImageDraw.Draw(m).rounded_rectangle([0, 0, px * Q - 1, px * Q - 1], 6 * S * Q, fill=255)
                im.putalpha(m.resize((px, px), Image.LANCZOS)); cover_cache[k] = ImageTk.PhotoImage(im)
            except Exception as e:
                log("Cover image: %r" % e); cover_cache[k] = None
        return cover_cache[k]
    tips, tipbound = {}, set()
    tipw = tk.Toplevel(root); tipw.withdraw(); tipw.overrideredirect(True); tipw.configure(bg=C["line"])
    tipl = tk.Label(tipw, text="", bg=C["line"], fg=C["tx"], font=F(10), padx=6, pady=2, wraplength=int(260 * S), justify="left"); tipl.pack()
    tipst = {"tag": None, "job": None, "shown": False}
    def hide_tip(_=None):
        if tipst["job"]: root.after_cancel(tipst["job"]); tipst["job"] = None
        tipst["tag"] = None
        if tipst["shown"]:
            tipst["shown"] = False
            try: tipw.withdraw()
            except tk.TclError: pass
    def tip(tag, msg): tips[tag] = msg              # shown by on_pointer after a short delay
    def show_tip_later(tag):
        tipst["tag"] = tag
        def show():
            tipst["job"] = None
            if tipst["tag"] != tag or not tips.get(tag): return
            if not tipw.winfo_exists(): return
            tipl.config(text=tips[tag]); x, y = root.winfo_pointerxy()
            tipw.geometry("+%d+%d" % (x + 10, y + 14)); tipw.deiconify(); tipw.lift(); tipst["shown"] = True
        tipst["job"] = root.after(300, show)

    def draw():
        cv.delete("all"); handlers.clear(); cfg = cur(); en = bool(cfg.get("enabled", True))
        # header: logo, title + subtitle, version pill, update pill, gear
        cv.create_image(*P(M, 14), image=logo, anchor="nw")
        text(M + 44, 30, "AoE4 Spotify", 19, b=True)
        tw = tkfont.Font(font=F(19, True)).measure("AoE4 Spotify") / S
        px = M + 44 + tw + 8
        rr(px, 21, px + 44, 39, 9, C["card"]); text(px + 22, 30, "v" + VERSION, 10, C["mu"], anchor="center")
        px += 4
        px += 48
        ph = upd["phase"]
        if ph != "idle":
            col = C["red"] if ph == "error" else C["acc"]
            lab = {"avail": "\u2193 Update %s" % (upd["info"] or {}).get("version", ""), "dl": "Downloading %d%%" % upd["pct"],
                   "run": "Installing…", "error": upd["msg"] or "Update failed", "done": upd["msg"]}[ph]
            pw = tkfont.Font(font=F(10, True)).measure(lab) / S + 20
            rr(px, 21, px + pw, 39, 9, "#183d26" if col == C["acc"] else "#3d1a1a", col, "upd")
            text(px + pw / 2, 30, lab, 10, col, True, "center", "upd")
            if ph in ("avail", "error") and upd["info"]: click("upd", start_update)
        gx = R_ - 32
        rr(gx, 14, R_, 46, 10, "#2a2a2a", tag="gear"); cv.create_image(*P(gx + 16, 30), image=gear_img[ui.get("menu", False)], anchor="center", tags="gear")
        if upd["info"] and ph in ("avail", "error"): oval_(P(R_ - 8, 10, R_ + 2, 20), fill=C["acc"], outline=C["bg"], width=2 * S, tags="gear")
        click("gear", lambda: (ui.update(menu=not ui.get("menu")), draw()))
        cv.create_line(*P(M, 62, R_, 62), fill=C["line"])

        # enabled (power icon vertically centered on the card)
        rr(M, 72, R_, 120, 12, C["card"], tag="encard"); cy = 96
        cv.create_image(*P(M + 24, cy), image=power_img, anchor="center", tags="encard")
        text(M + 50, cy, "Enabled", 16, b=True, tag="encard"); toggle(R_ - 12 - 52, cy - 14, en, "en", 52, 28)
        click("en", lambda: (set_user("enabled", not en), threading.Thread(target=music_sync, args=(not en,), daemon=True).start()))
        tip("encard", "Runs automatically when you launch AoE4 from Steam and mutes the game's own music. You don't need this window open." if en else "Off: music won't switch when you play, and the game's music is back on.")
        # status chips: Spotify (clickable -> log in) and Game
        cw = (W - 2 * M - 10) / 2; x = M; sp_ok = state["spotify"]
        rr(x, 130, x + cw, 162, 16, "#242424", "#3a3a3a", "spot")
        oval_(P(x+14, 141, x+24, 151), fill=C["acc"] if sp_ok else (C["org"] if sp_ok is False else C["idle"]), outline="", tags="spot")
        text(x + 32, 146, "Spotify", 12, C["mu"], tag="spot")
        if sp_ok:
            text(x + cw - 26, 146, "Connected", 12, C["acc"], True, "e", "spot"); chev_right(x + cw - 16, 146, C["mu"], "spot", 12)
        elif sp_ok is False:
            rr(x + cw - 86, 136, x + cw - 8, 156, 10, "#4a3216", C["org"], "spot"); text(x + cw - 52, 146, "Log in", 11, C["org"], True, "center", "spot"); chev_right(x + cw - 22, 146, C["org"], "spot", 11)
        else: text(x + cw - 14, 146, "...", 12, C["mu"], True, "e", "spot")
        click("spot", login); tip("spot", "Log in to Spotify" if not sp_ok else "Log in again")
        x = M + cw + 10; gv = state["game"]; gc = C["acc"] if gv else C["idle"]
        rr(x, 130, x + cw, 162, 16, C["card"])
        oval_(P(x+14, 141, x+24, 151), fill=gc, outline=""); text(x + 32, 146, "Game", 12, C["mu"])
        text(x + cw - 14, 146, "..." if gv is None else ("Running" if gv else "Not running"), 12, gc, True, "e")
        # collapsible Playlists section (collapsed by default)
        rr(M, 172, R_, 208, 10, C["card"], tag="plh")
        text(M + 16, 190, "Playlists", 13, b=True, tag="plh")
        cv.create_image(*P(R_ - 18, 190), image=chev_up if ui["open"] else chev_down, anchor="center", tags="plh")
        click("plh", lambda: (ui.update(open=not ui["open"]), draw()))
        X = M + 22                                         # age rows sit indented under the Playlists header
        for i, (k, lab) in enumerate(AGES if ui["open"] else []):
            rx = R_ - 12 - 30; y = 216 + i * 50; uri = cfg["playlists"].get(k, ""); is_def = uri == defaults.get(k)
            rr(X, y, R_, y + 42, 10, C["card"]); pid = uri.split(":")[-1]
            cimg = cover_img(covers.get(pid) or (cover_file(pid) if pid else None))
            if cimg:                                       # playlist cover: click = open in Spotify
                cv.create_image(*P(X + 24, y + 21), image=cimg, anchor="center", tags="cov%d" % i)
                click("cov%d" % i, lambda pid=pid: open_playlist(pid)); tip("cov%d" % i, "Open in Spotify")
            else:
                rr(X + 9, y + 6, X + 39, y + 36, 6, C["ib"]); icon(i, X + 24, y + 21, C["acc"])
            rr(X + 38, y + 7, rx - 76, y + 35, 8, C["card"], tag="opn%d" % i)          # hit area (gaps between texts)
            rr(X + 38, y + 7, rx - 76, y + 35, 8, "#2c2c2c", tag="hl%d" % i); cv.itemconfigure("hl%d" % i, state="hidden")
            text(X + 48, y + 21, lab, 13, b=True, tag="opn%d" % i)
            oval_(P(X+118, y+17, X+126, y+25), fill=C["acc"] if uri else C["idle"], outline="", tags="opn%d" % i)
            nm = pl_name(uri); nm = nm if len(nm) <= 15 else nm[:14] + "\u2026"
            text(X + 132, y + 21, nm, 12, C["mu"], tag="opn%d" % i)
            if pid:
                click("opn%d" % i, lambda pid=pid: open_playlist(pid)); tip("opn%d" % i, "Open in Spotify"); hover_hl(i)
            rx = R_ - 12 - 30
            rr(rx - 70, y + 9, rx - 8, y + 33, 12, C["card"], C["acc"], ("chg%d" % i, "chgx")); text(rx - 39, y + 21, "Change", 10, C["acc"], True, "center", ("chg%d" % i, "chgx"))
            rc = C["dis"] if is_def else C["mu"]
            rr(rx, y + 9, rx + 30, y + 33, 12, C["card"], rc, "rev%d" % i); undo_icon(rx + 15, y + 21, rc, "rev%d" % i)
            click("chg%d" % i, lambda k=k, lab=lab: change(k, lab))
            if not is_def: click("rev%d" % i, lambda k=k: revert(k))
            tip("rev%d" % i, "Revert" if not is_def else "Revert (already default)")
        # Age 4 Intro theme
        base = 418 if ui["open"] else 218
        Hn = base + 56 + 46 + M
        if int(cv.cget("height")) != int(Hn * S): cv.config(height=int(Hn * S))
        y = base; bon = bool((cfg.get("boss_intro") or {}).get("enabled", True))
        rr(M, y, R_, y + 46, 10, C["card"], tag="intro"); icon(3, M + 24, y + 23, C["acc"])
        text(M + 46, y + 23, "Age Intros", 13, b=True, tag="intro")
        sx = M + 46 + tkfont.Font(font=F(13, True)).measure("Age Intros") / S + 14
        ion = cfg.get("intros") or {}
        for j, (a_, rn) in enumerate(zip(INTRO_AGES, ("I", "II", "III", "IV"))):   # one pip per age, lit when its intro is on
            lit = bool((ion.get(a_) or {}).get("enabled")) and bon; px_ = sx + 11 + j * 25
            oval_(P(px_ - 10, y + 13, px_ + 10, y + 33), fill=C["acc"] if lit else "#2a2a2a", outline="" if lit else "#3a3a3a", tags="intro")
            text(px_, y + 23, rn, 9, "#121212" if lit else C["mu"], True, "center", "intro")
        toggle(R_ - 30 - 44, y + 11, bon, "boss")
        chev_right(R_ - 15, y + 23, C["mu"], "intro", 16)
        click("intro", open_editor); tip("intro", "Intro song per age and civ")
        click("boss", lambda: set_user("boss_intro_enabled", not bon))
        # fade
        y = base + 56; fv = float(cfg.get("fade_seconds", 2))
        rr(M, y, R_, y + 46, 10, C["card"])
        cv.create_image(*P(M + 24, y + 23), image=fade_img, anchor="center")
        text(M + 46, y + 23, "Fade", 13, b=True)
        x0, x1 = FX0, FX1; xv = x0 + (x1 - x0) * fv / 5
        rr(x0, y + 20, x1, y + 26, 3, C["off"], tag="fade"); rr(x0, y + 20, max(xv, x0 + 6), y + 26, 3, C["acc"], tag="fade")
        oval_(P(xv-9, y+14, xv+9, y+32), fill="white", outline=C["acc"], width=2*S, tags="fade")
        text(R_ - 12 - 30 - 10, y + 23, ("%.1fs" % fv) if fv else "Off", 12, C["acc"], True, "e")
        fdef = float(base_cfg.get("fade_seconds", 2)); f_is_def = abs(fv - fdef) < 1e-6
        rc = C["dis"] if f_is_def else C["mu"]          # revert to default fade, right-aligned like playlist rows
        rx = R_ - 12 - 30
        rr(rx, y + 11, rx + 30, y + 35, 12, C["card"], rc, "revf"); undo_icon(rx + 15, y + 23, rc, "revf")
        if not f_is_def: click("revf", lambda: (user.pop("fade_seconds", None), save_user(user), draw()))
        tip("revf", "Revert" if not f_is_def else "Revert (already default)")
        # gear menu (drawn on top, with a dim layer that closes it)
        if ui.get("menu"):
            cv.create_image(0, 0, anchor="nw", tags="menubg", image=_img(("dim", Hn), int(W * S), int(Hn * S),
                            lambda d, Q: d.rectangle([0, 0, W * S * Q, Hn * S * Q], fill=(0, 0, 0, 90))))
            click("menubg", lambda: (ui.update(menu=False), draw()))
            rr(gx, 14, R_, 46, 10, "#2a2a2a", tag="gear"); cv.create_image(*P(gx + 16, 30), image=gear_img[True], anchor="center", tags="gear")
            mx0, my0 = R_ - 158, 52
            mx0 = R_ - 190
            rr(mx0, my0, R_, my0 + 116, 10, "#262626", "#3a3a3a")
            rr(mx0 + 6, my0 + 6, R_ - 6, my0 + 38, 7, "#262626", tag="m_chk"); text(mx0 + 20, my0 + 22, "\u21bb  Check for updates", 12, C["tx"], tag="m_chk")
            rr(mx0 + 6, my0 + 38, R_ - 6, my0 + 70, 7, "#262626", tag="m_log"); text(mx0 + 20, my0 + 54, "\u2630  Open log", 12, C["tx"], tag="m_log")
            cv.create_line(*P(mx0 + 10, my0 + 76, R_ - 10, my0 + 76), fill="#3a3a3a")
            rr(mx0 + 6, my0 + 80, R_ - 6, my0 + 110, 7, "#262626", tag="m_un"); text(mx0 + 20, my0 + 95, "\u2715  Uninstall", 12, C["red"], True, tag="m_un")
            click("m_chk", lambda: (ui.update(menu=False), draw(), check_now()))
            click("m_log", lambda: (ui.update(menu=False), draw(), open_log()))
            click("m_un", lambda: (ui.update(menu=False), draw(), uninstall()))

    FX0, FX1 = M + 94, W - M - 12 - 30 - 62          # fade slider track (leaves room for value + revert)
    base_cfg = load_config(user=False)
    drag = {"on": False}
    def slide(e, save=False):
        if not drag["on"]: return
        v = round(max(0, min(5, (e.x / S - FX0) / (FX1 - FX0) * 5)) * 2) / 2
        if save: drag["on"] = False; set_user("fade_seconds", v)
        elif v != user.get("fade_seconds"): user["fade_seconds"] = v; draw()
    cv.tag_bind("fade", "<ButtonPress-1>", lambda e: (drag.update(on=True), root.after_idle(lambda: slide(e))))
    cv.bind("<B1-Motion>", lambda e: root.after_idle(lambda: slide(e)))
    cv.bind("<ButtonRelease-1>", lambda e: root.after_idle(lambda: slide(e, True)))

    def dialog(title, prompt):
        d = tk.Toplevel(root); dark_window(d, C["card"]); d.title(title); d.transient(root); d.resizable(False, False)
        tk.Label(d, text=prompt, bg=C["card"], fg=C["tx"], font=F(12, True), justify="left").pack(padx=16, pady=(14, 6), anchor="w")
        e = tk.Entry(d, width=52, bg=C["ib"], fg=C["tx"], insertbackground=C["tx"], relief="flat", font=F(12)); e.pack(padx=16, ipady=5)
        err = tk.Label(d, text="", bg=C["card"], fg=C["red"], font=F(10)); err.pack(padx=16, anchor="w")
        res = {}
        def ok(_=None):
            m = RE_PLAYLIST.search(e.get().strip())
            if not m: err.config(text="That's not a Spotify playlist link (open.spotify.com/playlist/...)"); return
            res["id"] = m.group(1); d.destroy()
        row = tk.Frame(d, bg=C["card"]); row.pack(padx=16, pady=(4, 14), anchor="e")
        tk.Button(row, text="Cancel", command=d.destroy, bg=C["ib"], fg=C["tx"], relief="flat", font=F(11), padx=12).pack(side="left", padx=6)
        tk.Button(row, text="Save", command=ok, bg=C["acc"], fg="black", relief="flat", font=F(11, True), padx=14).pack(side="left")
        reveal(d, fade=False, over=root); d.grab_set(); e.bind("<Return>", ok); e.focus_set(); root.wait_window(d)
        return res.get("id")

    def change(k, lab):
        pid = dialog("Change playlist", "Paste a Spotify playlist link for %s Age:" % lab)
        if not pid: return
        pls = dict(user.get("playlists") or {}); pls[k] = "spotify:playlist:" + pid
        set_user("playlists", pls); fetch_names()

    def revert(k):
        pls = dict(user.get("playlists") or {}); pls.pop(k, None); set_user("playlists", pls); fetch_names()

    def show_gtg():                                    # access just started working: no new login needed
        def go():
            st = setup_status(Spotify(load_config())); refresh_now(); fetch_names()
            post(lambda: good_to_go(st, parent=root, on_open_panel=lambda: None, on_retry=login,
                                    fix=lambda: with_steam_closed(set_launch_option)))
        threading.Thread(target=go, daemon=True).start()
    def pending_access():                              # asked for access earlier: check once on start
        if not load_user_settings().get("access_pending"): return
        def go():
            r = access_status(Spotify(load_config()))
            if r == "ok":
                u = load_user_settings(); u.pop("access_pending", None); save_user(u); show_gtg()
            elif r == "blocked": post(lambda: access_dialog(root, on_allowed=show_gtg))
        threading.Thread(target=go, daemon=True).start()
    def login():
        def go():
            sp = Spotify(load_config())
            try: sp.login()
            except BaseException as e: log("Login failed: %r" % e); sp.tok = None
            if access_status(sp) == "blocked":
                post(lambda: access_dialog(root, on_allowed=lambda: show_gtg())); return
            st = setup_status(sp)
            refresh_now(); fetch_names()
            post(lambda: good_to_go(st, parent=root, on_open_panel=lambda: None, on_retry=login,
                                    fix=lambda: with_steam_closed(set_launch_option)))
        threading.Thread(target=go, daemon=True).start()

    art = Art(root, S)
    def open_editor(): pool_editor(root, user, lambda: (save_user(user), draw()))
    pending_access()

    def start_update():
        info = upd["info"]
        if not info or upd["phase"] in ("dl", "run"): return
        upd.update(phase="dl", pct=0); draw()
        dest = os.path.join(os.environ.get("TEMP") or DATA, "AoE4 Spotify Setup %s.exe" % info["version"])
        def go():
            try:
                download_update(info, dest, lambda f: (upd.update(pct=int(f * 100)), post(draw)) if int(f * 100) != upd["pct"] else None)
                upd.update(phase="run"); post(draw)
                post(lambda: (run_update(dest), root.after(400, root.destroy)))   # Setup closes us anyway
            except Exception as e:
                log("Update failed: %r" % e); upd.update(phase="error", msg="Update failed \u2013 retry"); post(draw)
        threading.Thread(target=go, daemon=True).start()

    def check_updates():
        def go():
            info = check_update()
            if info and upd["phase"] in ("idle", "done"):
                upd.update(info=info, phase="avail"); post(draw)
                if os.environ.get("AOE4SPOTIFY_TEST_AUTOUPDATE") == "1": post(start_update)   # testing only
        threading.Thread(target=go, daemon=True).start()

    def check_now():
        """Gear menu 'Check for updates': pill shows the result; 'Up to date' / 'Couldn't check' fade after ~2s."""
        if upd["phase"] in ("dl", "run"): return
        upd.update(phase="done", msg="Checking\u2026"); draw()
        def go():
            try: info = check_update(report=True); res = ("avail", "", info) if info else ("done", "Up to date", None)
            except Exception: res = ("error", "Couldn't check", None)
            def show():
                if res[0] == "avail": upd.update(phase="avail", msg="", info=res[2])
                else: upd.update(phase=res[0], msg=res[1], info=None)
                draw()
                if res[0] != "avail":
                    root.after(2000, lambda: upd["phase"] in ("done", "error") and not upd["info"] and (upd.update(phase="idle", msg=""), draw()))
            post(show)
        threading.Thread(target=go, daemon=True).start()

    def open_log():
        if not os.path.exists(LOGFILE): open(LOGFILE, "a").close()
        os.startfile(LOGFILE)

    def uninstall():
        from tkinter import messagebox
        un = os.path.join(HERE, "unins000.exe")
        if not os.path.exists(un): messagebox.showinfo("Uninstall", "Uninstaller not found (not installed?)."); return
        steam = " Steam will close for a moment and reopen by itself." if steam_running() else ""
        if messagebox.askyesno("Uninstall AoE4 Spotify?", "Removes the app, its shortcuts and settings, and puts the game's launch options and music volume back." + steam):
            subprocess.Popen([un, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], env=child_env()); root.destroy()   # one click: no further boxes

    def fetch_names():
        def go():
            try:
                cfg = load_config(); sp = Spotify(cfg)
                if not sp.tok: return
                changed = False
                for uri in set(cfg["playlists"].values()) | set(defaults.values()):
                    pid = uri.split(":")[-1]
                    if not pid: continue
                    nm, path = update_cover(sp, pid, int(round(30 * S * 1.5)))
                    if nm and names.get(pid) != nm: names[pid] = nm; changed = True
                    if path and covers.get(pid) != path: covers[pid] = path; changed = True
                if changed:
                    os.makedirs(DATA, exist_ok=True)
                    json.dump(names, open(NAMES_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                    post(draw)
            except Exception as e: log("Playlist names: %r" % e)
        threading.Thread(target=go, daemon=True).start()

    _draw = draw
    def draw():                                    # full redraw (state changes only, never on hover)
        t0 = time.perf_counter(); _draw(); ui["dt"] = time.perf_counter() - t0
        tg = hov["tip"]; on_pointer(force=True)      # re-apply hover state to the new items
        if tg and hov["tip"] == tg and not tipst["shown"]: pass
    def refresh_now():
        def go():
            s = {"spotify": os.path.exists(TOKEN), "game": aoe_running()}
            if s != state: state.update(s); post(draw)
        threading.Thread(target=go, daemon=True).start()
    def tick(): refresh_now(); root.after(3000, tick)
    def pump():                                   # run UI updates queued by worker threads (Tk isn't thread-safe)
        while ui_q:
            try: ui_q.pop(0)()
            except Exception as e: log("Panel update failed: %r" % e)
        root.after(150, pump)

    if upd["phase"] == "done": root.after(6000, lambda: (upd.update(phase="idle") if upd["phase"] == "done" else None, draw()))
    draw(); reveal(root); note_window("panel", root); pump(); tick(); fetch_names(); check_updates(); root.mainloop()

if __name__ == "__main__":
    try: main()
    except Exception as e:
        log("FATAL: %r" % e); raise
