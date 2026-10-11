"""AoE4 -> Spotify age playlist switcher. Python stdlib only. MIT licensed (see LICENSE).

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
DATA = os.path.join(os.environ.get("APPDATA") or HERE, "AoE4Spotify")
os.makedirs(DATA, exist_ok=True)
TOKEN = os.path.join(DATA, "token.json")   # private Spotify login token; never shared or packaged
LOGFILE = os.path.join(DATA, "aoe4_spotify.log")
REDIRECT = "http://127.0.0.1:8888/callback"
SCOPES = "user-modify-playback-state user-read-playback-state"
DEFAULT_LOG = os.path.join(os.path.expanduser("~"), "Documents", "My Games", "Age of Empires IV", "warnings.log")

def log(msg):
    line = time.strftime("%H:%M:%S ") + msg
    try: print(line, flush=True)
    except Exception: pass  # pythonw has no console
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass

def load_config():
    with open(CONFIG, encoding="utf-8") as f: return json.load(f)

# ---------------------------------------------------------------- Spotify
class Spotify:
    def __init__(self, cfg):
        self.cid = cfg["client_id"].strip()
        self.device_id = (cfg.get("device_id") or "").strip() or None
        self.tok = None
        self.shuffle = bool(cfg.get("shuffle", True))
        self.repeat = bool(cfg.get("repeat", True))
        if os.path.exists(TOKEN):
            with open(TOKEN, encoding="utf-8") as f: self.tok = json.load(f)

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
        srv = http.server.HTTPServer(("127.0.0.1", 8888), H)
        url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
            "client_id": self.cid, "response_type": "code", "redirect_uri": REDIRECT,
            "code_challenge_method": "S256", "code_challenge": challenge,
            "scope": SCOPES, "state": state})
        log("Opening browser for Spotify login...")
        webbrowser.open(url)
        while "code" not in result and "error" not in result:
            srv.handle_request()
        srv.server_close()
        if result.get("error") or result.get("state") != state:
            raise SystemExit("Spotify login failed: %s" % result)
        self._save(self._token_req({"grant_type": "authorization_code", "code": result["code"],
            "redirect_uri": REDIRECT, "client_id": self.cid, "code_verifier": verifier}))
        log("Spotify login OK, token cached in token.json")

    def access(self):
        if not self.tok: self.login()
        if time.time() > self.tok.get("expires_at", 0):
            self._save(self._token_req({"grant_type": "refresh_token",
                "refresh_token": self.tok["refresh_token"], "client_id": self.cid}))
        return self.tok["access_token"]

    def _api(self, method, path, body=None):
        req = urllib.request.Request("https://api.spotify.com/v1" + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": "Bearer " + self.access(), "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read(); return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try: return e.code, json.loads(raw)
            except Exception: return e.code, raw.decode(errors="replace")

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

    def _play(self, uri, payload, q):
        code, body = self._api("PUT", "/me/player/play" + q, payload)
        if code == 404:  # no active device: pick the first available one
            _, devs = self._api("GET", "/me/player/devices")
            devs = (devs or {}).get("devices", []) if isinstance(devs, dict) else []
            if not devs:
                log("Spotify: NO ACTIVE DEVICE. Open Spotify (desktop app) and play anything once, then it will work.")
                return False
            self.device_id = devs[0]["id"]
            log("Spotify: no active device, using '%s'" % devs[0]["name"])
            code, body = self._api("PUT", "/me/player/play?device_id=" + self.device_id, payload)
        if code == 403:
            log("Spotify 403: playback control needs Spotify Premium (%s)" % body); return False
        if code not in (200, 202, 204):
            log("Spotify error %s: %s" % (code, body)); return False
        return True

    # ---- fading switch (runs in a background thread)
    def _set_vol(self, v):
        q = "&device_id=" + self.device_id if self.device_id else ""
        code, _ = self._api("PUT", "/me/player/volume?volume_percent=%d%s" % (max(0, min(100, int(v))), q))
        return code in (200, 202, 204)

    def _ramp(self, a, b, secs, gen):
        steps = max(1, int(secs / 0.15))
        for i in range(1, steps + 1):
            if gen != self._gen: return False          # superseded by a newer switch
            if not self._set_vol(a + (b - a) * i / steps): return False
            time.sleep(secs / steps)
        return True

    def switch(self, uri, fade=2.0):
        if not hasattr(self, "_glock"):
            self._glock = threading.Lock(); self._gen = 0; self._orig = None
        with self._glock:
            self._gen += 1; gen = self._gen
            orig = self._orig                          # mid-fade: keep the ORIGINAL volume
            if orig is None and fade > 0:
                code, st = self._api("GET", "/me/player")
                dev = (st or {}).get("device") if isinstance(st, dict) else None
                if code == 200 and dev and dev.get("volume_percent") is not None \
                        and dev.get("supports_volume", True):
                    orig = dev["volume_percent"]
            self._orig = orig
        try:
            if orig is None or fade <= 0:
                return self.play(uri)
            if not self._ramp(orig, 0, fade, gen):
                if gen != self._gen: return False
                log("Spotify: volume control not allowed on this device, switching without fade")
                self._set_vol(orig); return self.play(uri)
            ok = self.play(uri)
            if not self._ramp(0, orig, fade, gen) and gen == self._gen: self._set_vol(orig)
            return ok
        finally:
            with self._glock:
                if gen == self._gen:
                    if self._orig is not None: self._set_vol(self._orig)
                    self._orig = None

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
            self.my_slot = int(m.group(1))
            log("You are lobby slot %s (%s), team %s" % (m.group(1), m.group(5), m.group(4)))
            return
        if RE_REPLAY.search(line) and self.in_match:
            self.replay = True; log("Replay detected - ignoring this match")
            return
        if RE_START.search(line):
            if not self.in_match: self.reset()
            self.resolve_id()
            log("Match started -> Dark Age playlist")
            self.play("dark"); return
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
                    log("YOU are aging up to %s -> %s playlist" % (new, KEY[new])); self.play(KEY[new])
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
                log("YOU reached %s -> %s playlist" % (new, KEY[new])); self.play(KEY[new])

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
    tracker.play = lambda k: None          # catch-up: no Spotify calls
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

def aoe_running():
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq RelicCardinal.exe", "/NH"],
                             capture_output=True, text=True, creationflags=NOWIN).stdout
        return "RelicCardinal.exe" in out
    except Exception:
        return False

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

def steam_path():
    if os.environ.get("AOE4SPOTIFY_STEAM_PATH"): return os.environ["AOE4SPOTIFY_STEAM_PATH"]  # testing only
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
    return sorted(glob.glob(os.path.join(steam_path(), "userdata", "*", "config", "localconfig.vdf")))

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

def remove_old_startup_shortcut():
    lnk = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "AoE4 Spotify.lnk")
    if os.path.exists(lnk): os.remove(lnk); log("Removed old Startup shortcut")

# ---------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if args[:1] == ["--set-launch-option"]: set_launch_option(); return
    if args[:1] == ["--remove-launch-option"]: remove_launch_option(); return
    cfg = load_config()
    if args[:1] == ["--dry-run"]:
        t = Tracker(cfg, lambda k: log("   [dry-run] would play %s: %s" % (k, cfg["playlists"].get(k))))
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
        # Started by hand / installer Finish page: just log in to Spotify, then exit.
        if sp.tok: log("Already logged in to Spotify. Start AoE4 from Steam and the music follows your ages.")
        else: sp.login()
        return
    # Started by Steam with the game command (%command%) as args: start the game first.
    import subprocess
    game_dir = os.path.dirname(args[0]) if os.path.isfile(args[0]) else None
    subprocess.Popen(args, cwd=game_dir)
    log("Started game: %s" % " ".join(args))
    if not single_instance(): log("Another switcher is already running - exiting"); return
    if not sp.tok: sp.login()
    t0 = time.time()
    while not aoe_running():                    # wait for RelicCardinal.exe (max 5 min)
        if time.time() - t0 > 300: log("AoE4 did not start within 5 minutes - exiting"); return
        time.sleep(3)
    log("AoE4 is running")
    def play(k):
        uri = cfg["playlists"].get(k, "")
        if not uri.startswith("spotify:") or "PASTE" in uri: log("No playlist set for %s" % k); return
        threading.Thread(target=sp.switch, args=(uri, float(cfg.get("fade_seconds", 2))), daemon=True).start()
    path = os.path.expandvars(cfg.get("log_path") or DEFAULT_LOG)
    t = Tracker(cfg, play)
    t.crc_dir = os.path.join(os.path.dirname(path), "LogFiles")
    tail(path, t, stop=lambda: not aoe_running())   # returns ~10s after the game closes
    log("AoE4 closed - exiting")
    time.sleep(3)                                     # let a running fade finish

if __name__ == "__main__":
    try: main()
    except Exception as e:
        log("FATAL: %r" % e); raise
