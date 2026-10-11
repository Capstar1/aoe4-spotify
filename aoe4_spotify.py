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
ASSETS = getattr(sys, "_MEIPASS", HERE)     # bundled files (app.ico, gtg_frames/) inside the exe
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
    if isinstance(u.get("fade_seconds"), (int, float)): cfg["fade_seconds"] = max(0.0, min(5.0, float(u["fade_seconds"])))
    if isinstance(u.get("boss_intro_enabled"), bool): cfg.setdefault("boss_intro", {})["enabled"] = u["boss_intro_enabled"]
    return cfg

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
            subprocess.Popen([exe, "--minimized"], creationflags=0x08000000); log("Started Spotify (minimized)"); return True
        if os.path.isdir(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", STORE_APP)):   # Microsoft Store
            subprocess.Popen(["explorer.exe", r"shell:AppsFolder\%s!Spotify" % STORE_APP]); log("Started Spotify (Microsoft Store app)"); return True
        if _spotify_protocol_registered():
            os.startfile("spotify:"); log("Started Spotify via spotify: link"); return True
    except Exception as e:
        log("Could not start Spotify: %r" % e); return False
    log("Spotify desktop app is NOT INSTALLED on this PC - install it from spotify.com to get music.")
    return False

# ---------------------------------------------------------------- Spotify
class Spotify:
    def __init__(self, cfg):
        self.cid = cfg["client_id"].strip()
        self.device_id = (cfg.get("device_id") or "").strip() or None
        self.tok = None
        self.shuffle = bool(cfg.get("shuffle", True))
        self.repeat = bool(cfg.get("repeat", True))
        self._glock = threading.Lock(); self._gen = 0; self._orig = None   # fade/switch state
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
        if not self.tok: self.login()
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
        try:
            req = urllib.request.Request("https://api.spotify.com/v1" + path, method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers={"Authorization": "Bearer " + self.access(), "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
                try: return r.status, (json.loads(raw) if raw else None)
                except ValueError: return r.status, None
        except urllib.error.HTTPError as e:
            if e.code == 401 and _retry and self.tok:          # access token rejected: refresh once
                self.tok["expires_at"] = 0
                return self._api(method, path, body, False)
            raw = e.read()
            try: return e.code, json.loads(raw)
            except Exception: return e.code, raw.decode(errors="replace")
        except (urllib.error.URLError, OSError) as e:
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

    def switch(self, uri, fade=2.0, player=None):
        player = player or self.play
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
                return player(uri)
            if not self._ramp(orig, 0, fade, gen):
                if gen != self._gen: return False
                log("Spotify: volume control not allowed on this device, switching without fade")
                self._set_vol(orig); return player(uri)
            ok = player(uri)
            if not self._ramp(0, orig, fade, gen) and gen == self._gen: self._set_vol(orig)
            return ok
        finally:
            with self._glock:
                if gen == self._gen:
                    if self._orig is not None: self._set_vol(self._orig)
                    self._orig = None

    # ---- Age 4 Intro theme (config key boss_intro): play one track, then the age playlist (runs in a background thread)
    def boss_then(self, track, playlist, fade=2.0):
        if not hasattr(self, "_glock"):
            self._glock = threading.Lock(); self._gen = 0; self._orig = None
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

def pick_boss_track(cfg, civ):
    b = cfg.get("boss_intro") or {}
    pool = [u for u in ((b.get("pools") or {}).get(civ) or b.get("default") or []) if u.startswith("spotify:track:")]
    if not pool: return None
    try: state = json.load(open(BOSS_STATE, encoding="utf-8"))
    except Exception: state = {}
    choices = [u for u in pool if u != state.get(civ)] or pool      # never the same as last time
    uri = random.choice(choices)
    state[civ] = uri
    try: json.dump(state, open(BOSS_STATE, "w", encoding="utf-8"), indent=1)
    except Exception as e: log("Could not save boss state: %r" % e)
    return uri

def boss_age(cfg, key):
    b = cfg.get("boss_intro") or {}
    return bool(b.get("enabled", True)) and key in (b.get("ages") or ["imperial"])

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
        out = subprocess.run(["tasklist", "/fi", "imagename eq steam.exe", "/nh"], capture_output=True,
                             text=True, creationflags=0x08000000).stdout
        return "steam.exe" in out.lower()
    except Exception: return False

def steam_exe():
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
        if exe: subprocess.Popen([exe, "-shutdown"])
        for _ in range(30):
            time.sleep(1)
            if not steam_running(): break
        else:
            log("Steam did not close in 30s - force closing")
            subprocess.run(["taskkill", "/im", "steam.exe", "/f"], capture_output=True, creationflags=0x08000000)
            time.sleep(2)
    try: fn()
    finally:
        if was and exe: subprocess.Popen([exe, "-silent"]); log("Reopened Steam")

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
    subprocess.Popen(cmd)

# ---------------------------------------------------------------- "You're good to go" window
def good_to_go(status, parent=None, on_open_panel=None, on_retry=None, fix=None):
    """Panel-style result window after Spotify login. status from setup_status().
    parent: an existing Tk root (from the panel) or None (own window, blocks until closed)."""
    import tkinter as tk
    from PIL import Image, ImageDraw, ImageTk
    try: import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", acc="#1DB954", red="#e5484d", warn="#f5a524")
    win = tk.Toplevel(parent) if parent else tk.Tk()
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
        cv.tag_bind(tag, "<Enter>", lambda e: cv.config(cursor="hand2")); cv.tag_bind(tag, "<Leave>", lambda e: cv.config(cursor=""))
    def close():
        try: win.destroy()
        except tk.TclError: pass
    # Animated avatar: bundled face frames (gtg_frames/), soft round mask, thin green ring, check badge.
    R = 62                                        # avatar radius
    faces = []
    def load_faces():
        from PIL import ImageFilter, ImageChops
        D = int(2 * R * S)
        m = Image.new("L", (D * 4, D * 4), 0); ImageDraw.Draw(m).ellipse([0, 0, D * 4 - 1, D * 4 - 1], fill=255)
        m = m.resize((D, D), Image.LANCZOS)
        fade = Image.new("L", (D, D), 0); e = max(2, int(5 * S)); ImageDraw.Draw(fade).ellipse([e, e, D - e, D - e], fill=255)
        mask = ImageChops.multiply(m, fade.filter(ImageFilter.GaussianBlur(4.5 * S)))
        files = sorted(glob.glob(os.path.join(ASSETS, "gtg_frames", "face_*.jpg")), key=lambda p: int(re.findall(r"\d+", os.path.basename(p))[0]))
        frames = []
        for p in files:
            try: f = Image.open(p).convert("RGB").resize((D, D), Image.LANCZOS)
            except Exception as ex: log("Face frame %s: %r" % (p, ex)); continue
            im = Image.new("RGB", (D, D), C["bg"]); im.paste(f, (0, 0), mask)
            frames.append(ImageTk.PhotoImage(im, master=win))
        return frames + frames[-2:0:-1]          # ping-pong loop
    anim = {"i": 0}
    def animate():
        if not win.winfo_exists(): return
        it = cv.find_withtag("avatar")
        if it and faces:
            anim["i"] = (anim["i"] + 1) % len(faces); cv.itemconfig(it[0], image=faces[anim["i"]])
        win.after(90, animate)
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
    def badge(d, k):                              # same app badge as app.ico / the panel
        m = 32 * k; d.ellipse([0, 0, m - 1, m - 1], fill=C["acc"])
        for o, hh in ((-0.2, 0.2), (0, 0.3), (0.2, 0.2)):
            x = m * (0.5 + o); d.rounded_rectangle([x - m*.05, m*(.5-hh), x + m*.05, m*(.5+hh)], radius=m*.05, fill="#121212")
    set_app_icon(win)
    faces.extend(load_faces())
    draw(); animate()
    win._gtg = {"cv": cv, "status": status, "actions": actions, "draw": draw}   # for tests
    win.lift(); win.attributes("-topmost", True); win.after(300, lambda: win.attributes("-topmost", False))
    if parent is None: win.mainloop()
    return win

def set_app_icon(win):
    """Title-bar icon = app.ico (bundled), so it matches the exe and shortcuts."""
    ico = os.path.join(ASSETS, "app.ico")
    try:
        if os.path.exists(ico): win.iconbitmap(ico); win.iconbitmap(default=ico); return
    except Exception as e: log("Icon: %r" % e)

def login_flow(cfg):
    """No-arg start (installer Finish page): log in if needed, then show the result window."""
    if os.environ.get("AOE4SPOTIFY_GTG_DEMO"):    # testing/screenshots only: show the window with sample data
        good_to_go({"ok": True, "name": "Capstar", "steam": True, "spotify_app": True}); return
    sp = Spotify(cfg)
    while True:
        if not sp.tok:
            try: sp.login()
            except BaseException as e: log("Login failed: %r" % e)
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
    if args[:1] == ["--set-launch-option"]: with_steam_closed(set_launch_option); return   # no-op close if Setup already closed Steam
    if args[:1] == ["--remove-launch-option"]: remove_launch_option(); return
    if args[:1] == ["--panel"]: panel(); return
    cfg = load_config()
    if args[:1] == ["--dry-run"]:
        t = Tracker(cfg, lambda k, civ=None: log("   [dry-run] would play %s%s: %s" % (k, (" (Age 4 Intro theme for %s: %s)" % (civ, pick_boss_track(cfg, civ))) if civ and boss_age(cfg, k) else "", cfg["playlists"].get(k))))
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
    subprocess.Popen(args, cwd=game_dir)
    log("Started game: %s" % " ".join(args))
    if not cfg.get("enabled", True): log("Disabled in the control panel - game started, doing nothing else"); return
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
        track = pick_boss_track(cfg, civ) if civ and boss_age(cfg, k) else None
        if track:
            log("Age 4 Intro theme for %s: %s" % (civ, track))
            threading.Thread(target=sp.boss_then, args=(track, uri, fade), daemon=True).start()
        else:
            threading.Thread(target=sp.switch, args=(uri, fade), daemon=True).start()
    path = os.path.expandvars(cfg.get("log_path") or DEFAULT_LOG)
    t = Tracker(cfg, play)
    t.crc_dir = os.path.join(os.path.dirname(path), "LogFiles")
    tail(path, t, stop=lambda: not aoe_running())   # returns ~10s after the game closes
    log("AoE4 closed - exiting")
    time.sleep(3)                                     # let a running fade finish

# ---------------------------------------------------------------- control panel (--panel)
# A small settings window. Settings are saved to %APPDATA%/AoE4Spotify/config.json and
# overlay the install config (which is never edited).
RELEASES_URL = "https://github.com/Capstar1/aoe4-spotify/releases"
NAMES_CACHE = os.path.join(DATA, "playlist_names.json")
AGES = [("dark", "Dark"), ("feudal", "Feudal"), ("castle", "Castle"), ("imperial", "Imperial")]
RE_PLAYLIST = re.compile(r"(?:open\.spotify\.com/(?:intl-[a-z]+/)?playlist/|spotify:playlist:)([A-Za-z0-9]{22})")

def load_user(): return load_user_settings()

def save_user(u):
    tmp = USER_CONFIG + ".tmp"                      # write-then-rename: never leaves a half-written file
    with open(tmp, "w", encoding="utf-8") as f: json.dump(u, f, indent=2)
    os.replace(tmp, USER_CONFIG)

def panel():
    import tkinter as tk, subprocess, webbrowser as wb
    try: import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception: pass
    C = dict(bg="#121212", card="#1f1f1f", tx="#f2f2f2", mu="#9a9a9a", off="#3a3a3a", line="#2a2a2a",
             ib="#2a2a2a", idle="#8a8a8a", red="#e5484d", acc="#1DB954", dis="#555555")
    root = tk.Tk(); root.title("AoE4 Spotify"); root.configure(bg=C["bg"]); root.resizable(False, False)
    S = root.winfo_fpixels("1i") / 96.0
    W, H = 520, 650
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
    def badge(px):
        im = Image.new("RGBA", (px * 4, px * 4), (0, 0, 0, 0)); d = ImageDraw.Draw(im); m = px * 4
        d.ellipse([0, 0, m - 1, m - 1], fill=C["acc"])
        for k, hh in ((-0.2, 0.2), (0, 0.3), (0.2, 0.2)):
            x = m * (0.5 + k); d.rounded_rectangle([x - m*0.05, m*(0.5-hh), x + m*0.05, m*(0.5+hh)], radius=m*0.05, fill=C["bg"])
        return im.resize((px, px), Image.LANCZOS)
    logo = ImageTk.PhotoImage(badge(int(32 * S)))
    def _icon(px, paint):
        Q = 4; im = Image.new("RGBA", (px * Q, px * Q), (0, 0, 0, 0)); paint(ImageDraw.Draw(im), px * Q, Q)
        return ImageTk.PhotoImage(im.resize((px, px), Image.LANCZOS))
    def _power(d, m, Q):
        lw = int(3 * S * Q); d.arc([m*0.12, m*0.16, m*0.88, m*0.92], start=-60, end=240, fill=C["acc"], width=lw)
        d.rounded_rectangle([m/2 - lw/2, m*0.04, m/2 + lw/2, m*0.5], radius=lw/2, fill=C["acc"])
    def _fade(d, m, Q):
        lw = int(2 * S * Q)
        for k in range(3): d.arc([m*(0.0+k*0.18), m*0.12, m*(0.6+k*0.18), m*0.88], start=-60, end=60, fill=C["acc"], width=lw)
    def _chev(up):
        def p(d, m, Q):
            lw = int(2.4 * S * Q); a, b = (0.62, 0.36) if up else (0.38, 0.64)
            d.line([(m*0.22, m*a), (m*0.5, m*b), (m*0.78, m*a)], fill=C["mu"], width=lw, joint="curve")
            for x, yy in ((0.22, a), (0.5, b), (0.78, a)): d.ellipse([m*x - lw/2, m*yy - lw/2, m*x + lw/2, m*yy + lw/2], fill=C["mu"])
        return p
    chev_up = _icon(int(18 * S), _chev(True)); chev_down = _icon(int(18 * S), _chev(False))
    ui = {"open": os.environ.get("AOE4SPOTIFY_PANEL_OPEN") == "1"}   # env var: screenshots/testing only
    power_img = _icon(int(30 * S), _power); fade_img = _icon(int(24 * S), _fade)
    root.iconphoto(True, ImageTk.PhotoImage(badge(64)), ImageTk.PhotoImage(badge(32)))
    set_app_icon(root)
    def text(x, y, s, sz, c=None, b=False, anchor="w", tag=None):
        return cv.create_text(*P(x, y), text=s, font=F(sz, b), fill=c or C["tx"], anchor=anchor, tags=tag)
    # Each tag is bound once; draw() only updates the handler table. (Re-binding inside a click
    # would free the running Tcl callback and crash Tk.) Handlers run after the event finishes.
    handlers, bound = {}, set()
    def click(tag, fn):
        handlers[tag] = fn
        if tag in bound: return
        bound.add(tag)
        cv.tag_bind(tag, "<Button-1>", lambda e, t=tag: root.after_idle(lambda: handlers[t]() if t in handlers else None), add="+")
        cv.tag_bind(tag, "<Enter>", lambda e, t=tag: cv.config(cursor="hand2" if t in handlers else ""), add="+")
        cv.tag_bind(tag, "<Leave>", lambda e: cv.config(cursor=""), add="+")

    base = load_config(user=False); user = load_user()
    defaults = base.get("default_playlists") or base.get("playlists", {})
    try: names = json.load(open(NAMES_CACHE, encoding="utf-8"))
    except Exception: names = {}
    state = {"spotify": None, "game": None}
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

    tipw, tips, tipbound = {}, {}, set()
    def hide_tip(_=None):
        w = tipw.pop("w", None)
        if w: w.destroy()
    def tip(tag, msg):
        tips[tag] = msg
        if tag in tipbound: return
        tipbound.add(tag)
        def show(e, tag=tag):
            hide_tip(); t = tk.Toplevel(root); t.overrideredirect(True); t.configure(bg=C["line"])
            tk.Label(t, text=tips.get(tag, ""), bg=C["line"], fg=C["tx"], font=F(10), padx=6, pady=2).pack()
            t.geometry("+%d+%d" % (e.x_root + 10, e.y_root + 14)); tipw["w"] = t
        cv.tag_bind(tag, "<Enter>", show, add="+"); cv.tag_bind(tag, "<Leave>", hide_tip, add="+")

    def draw():
        cv.delete("all"); handlers.clear(); hide_tip(); cfg = cur(); en = bool(cfg.get("enabled", True))
        # header
        cv.create_image(*P(20, 16), image=logo, anchor="nw")
        text(64, 32, "AoE4 Spotify", 22, b=True)
        rr(238, 22, 284, 42, 10, C["card"]); text(261, 32, "v0.2", 10, C["mu"], anchor="center")
        cv.create_line(*P(20, 62, 500, 62), fill=C["line"])
        # enabled
        rr(20, 74, 500, 128, 12, C["card"])
        cv.create_image(*P(48, 96), image=power_img, anchor="center")
        text(72, 101, "Enabled", 17, b=True); toggle(424, 88, en, "en", 52, 28)
        click("en", lambda: set_user("enabled", not en))
        # status lights
        for i, (lab, key, okt, offt) in enumerate((("Spotify", "spotify", "Logged in", "Logged out"), ("Game", "game", "Running", "Not running"))):
            x = 20 + i * 245; v = state[key]
            c = C["acc"] if v else C["idle"]
            rr(x, 140, x + 235, 176, 18, C["card"])
            oval_(P(x+16, 152, x+28, 164), fill=c, outline=""); text(x+38, 158, lab, 13, C["mu"])
            text(x+218, 158, "..." if v is None else (okt if v else offt), 13, c, True, "e")
        # collapsible Playlists section (collapsed by default)
        rr(20, 188, 500, 224, 10, C["card"], tag="plh")
        text(36, 206, "Playlists", 14, b=True, tag="plh")
        if not ui["open"]:
            changed = sum(1 for k, _ in AGES if cfg["playlists"].get(k) != defaults.get(k))
            text(150, 206, "4 ages" + (" · %d changed" % changed if changed else ""), 12, C["mu"], tag="plh")
        cv.create_image(*P(484, 206), image=chev_up if ui["open"] else chev_down, anchor="center", tags="plh")
        click("plh", lambda: (ui.update(open=not ui["open"]), draw()))
        for i, (k, lab) in enumerate(AGES if ui["open"] else []):
            y = 232 + i * 50; uri = cfg["playlists"].get(k, ""); is_def = uri == defaults.get(k)
            rr(20, y, 500, y + 42, 10, C["card"]); rr(28, y + 6, 58, y + 36, 6, C["ib"]); icon(i, 43, y + 21, C["acc"])
            text(70, y + 21, lab, 14, b=True)
            oval_(P(160, y+17, 168, y+25), fill=C["acc"] if uri else C["idle"], outline="")
            nm = pl_name(uri); nm = nm if len(nm) <= 22 else nm[:21] + "…"
            text(176, y + 21, nm, 13, C["mu"])
            rr(388, y + 9, 450, y + 33, 12, C["card"], C["acc"], "chg%d" % i); text(419, y + 21, "Change", 10, C["acc"], True, "center", "chg%d" % i)
            rc = C["dis"] if is_def else C["mu"]
            rr(458, y + 9, 488, y + 33, 12, C["card"], rc, "rev%d" % i); undo_icon(473, y + 21, rc, "rev%d" % i)
            click("chg%d" % i, lambda k=k, lab=lab: change(k, lab))
            if not is_def: click("rev%d" % i, lambda k=k: revert(k))
            tip("rev%d" % i, "Revert" if not is_def else "Revert (already default)")
        # Age 4 Intro theme
        base = 440 if ui["open"] else 236
        Hn = base + 230
        if int(cv.cget("height")) != int(Hn * S): cv.config(height=int(Hn * S))
        y = base; bon = bool((cfg.get("boss_intro") or {}).get("enabled", True))
        rr(20, y, 500, y + 46, 10, C["card"]); icon(3, 45, y + 23, C["acc"])
        text(66, y + 23, "Age 4 Intro theme", 14, b=True); toggle(452, y + 11, bon, "boss")
        click("boss", lambda: set_user("boss_intro_enabled", not bon))
        # fade
        y = base + 56; fv = float(cfg.get("fade_seconds", 2))
        rr(20, y, 500, y + 46, 10, C["card"])
        cv.create_image(*P(44, y + 23), image=fade_img, anchor="center")
        text(66, y + 23, "Fade", 14, b=True)
        x0, x1 = FX0, FX1; xv = x0 + (x1 - x0) * fv / 5
        rr(x0, y + 20, x1, y + 26, 3, C["off"], tag="fade"); rr(x0, y + 20, max(xv, x0 + 6), y + 26, 3, C["acc"], tag="fade")
        oval_(P(xv-9, y+14, xv+9, y+32), fill="white", outline=C["acc"], width=2*S, tags="fade")
        text(446, y + 23, ("%.1fs" % fv) if fv else "Off", 13, C["acc"], True, "e")
        fdef = float(base_cfg.get("fade_seconds", 2)); f_is_def = abs(fv - fdef) < 1e-6
        rc = C["dis"] if f_is_def else C["mu"]          # revert to default fade, right-aligned like playlist rows
        rr(458, y + 11, 488, y + 35, 12, C["card"], rc, "revf"); undo_icon(473, y + 23, rc, "revf")
        if not f_is_def: click("revf", lambda: (user.pop("fade_seconds", None), save_user(user), draw()))
        tip("revf", "Revert" if not f_is_def else "Revert (already default)")
        # buttons
        b1, b2 = base + 118, base + 170
        btns = (("Log in", "\u21bb", login, 20, b1), ("Updates", "\u2193", lambda: wb.open(RELEASES_URL), 265, b1),
                ("Open log", "\u2630", open_log, 20, b2), ("Uninstall", "\u2715", uninstall, 265, b2))
        for lab, ic, fn, x, y in btns:
            red = lab == "Uninstall"; tg = "b_" + lab.replace(" ", "_")   # Tk tags must not contain spaces
            rr(x, y, x + 235, y + 44, 10, C["card"], C["red"] if red else "", tg)
            text(x + 117, y + 22, ic + "  " + lab, 14, C["red"] if red else C["tx"], True, "center", tg)
            click(tg, fn)

    FX0, FX1 = 130, 360                              # fade slider track (shortened for the revert button)
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
        d = tk.Toplevel(root); d.title(title); d.configure(bg=C["card"]); d.transient(root); d.resizable(False, False); d.grab_set()
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
        e.bind("<Return>", ok); e.focus_set(); root.wait_window(d)
        return res.get("id")

    def change(k, lab):
        pid = dialog("Change playlist", "Paste a Spotify playlist link for %s Age:" % lab)
        if not pid: return
        pls = dict(user.get("playlists") or {}); pls[k] = "spotify:playlist:" + pid
        set_user("playlists", pls); fetch_names()

    def revert(k):
        pls = dict(user.get("playlists") or {}); pls.pop(k, None); set_user("playlists", pls)

    def login():
        def go():
            sp = Spotify(load_config())
            try: sp.login()
            except BaseException as e: log("Login failed: %r" % e); sp.tok = None
            st = setup_status(sp)
            refresh_now(); fetch_names()
            post(lambda: good_to_go(st, parent=root, on_open_panel=lambda: None, on_retry=login,
                                    fix=lambda: with_steam_closed(set_launch_option)))
        threading.Thread(target=go, daemon=True).start()

    def open_log():
        if not os.path.exists(LOGFILE): open(LOGFILE, "a").close()
        os.startfile(LOGFILE)

    def uninstall():
        from tkinter import messagebox
        un = os.path.join(HERE, "unins000.exe")
        if not os.path.exists(un): messagebox.showinfo("Uninstall", "Uninstaller not found (not installed?)."); return
        if messagebox.askyesno("Uninstall AoE4 Spotify", "Remove AoE4 Spotify from this PC?\nYour Steam launch option is restored."):
            subprocess.Popen([un]); root.destroy()

    def fetch_names():
        def go():
            try:
                cfg = load_config(); sp = Spotify(cfg)
                if not sp.tok: return
                changed = False
                for uri in set(cfg["playlists"].values()) | set(defaults.values()):
                    pid = uri.split(":")[-1]
                    if not pid or pid in names: continue
                    c, r = sp._api("GET", "/playlists/%s?fields=name" % pid)
                    if c == 200 and isinstance(r, dict) and r.get("name"): names[pid] = r["name"]; changed = True
                if changed:
                    json.dump(names, open(NAMES_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
                    post(draw)
            except Exception as e: log("Playlist names: %r" % e)
        threading.Thread(target=go, daemon=True).start()

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

    draw(); pump(); tick(); fetch_names(); root.mainloop()

if __name__ == "__main__":
    try: main()
    except Exception as e:
        log("FATAL: %r" % e); raise
