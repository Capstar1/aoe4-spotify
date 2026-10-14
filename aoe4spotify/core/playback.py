"""Turn an age key into a Spotify switch. Game adapters do not call Spotify.
"""

import json, os, random, threading, time
from aoe4spotify.core.runtime import DATA, HERE, atomic_write, log, log_once
from aoe4spotify.core import transition as _transition
from aoe4spotify.core.settings import DEFAULT_AGE, INTRO_AGES, after_match_cfg, custom_tracks, is_custom, is_playable, load_config

BOSS_STATE = os.path.join(DATA, "boss_state.json")   # last pick per civ
NOW_PLAYING = os.path.join(DATA, "now_playing.json")   # which age row the panel shows as playing (glow pool fire)
_NOW = {"key": None, "paused": False}
def _write_now():
    try:
        os.makedirs(DATA, exist_ok=True)
        atomic_write(NOW_PLAYING, json.dumps({"key": _NOW["key"], "paused": _NOW["paused"], "pid": os.getpid(), "t": time.time()}))
    except Exception as e: log_once("Now-playing file", e)
def set_now_playing(key):
    """Tell the panel which age playlist we're playing (None = none of ours). Never raises."""
    _NOW["key"] = key; _NOW["paused"] = False; _write_now()
def mark_paused(paused):
    """You paused / resumed Spotify mid-match: the row keeps its key but the panel's fire sleeps while paused."""
    if _NOW["key"] is None or _NOW["paused"] == bool(paused): return False
    _NOW["paused"] = bool(paused); _write_now(); return True
def read_now_playing():
    """The playing age key for the panel, or None (nothing of ours, or paused)."""
    try:
        with open(NOW_PLAYING, encoding="utf-8") as f: d = json.load(f)
        return d.get("key") if isinstance(d, dict) and not d.get("paused") else None
    except Exception: return None

class PauseWatch:
    """Notices a mid-match pause from Spotify's own audio level (Windows audio session peak meter):
    local and cheap, no Spotify API calls. Silent for `quiet` s = paused; any sound again = playing.
    Only looks while one of our age playlists is marked playing."""
    def __init__(self, level=None, quiet=4.0, every=1.0):
        self.level = level or self._peak; self.quiet, self.every = quiet, every
        self.silent_since = None; self._meters = None; self._next_find = 0.0
    def _peak(self):
        """Highest peak of Spotify's audio sessions, or None when unknown (no Spotify audio session / not Windows)."""
        try:
            if self._meters is None:
                if time.time() < self._next_find: return None
                self._next_find = time.time() + 15
                import sys
                if sys.platform != "win32": return None
                try:
                    import comtypes; comtypes.CoInitializeEx(getattr(comtypes, "COINIT_MULTITHREADED", 0))
                except Exception: pass
                from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
                ms = [x._ctl.QueryInterface(IAudioMeterInformation) for x in AudioUtilities.GetAllSessions()
                      if x.Process and x.Process.name().lower() == "spotify.exe"]
                self._meters = ms or None
                if not ms: return None
            return max(float(m.GetPeakValue()) for m in self._meters)
        except Exception:
            self._meters = None; return None                        # Spotify restarted: find it again later
    def poll(self, now=None):
        now = time.time() if now is None else now
        if _NOW["key"] is None: self.silent_since = None; return
        if _transition.active(now): self.silent_since = None; return   # our own fade / switch / intro hand-over (+ grace): not a pause
        lv = self.level()
        if lv is None: return                                        # can't tell: leave the row as it is
        if lv > 0.0005:
            self.silent_since = None
            if mark_paused(False): log("Spotify playing again - row glow back on")
        else:
            if self.silent_since is None: self.silent_since = now
            elif now - self.silent_since >= self.quiet and mark_paused(True): log("Spotify paused - row glow off")
    def run(self, stop):
        while not stop():
            try: self.poll()
            except Exception as e: log_once("Pause watch", e)
            time.sleep(self.every)
def intro_of(cfg, age):
    it = (cfg.get("intros") or {}).get(age)
    if it: return it
    b = cfg.get("boss_intro") or {}
    return {"enabled": age in (b.get("ages") or [DEFAULT_AGE]), "pools": b.get("pools") or {}}
def pick_boss_track(cfg, civ, age=None):
    if age is None: age = DEFAULT_AGE
    b = cfg.get("boss_intro") or {}
    pools = intro_of(cfg, age)["pools"]
    fallback = (b.get("default") or []) if age == DEFAULT_AGE else []    # other ages: empty civ = no intro
    pool = [u for u in (pools[civ] if civ in pools else fallback) if u.startswith("spotify:track:")]   # [] = no intro
    if not pool: return None
    try: state = json.load(open(BOSS_STATE, encoding="utf-8"))
    except Exception: state = {}
    choices = [u for u in pool if u != state.get(civ)] or pool      # never the same as last time
    uri = random.choice(choices)
    state[civ] = uri
    try: atomic_write(BOSS_STATE, json.dumps(state, indent=1))
    except Exception as e: log("Could not save boss state: %r" % e)
    return uri
def choose_intro(cfg, age, civ):
    """The intro track to play when entering `age` as `civ`, or None (intro off, or that civ has no songs
    in this age): then the switcher just plays the age playlist."""
    return pick_boss_track(cfg, civ, age) if civ and boss_age(cfg, age) else None
def boss_age(cfg, key):
    b = cfg.get("boss_intro") or {}
    return bool(b.get("enabled", True)) and key in INTRO_AGES and bool(intro_of(cfg, key)["enabled"])
def age_switch(sp, k, civ=None, start=False):
    """Switch to age k's music (intro first if set). Reads the settings fresh: panel changes apply right away."""
    cur = load_config()
    if not cur.get("enabled", True):                                      # turned off in the panel mid-match
        sp.clear_hold(); sp.hand_back("Disabled"); set_now_playing(None); return
    uri = cur["playlists"].get(k, "")
    if not is_playable(uri): log("No playlist set for %s" % k); return
    fade = float(cur.get("fade_seconds", 2))
    if not start and sp.user_paused():                                    # you paused mid-match: no intro, no switch
        sp.hold(k, uri, fade); set_now_playing(None); return
    sp.clear_hold(); set_now_playing(k)
    track = choose_intro(cur, k, civ)
    if track:
        log("%s intro for %s: %s" % (k.capitalize(), civ, track))
        threading.Thread(target=sp.boss_then, args=(track, uri, fade), daemon=True).start()
    else:
        threading.Thread(target=sp.switch, args=(uri, fade), daemon=True).start()
def make_switcher(sp):
    """(play, jobs): play(k, civ) only queues; one worker runs Spotify work in log order, never under the tracker lock."""
    import queue as _queue
    jobs = _queue.Queue()
    try: sp.on_now_playing = set_now_playing           # a held playlist that starts on resume lights its row too
    except Exception: pass
    def worker():
        while True:
            fn, a = jobs.get()
            try: fn(*a)
            except Exception as e: log("Switch failed: %r" % e)
            finally: jobs.task_done()
    threading.Thread(target=worker, daemon=True).start()
    def play(k, civ=None): jobs.put((age_switch, (sp, k, civ)))
    play.start = lambda k, civ=None: jobs.put((age_switch, (sp, k, civ, True)))   # ignores a pause from before the match
    return play, jobs
def install_after_match(t, sp, wait=6.0):
    """Hook the After match setting into a Tracker. Resume: the music playing at match start is saved (unless it is
    one of our age playlists, e.g. back-to-back matches: then the older save is kept). Win/Loss: the result line lands
    ~40 ms after 'Game Over' (or ~1 s before shutdown when leaving), so wait up to `wait` s for it."""
    snap = {"v": None}
    def on_start():
        cur = load_config()
        if after_match_cfg(cur)["mode"] != "resume": snap["v"] = None; return
        s = sp.snapshot(); ours = set(cur["playlists"].values())
        if s and (s.get("custom") or s.get("ctx")) in ours: return
        snap["v"] = s if s else None                           # playing or paused: both come back after the match
        if snap["v"]: log("After match: saved pre-match music for Resume (%s)" % (s.get("ctx") or s.get("track")))
    def song_end(n, uri, first):
        """Wait until the Win / Loss pick is done: a song when it ends (or you skip it), a playlist after its first
        track. False = cancelled: you paused, a new match started, or something else took over the player."""
        dur = None; started = False; cur = first; t0 = time.time(); ctr = set(custom_tracks(uri)) if is_custom(uri) else set()
        due = 0.0                                                  # next Spotify check (1 s ticks stay local)
        while True:
            time.sleep(1.0)
            if t.match_n != n: log("After match: new match - cancelled"); return False
            if time.time() < due: continue
            c, st = sp._api("GET", "/me/player"); song_end.calls = getattr(song_end, "calls", 0) + 1   # (tests)
            if c != 200 or not isinstance(st, dict): continue
            item = (st.get("item") or {}); iu = item.get("uri"); ctx = (st.get("context") or {}).get("uri")
            if dur is None and item.get("duration_ms"): dur = item["duration_ms"]
            if uri.startswith("spotify:track:"): mine = iu == uri
            elif is_custom(uri): mine = (iu == cur) if cur else (iu in ctr and not ctx)      # custom list: its first song
            else: mine = ctx == uri and (cur is None or iu == cur)
            if mine:
                started = True; cur = cur or iu
                if not st.get("is_playing"):
                    if (st.get("progress_ms") or 0) == 0: return True          # finished and stopped
                    log("After match: Spotify paused by you - doing nothing"); return False
                if dur and (st.get("progress_ms") or 0) >= dur - 1500: time.sleep(1.5); return True
                if dur: due = time.time() + max(0.0, min(5.0, (dur - (st.get("progress_ms") or 0)) / 1000.0 - 3.0))   # mid-song: every 5 s, tight near the end
            elif started:
                return True                                                    # next track / skipped: done
            elif time.time() - t0 > 15: log("After match: Win / Loss pick did not start"); return True
            if time.time() - t0 > (dur or 600000) / 1000.0 + 30: return True
    def run(n):
        try:
            sp.clear_hold()                                                # a mid-match pause hold never outlives the match
            set_now_playing(None)                                          # match over: no age row is playing
            cur = load_config(); am = after_match_cfg(cur); mode = am["mode"]; fade = float(cur.get("fade_seconds", 2))
            if not cur.get("enabled", True): sp.hand_back("Disabled"); return
            if am["wl"]:
                t0 = time.time()
                while t.result is None and time.time() - t0 < wait and t.match_n == n: time.sleep(0.2)
            if t.match_n != n: return                                      # a new match already started
            if sp.user_paused(): sp.clear_hold(); log("After match: Spotify paused by you - doing nothing"); return
            sp.clear_hold()
            if am["wl"]:
                r = t.result; pick = am["win"] if r == 1 else am["loss"] if r == 0 else ""
                log("After match: %s" % ({1: "victory", 0: "defeat"}.get(r, "no final result")))
                if pick:
                    log("After match: play %s first" % pick)
                    if pick.startswith("spotify:track:"): sp.set_mode(repeat="off")
                    sp.play_any(pick, fade)
                    if not song_end(n, pick, None): return
                    if t.match_n != n: return
                    fade = min(fade, 1.0)                                      # song already ended: short handover
            uri = None
            if mode == "resume":
                s, snap["v"] = snap["v"], None
                if s and s.get("playing"): log("After match: resume pre-match music"); sp.restore(s, fade); return
                if s: log("After match: load pre-match music back, paused"); sp.restore_paused(s, fade); return
                log("After match: nothing saved to resume")
            elif mode == "playlist": uri = am["playlist"]
            if uri and is_playable(uri):
                log("After match: play %s" % uri); sp.play_any(uri, fade); return
            log("After match: stop (fade out and pause)"); sp.fade_pause(fade); sp.hand_back("After match")
        except Exception as e: log("After match failed: %r" % e)
    t.on_start = on_start
    t.on_end = lambda n: threading.Thread(target=run, args=(n,), daemon=True).start()
    return snap

def on_game_event(self, event):
    """Switch playlists for one generic game event. The adapter supplies key and civ."""
    kind = event.kind
    if kind == "lobby":
        return
    if getattr(self, "catching_up", False) and kind in ("match_start", "age", "joined"):
        return                                         # reading old log lines: state only, never music
    if kind == "match_start":
        log("Match started -> Dark Age playlist")
        if self.on_start and not self.catching_up and not self.replay:
            try: self.on_start()
            except Exception as e: log("After match snapshot failed: %r" % e)
        getattr(self.play, "start", self.play)(event.key, event.civ)   # match start / join: always play, even if Spotify was paused before
    elif kind == "age":
        if event.reason == "up_start":
            log("YOU are aging up to %s -> %s playlist" % (event.age, event.key))
        else:
            log("YOU reached %s -> %s playlist" % (event.age, event.key))
        self.play(event.key, event.civ)
    elif kind == "match_end":
        log("Match over")
        if self.on_end and not self.catching_up and not self.replay: self.on_end(self.match_n)
    elif kind == "joined":
        log("Joined mid-match, you are in %s" % event.age)
        getattr(self.play, "start", self.play)(event.key, event.civ)   # match start / join: always play, even if Spotify was paused before
    elif kind == "session_reset":
        cb = getattr(self, "on_session_reset", None)
        if cb:
            try: cb()
            except Exception as e: log("Session reset hook failed: %r" % e)

