"""Spotify login (PKCE) and playback. No game-specific code.
"""

import base64, hashlib, http.server, json, os, random, secrets, sys, threading, time, urllib.error, urllib.parse, urllib.request, webbrowser
from aoe4spotify.core.runtime import DATA, FileLock, REDIRECT, SCOPES, TOKEN, atomic_write, child_env, clean_env, log, log_once, proc_running, test_env
from aoe4spotify.core.branding import APP_NAME
from aoe4spotify.core import transition as _transition
from aoe4spotify.core.settings import custom_tracks, is_custom, load_config
from aoe4spotify.core import catalog as _cat


STORE_APP = r"SpotifyAB.SpotifyMusic_zpdnekdrzrea0"
def spotify_running(): return proc_running("Spotify.exe")
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
            subprocess.Popen([exe, "--minimized"], env=clean_env(), creationflags=0x08000000, close_fds=True); log("Started Spotify (minimized)"); return True
        if os.path.isdir(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Packages", STORE_APP)):   # Microsoft Store
            subprocess.Popen(["explorer.exe", r"shell:AppsFolder\%s!Spotify" % STORE_APP], env=clean_env(), close_fds=True); log("Started Spotify (Microsoft Store app)"); return True
        if _spotify_protocol_registered():
            subprocess.Popen(["explorer.exe", "spotify:"], env=clean_env(), close_fds=True); log("Started Spotify via spotify: link"); return True
    except Exception as e:
        log("Could not start Spotify: %r" % e); return False
    log("Spotify desktop app is NOT INSTALLED on this PC - install it from spotify.com to get music.")
    return False
INTRO_LEAD = 1.2         # s before the intro ends: start the playlist (covers Spotify's ~1s start latency)
INTRO_FADE_OUT = 0.4     # s: the intro's last moment dips fast; the playlist then fades in normally
INTRO_OUTRO_MS = 12000                                 # last part of an intro song: often fades out on its own
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
            atomic_write(p, json.dumps({"v": float(v), "last": None if last is None else float(last)}))
    except Exception as e: log_once("Fade volume guard", e)
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
    except Exception as e: log_once("Fade volume restore", e)
class SpotifySession:
    """Windows per-app volume of Spotify.exe (Core Audio session). Smooth and instant; local only."""
    def __init__(self, vols): self.vols = vols
    _warned = None
    @staticmethod
    def find():
        if sys.platform != "win32" or test_env("AOE4SPOTIFY_NO_LOCAL_FADE"): return None
        err = None
        for attempt in range(2):                     # one retry: audio endpoints can be mid-change
            try:
                try:                                 # every worker thread needs COM; harmless if already set up
                    import comtypes; comtypes.CoInitializeEx(getattr(comtypes, "COINIT_MULTITHREADED", 0))
                except Exception: pass
                from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
                vols = []
                for x in AudioUtilities.GetAllSessions():   # fresh every call: never a stale session after Spotify restarts
                    try:
                        if x.Process and x.Process.name().lower() == "spotify.exe":
                            vols.append(x._ctl.QueryInterface(ISimpleAudioVolume))
                    except Exception: continue       # one dead/protected session must not sink the rest
                SpotifySession._warned = None
                return SpotifySession(vols) if vols else None
            except Exception as e:
                err = e; time.sleep(0.15)
        msg = "%s: %s" % (type(err).__name__, err)
        if SpotifySession._warned != msg:            # full reason once, not every age-up
            log("Local fade unavailable (%s)" % msg); SpotifySession._warned = msg
        return None
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
_LOGIN = {"lock": threading.Lock(), "active": False, "url": None, "states": {}, "got": None, "err": None,
          "done": threading.Event(), "srv": None}
class _CallbackServer(http.server.HTTPServer):
    allow_reuse_address = False                       # never share port 8888 with another listener
    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):    # Windows: refuse a second bind instead of silently sharing
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()
class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def _page(self, code, title, sub):
        self.send_response(code); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(("<html><body style='background:#121212;color:#f2f2f2;font-family:Segoe UI,sans-serif;text-align:center;"
                          "padding-top:80px'><h2>%s</h2><p style='color:#9a9a9a'>%s</p></body></html>" % (title, sub)).encode())
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != "/callback": self.send_response(404); self.end_headers(); return
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}     # extra params (e.g. 'ubi') ignored
        L = _LOGIN; ver = L["states"].get(q.get("state") or "")
        if ver is None:                               # an old tab from an earlier attempt: keep waiting for the right one
            log("Login: ignored a callback from an outdated login tab")
            self._page(400, "This login link is out of date", ("Use the newest Spotify tab, or press Log in again in " + APP_NAME + ".")); return
        if q.get("error"):
            L["got"] = ("error", str(q["error"])[:40]); self._page(200, "Spotify login cancelled", "You can close this tab."); return
        if not q.get("code"):
            self._page(400, "Spotify login failed", "No login code was returned. Try again."); return
        L["got"] = ("code", q["code"], ver); self._page(200, "Spotify login done", ("You can close this tab and return to " + APP_NAME + "."))
    def log_message(self, *a): pass
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
        atomic_write(TOKEN, json.dumps(tok))

    @staticmethod
    def _disk_tok():
        try:
            with open(TOKEN, encoding="utf-8") as f: t = json.load(f)
            return t if isinstance(t, dict) and t.get("refresh_token") else None
        except Exception: return None

    def _token_req(self, data):
        req = urllib.request.Request("https://accounts.spotify.com/api/token",
            data=urllib.parse.urlencode(data).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        with urllib.request.urlopen(req, timeout=15) as r: return json.load(r)

    def login(self, timeout=300):
        """PKCE login. One local callback server per process: pressing Log in again while a login is pending
        reopens the SAME Spotify page instead of starting a second listener (on Windows two sockets could
        share port 8888, so a tab's callback landed on the other login and failed with a state mismatch).
        Every state issued by this pending login stays valid; extra query params (e.g. 'ubi') are ignored."""
        L = _LOGIN
        with L["lock"]:
            if L["active"]:
                log("Login already in progress - reopening the same Spotify page")
                url = L["url"]; owner = False
            else:
                try: srv = _CallbackServer(("127.0.0.1", 8888), _CallbackHandler)
                except OSError:
                    log(("Login: port 8888 is busy (another " + APP_NAME + " login window open?) - finish or close it and try again"))
                    raise SystemExit("Login port 8888 is busy")
                verifier = secrets.token_urlsafe(64)[:100]
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                state = secrets.token_urlsafe(16)
                url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
                    "client_id": self.cid, "response_type": "code", "redirect_uri": REDIRECT,
                    "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state})
                L.update(active=True, url=url, states={state: verifier}, got=None, err=None, done=threading.Event(), srv=srv)
                owner = True
                log("Opening browser for Spotify login...")
        try: webbrowser.open(url)
        except Exception as e: log("Login: could not open the browser (%s)" % type(e).__name__)
        if not owner:                                     # the pending login finishes it; share its outcome
            L["done"].wait(timeout)
            if L["err"]: raise SystemExit(L["err"])
            self.tok = self._disk_tok()
            if not self.tok: raise SystemExit("Spotify login did not finish")
            return
        err = None
        try:
            srv.timeout = 1; deadline = time.time() + timeout
            while L["got"] is None and time.time() < deadline: srv.handle_request()
            got = L["got"]
            if got is None: err = "Spotify login timed out (no answer from the browser in %s)" % ("%d min" % (timeout // 60) if timeout >= 60 else "%d s" % timeout)
            elif got[0] == "error": err = "Spotify login was cancelled or refused (%s)" % got[1]
            else:
                try: tok = self._token_req({"grant_type": "authorization_code", "code": got[1], "redirect_uri": REDIRECT,
                                            "client_id": self.cid, "code_verifier": got[2]})
                except urllib.error.HTTPError as e:
                    try: b = json.loads(e.read().decode("utf-8", "replace") or "{}")
                    except Exception: b = {}
                    err = "Spotify refused the login code (HTTP %s: %s%s)" % (e.code, b.get("error", "?"),
                          (" - " + b["error_description"]) if b.get("error_description") else "")
                except Exception as e: err = "Spotify login: token request failed (%s - offline?)" % type(e).__name__
                else:
                    self._save(tok); log("Spotify login OK, token cached in token.json")
        finally:
            try: srv.server_close()
            except Exception: pass
            with L["lock"]: L.update(active=False, err=err, srv=None); L["done"].set()
        if err: log("Login failed: " + err); raise SystemExit(err)

    def access(self):
        # Never opens the login page by itself: background calls (panel, game) just fail quietly.
        if not self.tok:
            self.tok = self._disk_tok()                  # logged in from the panel meanwhile
            if not self.tok: raise RuntimeError("not logged in to Spotify")
        if time.time() > self.tok.get("expires_at", 0):
            # The panel and the game process share token.json, and a refresh can rotate the refresh token:
            # refresh under a cross-process lock, and first adopt a newer token another process already saved.
            with FileLock(TOKEN):
                d = self._disk_tok()
                if d and time.time() <= d.get("expires_at", 0) and d.get("access_token") and d.get("access_token") != getattr(self, "_rejected", None):
                    self.tok = d; return d["access_token"]
                if d and d.get("refresh_token") != self.tok.get("refresh_token"): self.tok = d
                used = self.tok.get("refresh_token")
                try:
                    self._save(self._token_req({"grant_type": "refresh_token", "refresh_token": used, "client_id": self.cid}))
                except urllib.error.HTTPError as e:
                    if e.code in (400, 401):      # refresh token revoked/expired: forget it, user must log in again
                        d = self._disk_tok()
                        if d and d.get("refresh_token") != used: self.tok = d; raise   # someone saved a newer one: keep it
                        log(("Spotify login expired - open " + APP_NAME + " and click Log in"))
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
            if method != "GET": self._pcache = None           # anything we change invalidates the cached player state
            if status == 429:
                try: self._retry_after = float(r.getheader("Retry-After") or 1)
                except Exception: self._retry_after = 1.0
            if status == 401 and _retry and self.tok:          # access token rejected: refresh once
                self._rejected = self.tok.get("access_token"); self.tok["expires_at"] = 0
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
        if is_custom(uri):                                  # app-only list: play the songs directly (no Spotify context)
            tr = custom_tracks(uri)
            if not tr: log("Custom list %s is empty" % uri); return False
            if self.shuffle: tr = tr[:]; random.shuffle(tr)      # app-side shuffle = random start + random order
            self._custom = (uri, tr)
            ok = self._play(uri, {"uris": tr}, q)
            if ok: self.set_mode(shuffle=False, repeat="context" if self.repeat else None)
            return ok
        payload = {"context_uri": uri}
        if self.shuffle and uri.startswith("spotify:playlist:"):
            n = _cat.playlist_total(self, uri.split(":")[-1])
            payload["offset"] = {"position": random.randrange(n) if n > 0 else 0}
        self._last_fail = None
        ok = self._play(uri, payload, q)
        if not ok and "offset" in payload and (getattr(self, "_last_fail", None) or (0,))[0] in (400, 403, 404):
            log("Spotify: random start song is not playable (local file / unavailable?) - starting from the top")
            payload.pop("offset"); ok = self._play(uri, payload, q)
        if ok: self.set_mode(shuffle=True if self.shuffle else None, repeat="context" if self.repeat else None)
        return ok

    # ---- your shuffle / repeat: saved the first time the app changes them, put back when it hands control back
    def take_over(self):
        if getattr(self, "_user_mode", None) is not None: return
        c, st = self._api("GET", "/me/player")
        if c == 200 and isinstance(st, dict) and st.get("item"):
            self._user_mode = {"shuffle": bool(st.get("shuffle_state")), "repeat": st.get("repeat_state") or "off"}
            log("Saved your Spotify shuffle=%s repeat=%s" % (self._user_mode["shuffle"], self._user_mode["repeat"]))
        else: self._user_mode = {}                        # nothing was loaded: nothing to put back
        self._app_mode = {}

    def set_mode(self, shuffle=None, repeat=None):
        """The only place the app changes shuffle / repeat (remembers what it set, to tell your own changes apart)."""
        self.take_over(); dq = "&device_id=" + self.device_id if self.device_id else ""
        if shuffle is not None: self._api("PUT", "/me/player/shuffle?state=%s%s" % ("true" if shuffle else "false", dq)); self._app_mode["shuffle"] = bool(shuffle)
        if repeat in ("off", "context", "track"): self._api("PUT", "/me/player/repeat?state=%s%s" % (repeat, dq)); self._app_mode["repeat"] = repeat

    @_transition.wrap
    def hand_back(self, why, mode=None):
        """Put your shuffle / repeat back (volume has its own logic). Skipped if you changed them yourself meanwhile.
        mode: values to restore instead of the saved ones (Resume: the pre-match state)."""
        um = mode if mode is not None else getattr(self, "_user_mode", None); am = getattr(self, "_app_mode", None) or {}
        self._user_mode = None; self._app_mode = {}
        if not um: return False
        c, st = self._api("GET", "/me/player")
        if c != 200 or not isinstance(st, dict): return False
        sh, rp = bool(st.get("shuffle_state")), st.get("repeat_state") or "off"
        if ("shuffle" in am and sh != am["shuffle"]) or ("repeat" in am and rp != am["repeat"]):
            log("%s: you changed shuffle/repeat yourself - keeping yours" % why); return False
        dq = "&device_id=" + self.device_id if self.device_id else ""
        if sh != um.get("shuffle", sh): self._api("PUT", "/me/player/shuffle?state=%s%s" % ("true" if um["shuffle"] else "false", dq))
        if rp != um.get("repeat", rp) and um.get("repeat") in ("off", "context", "track"): self._api("PUT", "/me/player/repeat?state=%s%s" % (um["repeat"], dq))
        log("%s: your shuffle=%s repeat=%s restored" % (why, um.get("shuffle"), um.get("repeat"))); return True

    def ensure_device(self, wait=20):
        """Find this PC's Spotify device (type Computer); start Spotify if needed and wait for it."""
        def find():
            c, d = self._api("GET", "/me/player/devices")
            devs = (d or {}).get("devices", []) if isinstance(d, dict) else []
            comp = [x for x in devs if (x.get("type") or "").lower() == "computer"]
            me = os.environ.get("COMPUTERNAME", "").lower()
            comp.sort(key=lambda x: (x.get("name", "").lower() != me, not x.get("is_active")))
            if comp: return comp[0]
            return next((x for x in devs if x.get("id") and not x.get("is_restricted")), None)   # no PC device: any usable one
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

    @_transition.wrap
    def _play(self, uri, payload, q):
        code, body = self._api("PUT", "/me/player/play" + q, payload)
        if code == 429 or code >= 500:               # rate limited / Spotify hiccup: one paced retry
            wait = min(float(getattr(self, "_retry_after", 1) or 1), 5.0) if code == 429 else 0.6
            log("Spotify %s on play - retrying in %.1fs" % (code, wait)); time.sleep(wait)
            code, body = self._api("PUT", "/me/player/play" + q, payload)
        if code == 404 and body and "device" not in str(body).lower():   # deleted / private playlist or song: not a device issue
            self._last_fail = (code, body); log("Spotify: %s not found (deleted, private or unavailable?) - %s" % (uri, body)); return False
        if code == 404:  # no active device (Spotify closed/idle): start it and target this PC by device_id
            self.device_id = None
            if not self.ensure_device(): return False
            code, body = self._api("PUT", "/me/player/play?device_id=" + self.device_id, payload)
            if code == 404:  # Spotify open but idle (nothing played yet): wake the device with a transfer, then play
                log("Spotify: device idle - waking it up and retrying")
                for _ in range(3):
                    self._api("PUT", "/me/player", {"device_ids": [self.device_id], "play": False}); time.sleep(1.0)
                    code, body = self._api("PUT", "/me/player/play?device_id=" + self.device_id, payload)
                    if code != 404: break
        if code not in (200, 202, 204): self._last_fail = (code, body)
        if code == 403:
            if "premium" in str(body).lower() or not body: log("Spotify 403: playback control needs Spotify Premium (%s)" % body)
            else: log("Spotify 403: Spotify refused to play %s (%s)" % (uri, body))
            return False
        if code not in (200, 202, 204):
            log("Spotify error %s: %s" % (code, body)); return False
        self._paused_by_us = False
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

    def player_state(self, max_age=0.0):
        """GET /me/player, reusing a result at most max_age s old (only when nothing was changed since)."""
        pc = getattr(self, "_pcache", None)
        if max_age > 0 and pc and time.time() - pc[0] <= max_age: return pc[1], pc[2]
        c, st = self._api("GET", "/me/player")
        self._pcache = (time.time(), c, st) if c == 200 else None
        return c, st

    @_transition.wrap
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
            time.sleep(0.25)
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
            # Spotify can close mid-fade: its audio session then throws COM errors. Never let that kill the switch.
            def set_(v):
                try: sess.set(v)
                except Exception as e: log("Local fade: Spotify audio session gone (%s)" % type(e).__name__); return False
                ctl["last"] = v; local_guard(orig, v); return True
            def get_():
                try: return sess.get()
                except Exception: return None
            def put_(v):
                try: sess.set(v); return True
                except Exception: return False
            ctl.update(set=set_, get=get_, near=lambda c: ctl["last"] is not None and abs(c - ctl["last"]) <= 0.02, every=0.0, fps=60,
                       read=get_, put=put_)
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

    def _tls(self):
        if not hasattr(self, "_tl"): self._tl = threading.local()
        return self._tl

    @_transition.wrap
    def switch(self, uri, fade=2.0, player=None, fade_out=None):
        """fade_out: seconds for the dip (default = fade); the intro hand-over uses a short one."""
        player = player or self.play; fo = fade if fade_out is None else fade_out
        if not hasattr(self, "_glock"):
            self._glock = threading.Lock(); self._gen = 0
        with self._glock:
            self._gen += 1; gen = self._gen; self._tls().gen = gen
            self._busy = getattr(self, "_busy", 0) + 1     # our own switch: a stopped player now is NOT a user pause
            st = None
            if fade > 0:
                code, st = self.player_state(max_age=1.0)      # the age-up's user_paused() check just read it
                st = st if code == 200 and isinstance(st, dict) else None
            dev = (st or {}).get("device")
            playing = bool(st and st.get("is_playing"))
            old_item = ((st or {}).get("item") or {}).get("uri")
            loc = self._fader(dev) if (playing and fade > 0) else None
            mode = cur = None
            if loc:
                try: cur = loc.get()                        # Windows app volume; Spotify's own volume is never touched
                except Exception: loc = None                # audio session already gone (Spotify closing)
                else: mode = "local"
            if not mode and fade > 0 and playing and dev and dev.get("volume_percent") is not None and dev.get("supports_volume", True):
                mode, cur = "api", float(dev["volume_percent"])
            live = getattr(self, "_live", None)          # a fade a newer age-up just interrupted
            orig = cur
            if live and mode and live["mode"] == mode and live["last"] is not None and live["near"](cur):
                orig = live["orig"]                      # still dipped by us: go back to the level before that dip
            ctl = self._vol_ctl(mode, orig, loc) if mode else None
            orphan = live if (live and live["last"] is not None and live["user"] is None
                              and not (ctl and orig is live["orig"])) else None   # a dip nobody will undo now
            self._live = ctl
        if orphan and not ctl:                        # superseded fade whose level this switch doesn't inherit: undo it
            try:
                time.sleep(0.12)                          # let the old fader see the new generation and stop
                cur_ = orphan["read"]()
                if cur_ is None or orphan["near"](cur_):
                    orphan["put"](orphan["orig"]); log("Put the volume back after an interrupted fade")
                if orphan["mode"] == "local": local_guard(None)
            except Exception as e: log("Volume restore after interrupted fade failed: %r" % e)
        try:
            if not ctl:
                return player(uri)
            r = self._run_fade(ctl, fo, True, gen) if fo > 0.05 else "done"
            if r == "stop":
                if gen != self._gen: return False
                log("Spotify: volume control not allowed on this device, switching without fade")
                return player(uri)
            if r == "user":
                log("Volume changed during the fade: keeping your level, switching without fade")
                return player(uri)
            log(("Fade: %s, %.1fs each way" % ("Windows app volume" if ctl["mode"] == "local" else "Spotify volume", fade)) if abs(fo - fade) < 0.05 else
                ("Fade: %s, %.1fs out / %.1fs in" % ("Windows app volume" if ctl["mode"] == "local" else "Spotify volume", fo, fade)))
            ok = player(uri)
            if gen == self._gen: self._wait_started(old_item)
            r = self._run_fade(ctl, fade, False, gen)
            if r == "user": log("Volume changed during the fade: keeping your level")
            return ok
        finally:
            with self._glock:
                self._busy = max(0, getattr(self, "_busy", 1) - 1); self._quiet_until = time.time() + 3.0
                try:
                    if ctl and gen == self._gen:
                        if ctl["user"] is None and ctl["last"] is not None:
                            cur = ctl["read"]()              # only undo OUR dip, never a newer user choice
                            if cur is None or ctl["near"](cur):
                                if ctl["pacer"] and not ctl["pacer"].fail: ctl["pacer"].target(ctl["orig"]); ctl["pacer"].flush()
                                else: ctl["put"](ctl["orig"])
                            else: log("Volume changed during the fade: keeping your level")
                        if ctl["mode"] == "local": local_guard(None)
                        self._live = None
                except Exception as e: log("Volume restore failed: %r" % e); self._live = None
                finally:
                    if ctl and ctl["pacer"]: ctl["pacer"].stop()

    # ---- user pause: never start music while YOU paused Spotify; hold the age playlist until you press play
    def user_paused(self):
        """True when Spotify has something loaded but is paused, and not because of our own switch/fade
        (fades only dip volume; the short gap while a new track starts is covered by _busy/_quiet_until)."""
        if getattr(self, "_busy", 0) or time.time() < getattr(self, "_quiet_until", 0): return False
        c, st = self.player_state()
        if c != 200 or not isinstance(st, dict) or not st.get("item"): return False   # idle / no session: just play
        if st.get("is_playing"): self._paused_by_us = False; return False
        return not getattr(self, "_paused_by_us", False)          # paused by our After match Fade/Stop: not you

    def hold(self, key, uri, fade=2.0):
        """Remember the newest age playlist (no intro) and start it with the normal fade once you resume."""
        if not hasattr(self, "_hlock"): self._hlock = threading.Lock(); self._pending = None
        log("Spotify paused by user - holding %s until resume" % key)
        with self._hlock:
            new_watch = self._pending is None
            self._pending = (key, uri, fade)
        if new_watch: threading.Thread(target=self._watch_resume, daemon=True).start()

    def clear_hold(self):
        if hasattr(self, "_hlock"):
            with self._hlock: self._pending = None

    def _watch_resume(self, every=1.5):
        while True:
            time.sleep(every)
            with self._hlock:
                if self._pending is None: return                   # superseded by a normal switch
            c, st = self._api("GET", "/me/player")
            if c != 200 or not isinstance(st, dict) or not st.get("is_playing"): continue
            with self._hlock:
                pend, self._pending = self._pending, None
            if pend:
                log("Spotify resumed - switching to held %s playlist" % pend[0]); self.switch(pend[1], pend[2])
                cb = getattr(self, "on_now_playing", None)
                if cb:
                    try: cb(pend[0])
                    except Exception as e: log_once("Now-playing callback", e)
            return

    # ---- Age 4 Intro theme (config key boss_intro): play one track, then the age playlist (runs in a background thread)
    def boss_then(self, track, playlist, fade=2.0):
        if not hasattr(self, "_glock"):
            self._glock = threading.Lock(); self._gen = 0
        dq = "?device_id=" + self.device_id if self.device_id else ""
        # intro must not loop: repeat off, then play it as a single-track list
        self.set_mode(repeat="off")
        ok = self.switch_uris(track, fade)
        gen = getattr(self._tls(), "gen", self._gen)       # OUR switch's generation (not a newer one's)
        if gen != self._gen: return                         # superseded (age-up / match end): never play the old age
        if not ok: return self.switch(playlist, fade)
        _, tr = self._api("GET", "/tracks/" + track.split(":")[-1])
        dur = (tr or {}).get("duration_ms", 240000) if isinstance(tr, dict) else 240000
        t0 = time.time(); started = False; nap = 2.0
        while time.time() - t0 < dur / 1000.0 + 15:
            time.sleep(nap); nap = 2.0
            if gen != self._gen: return                     # a newer switch took over
            c, st = self._api("GET", "/me/player")
            if c != 200 or not isinstance(st, dict): continue
            item = (st.get("item") or {}).get("uri")
            if item == track: started = True
            if started and item != track: break             # ended or skipped by the user
            if item == track and st.get("progress_ms", 0) >= dur - INTRO_OUTRO_MS: _transition.hold(INTRO_OUTRO_MS / 1000.0 + _transition.GRACE)   # quiet outro: not a pause
            left = (dur - st.get("progress_ms", 0)) / 1000.0 if item == track else None
            if left is not None and left <= INTRO_LEAD + 0.15: break           # hand over now: playlist starts as the intro ends
            if left is not None and st.get("is_playing"): nap = max(0.1, min(2.0, left - INTRO_LEAD))   # wake exactly at the hand-over point
            if started and not st.get("is_playing") and st.get("progress_ms", 1) == 0: break
            if started and item == track and not st.get("is_playing"): t0 += 2   # paused by you: don't run the clock
        if gen != self._gen: return
        if self.user_paused(): return self.hold("playlist after intro", playlist, fade)
        try: fade = float(load_config().get("fade_seconds", fade))           # Fade changed in the panel during the intro: use the new value
        except Exception as e: log_once("Fade setting after intro", e)
        log("Age 4 Intro theme done -> playlist")
        self.switch(playlist, fade, fade_out=INTRO_FADE_OUT)                 # short dip on the intro's last second, normal fade-in

    @_transition.wrap
    def switch_uris(self, track, fade):
        """Like switch(), but plays a single track (uris) instead of a playlist context."""
        q = "?device_id=" + self.device_id if self.device_id else ""
        return self.switch(track, fade, player=lambda _u: self._play(track, {"uris": [track]}, q))

    # ---- After match
    def snapshot(self):
        """What is playing right now (context + track + position + shuffle/repeat), for After match: Resume."""
        c, st = self._api("GET", "/me/player")
        if c != 200 or not isinstance(st, dict) or not isinstance(st.get("item"), dict): return None
        snap = {"ctx": (st.get("context") or {}).get("uri"), "track": st["item"].get("uri"), "pos": int(st.get("progress_ms") or 0),
                "playing": bool(st.get("is_playing")), "shuffle": bool(st.get("shuffle_state")), "repeat": st.get("repeat_state") or "off"}
        cu = getattr(self, "_custom", None)                 # one of our custom lists: remember the list + its order
        if not snap["ctx"] and cu and snap["track"] in cu[1]: snap.update(custom=cu[0], order=list(cu[1]))
        return snap

    def _snap_payload(self, snap):
        ctx, tr, pos = snap.get("ctx"), snap.get("track"), snap.get("pos", 0)
        if snap.get("order"): return snap["custom"], {"uris": snap["order"], "offset": {"uri": tr}, "position_ms": pos}, {"uris": snap["order"]}
        if ctx and tr and not ctx.startswith("spotify:artist:"): return ctx, {"context_uri": ctx, "offset": {"uri": tr}, "position_ms": pos}, {"context_uri": ctx}
        if ctx: return ctx, {"context_uri": ctx}, None
        return tr, {"uris": [tr], "position_ms": pos}, None

    def pause_ours(self):
        self._paused_by_us = True; return self.pause()

    @_transition.wrap
    def fade_pause(self, fade=2.0):
        """Fade out, pause, put the volume back (while paused). Our pause never counts as yours."""
        self._paused_by_us = True
        return self.switch("pause", fade, player=lambda _u: (setattr(self, "_paused_by_us", True), self.pause())[1])

    def play_any(self, uri, fade=2.0):
        return self.switch_uris(uri, fade) if uri.startswith("spotify:track:") else self.switch(uri, fade)

    def restore_paused(self, snap, fade=2.0):
        """Pre-match music was loaded but paused: fade out what plays now, load it back at its spot, leave it paused."""
        q = "?device_id=" + self.device_id if self.device_id else ""
        key, payload, fb = self._snap_payload(snap)
        self.fade_pause(fade)
        sess = None
        try: sess = SpotifySession.find()                          # mute the tiny blip while it loads (local Spotify)
        except Exception: sess = None
        v0 = sess.get() if sess else None
        try:
            if sess: sess.set(0.0)
            ok = self._play(key, payload, q) or (bool(fb) and self._play(key, fb, q))
            if ok and snap.get("order"): self._custom = (snap["custom"], snap["order"])
            if ok: time.sleep(0.35); self.pause_ours()
        finally:
            if sess and v0 is not None: time.sleep(0.25); sess.set(v0)
        if ok: self.hand_back("Resume", {"shuffle": bool(snap.get("shuffle")), "repeat": snap.get("repeat") or "off"})
        return ok

    def restore(self, snap, fade=2.0):
        """Play the saved pre-match music again where it was (falls back to its start / the track alone)."""
        q = "?device_id=" + self.device_id if self.device_id else ""
        key, payload, fb = self._snap_payload(snap)
        def player(_u):
            ok_ = self._play(key, payload, q) or (bool(fb) and self._play(key, fb, q))
            if ok_ and snap.get("order"): self._custom = (snap["custom"], snap["order"])
            return ok_
        ok = self.switch(key, fade, player=player)
        if ok: self.hand_back("Resume", {"shuffle": bool(snap.get("shuffle")), "repeat": snap.get("repeat") or "off"})
        return ok
