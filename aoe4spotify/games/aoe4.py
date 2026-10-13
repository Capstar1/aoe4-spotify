"""Age of Empires IV log adapter. Detects lobby, match, and age events and emits them.
"""

import os, re, threading, time
from aoe4spotify.core.runtime import log

from aoe4spotify.games.base import GameEvent

RE_HUMAN   = re.compile(r"GAME -- Human Player: (\d+) (.+) (\d+) (\d+) (\S+)$")
RE_STEAM   = re.compile(r"GAME -- Current Steam name is \[(.*)\]")
RE_PROFILE = re.compile(r'WebSocketConnection::ProcessMessages: message=\[0,"\w+",(\d+),')  # recipient = local profile id
RE_BEGIN   = re.compile(r"\[Match Flow\] GameApp::RequestGameBegin\(\)")
RE_START   = re.compile(r"GAME -- Starting mission")
RE_REPLAY  = re.compile(r"PlaybackSynchronization::")
RE_UPSTART = re.compile(r"Age up started from (\w+) to (\w+) for player id (\d+)")
RE_UPDONE  = re.compile(r"Age up complete from (\w+) for player id (\d+)")
RE_RESULT  = re.compile(r"Report sent for profileID\[(\d+)\] -> race=\[\d+\], result=\[(\d+)\]")   # 1 win, 0 loss, 3 not final
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
        self.my_id = None; self.started = {}; self.ages = {}; self.recent = []; self.humans = []; self.my_hidx = None
        self.lock = threading.Lock()
        self.result = None; self.match_n = 0; self.on_start = self.on_end = None   # After match hooks
        self.first_human = None; self.start_delay = 0.0; self.replay_session = False

    def emit(self, kind, key=None, age=None, reason=None, civ=None, slot=None):
        """Hand one detected event to the core. Catch-up still reaches self.play, which tail silences."""
        handler = getattr(self, "on_event", None)
        if handler:
            handler(GameEvent(kind, key=key, age=age, reason=reason, civ=civ, slot=slot))

    def match_lock(self):
        """Held across the silent-update decision so a match cannot start mid-install."""
        return self.lock

    def between_matches(self):
        """True when no match is being caught up or played. Caller holds match_lock."""
        return not self.in_match and not self.catching_up

    def is_player(self):
        """Conservative: only a match we are confidently IN. You matched a lobby 'Human Player' line (profile id or name),
        or a manual player_id is set, or you are the only human (vs AI) and no profile id says otherwise.
        Anything else (spectating, casting, a replay of someone else, unknown identity) = leave the music alone."""
        if isinstance(self.fixed_id, int) or self.my_slot is not None: return True
        if len(self.humans) == 1 and not self.me_profile and getattr(self, "first_human", None):
            sl, civ = self.first_human; self.my_slot, self.my_civ, self.my_hidx = sl, civ, 0
            log("Only human in the lobby - that's you (slot %d)" % sl)
            self.emit("lobby", slot=sl, civ=civ)
            return True
        return False

    def session_reset(self):
        """The game log was recreated (new game session): back to 'in the menus' - no match, age, player or hold."""
        self.in_match = self.replay = False; self.match_n += 1; self.result = None
        self.my_id = self.fixed_id if isinstance(self.fixed_id, int) else None; self.my_slot = None; self.my_hidx = None
        self.started.clear(); self.ages.clear(); self.recent.clear(); self.humans = []; self.first_human = None
        self.emit("session_reset")

    def reset(self):
        self.in_match = True; self.replay = False; self.result = None; self.match_n += 1
        self.my_id = self.fixed_id if isinstance(self.fixed_id, int) else None
        self.my_slot = None; self.begin_t = 0 if self.catching_up else time.time()
        self.started.clear(); self.ages.clear(); self.recent.clear(); self.humans = []; self.my_hidx = None; self.first_human = None

    def feed(self, line):
        with self.lock: self._feed(line.rstrip("\r\n"))

    def _feed(self, line):
        m = RE_STEAM.search(line)
        if m: self.me_name = m.group(1); self.me_profile = ""; log("Local Steam name: %s" % self.me_name)
        m = RE_PROFILE.search(line)
        if m and not self.me_profile:
            self.me_profile = m.group(1); log("Local AoE4 profile id: %s" % self.me_profile)
        m = RE_RESULT.search(line)
        if m:
            if m.group(1) == self.me_profile:
                self.result = int(m.group(2)); log("Match result for you: %s" % {1: "victory", 0: "defeat"}.get(self.result, "not final (%d)" % self.result))
            return
        if RE_BEGIN.search(line):
            self.reset(); log("Match loading - state reset")
            return
        m = RE_HUMAN.search(line)
        if m and m.group(3) not in self.humans:
            self.humans.append(m.group(3))
            if len(self.humans) == 1: self.first_human = (int(m.group(1)), m.group(5))
        if m and (m.group(3) == self.me_profile or (not self.me_profile and m.group(2) == self.me_name)):
            self.my_slot = int(m.group(1)); self.my_civ = m.group(5); self.my_hidx = self.humans.index(m.group(3)) if m.group(3) in self.humans else None
            if not self.me_profile and m.group(3).isdigit() and m.group(3) != "0":   # matched by Steam name: learn the profile id
                self.me_profile = m.group(3); log("Local AoE4 profile id (from lobby): %s" % self.me_profile)   # (Win / Loss result lines use it)
            log("You are lobby slot %s (%s), team %s" % (m.group(1), m.group(5), m.group(4)))
            self.emit("lobby", slot=self.my_slot, civ=self.my_civ)
            return
        if RE_REPLAY.search(line) and self.in_match:
            self.replay = True; log("Replay detected - ignoring this match")
            return
        if RE_START.search(line):
            if not self.in_match: self.reset()
            if self.replay or self.replay_session:
                self.replay = True; log("Replay - leaving the music alone"); return
            if not self.is_player():
                self.replay = True; log("Not confidently a player in this match (observing / unknown) - leaving the music alone")
                return
            self.resolve_id()
            if self.start_delay > 0 and not self.catching_up:      # replay markers can trail the start line: wait briefly
                n = self.match_n; threading.Timer(self.start_delay, self._late_start, args=(n,)).start(); return
            self._begin_music()
            return
        if RE_END.search(line) and self.in_match:
            self.in_match = False
            self.emit("match_end")
            return
        m = RE_UPSTART.search(line)
        if m:
            pid = int(m.group(3)); new = m.group(2)
            self.started[pid] = new
            # Earliest signal: fires when the age-up transition begins (~5s before "complete").
            if self.in_match and not self.replay:
                if self.my_id is None: self.resolve_id()
                if pid == self.my_id and new in KEY and self.ages.get(pid) != new:
                    self.ages[pid] = new
                    self.emit("age", key=KEY[new], age=new, reason="up_start", civ=getattr(self, "my_civ", None))
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
                self.emit("age", key=KEY[new], age=new, reason="up_done", civ=getattr(self, "my_civ", None))

    def _late_start(self, n):
        with self.lock:
            if self.match_n != n or not self.in_match or self.replay: log("Match start cancelled (replay / ended)"); return
            self._begin_music()

    def _begin_music(self):
        self.emit("match_start", key="dark", age="dark_age", civ=getattr(self, "my_civ", None))

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
            self.my_id = pick_id(slot_to_id(newest), self.my_slot, getattr(self, "my_hidx", None))
            log("Identified you as player id %s (slot %d, from %s)" % (self.my_id, self.my_slot, os.path.basename(newest)))
        except Exception as e:
            log("Could not read DataCRC player map: %s" % e)
def slot_to_id(path):
    """{setupindex: sim player id} from the playermap block (tolerant of spacing and field order)."""
    with open(path, encoding="utf-8", errors="replace") as f: t = f.read()
    i = t.index("playermap:"); j = t.find("{", i); blk = t[i:t.index("}", j if j >= 0 else i)]
    out, cur = {}, None
    for k, v in re.findall(r"(setupindex|simid)\s*:\s*\[\s*(-?\d+)\s*\]", blk):
        if k == "setupindex": cur = int(v)
        elif cur is not None: out[cur] = int(v) - 1000; cur = None
    return out
def pick_id(pmap, slot, hidx=None):
    """Lobby slot -> sim id. The playermap only lists HUMAN players, numbered 0.. in lobby order, so
    with AI in the lobby your slot (e.g. 1) is not your setupindex (0). Use your index among the
    "Human Player" lines first, then the raw slot, then the only entry."""
    if not pmap: return None
    if hidx is not None and hidx in pmap: return pmap[hidx]
    if slot in pmap: return pmap[slot]
    if len(pmap) == 1: return next(iter(pmap.values()))
    return None
CATCHUP_MAX = 2 * 1024 * 1024
def tail(path, tracker, stop=None, skip_older_than=None):
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
            with tracker.lock: tracker.session_reset()
        ino = key
        if not caught_up and skip_older_than and st.st_mtime < skip_older_than:
            # We just launched the game: this log is from the LAST session (the game recreates it in a moment).
            # Never replay its old matches; only follow what the new session writes.
            log("Game log is from the previous session - waiting for the new one")
            pos = st.st_size; caught_up = True; tracker.play = real_play; tracker.catching_up = False
        if not caught_up and pos == 0 and st.st_size > CATCHUP_MAX:
            # Huge log: who you are is near the top; the current match is in the tail. Read only those parts.
            with open(path, "rb") as f:
                head = f.read(256 * 1024); f.seek(st.st_size - CATCHUP_MAX); f.readline(); pos = f.tell()
            for line in head.decode("utf-8", errors="replace").splitlines():
                if RE_STEAM.search(line) or RE_PROFILE.search(line): tracker.feed(line)
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
                    tracker.emit("joined", key=KEY.get(age, "dark"), age=age)   # 1.0.7: no civ on join (no intro mid-match)
        if stop and time.time() - last_check > 10:
            last_check = time.time()
            if stop(): return
        time.sleep(0.25 if tracker.in_match else 0.5)       # in a match: notice Game Over / age-ups sooner
