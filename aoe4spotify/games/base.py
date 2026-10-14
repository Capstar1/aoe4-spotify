"""Events a game adapter can emit. The core decides what to play."""

class GameEvent:
    """Something that happened in a game.

    kind:
      lobby         a lobby slot was recognised as the local player
      match_start   a match the local player is in has started
      age           the local player began or finished an age change
      match_end     that match ended
      joined        the app attached to a match already in progress
      session_reset the game log was recreated (back to the menus)
    """
    def __init__(self, kind, key=None, age=None, reason=None, civ=None, slot=None):
        self.kind = kind
        self.key = key          # playlist key the core already understands (dark/feudal/castle/imperial)
        self.age = age          # game's own age name, for the log line
        self.reason = reason    # "up_start" or "up_done" on age events
        self.civ = civ
        self.slot = slot


class GameAdapter:
    """What the core needs from a game. Subclass it in games/<game>.py and call registry.register(adapter).

    The core never imports a game module; it only talks to the active adapter through these methods.
    """
    key = "game"              # short id, e.g. "aoe4"
    name = "Game"             # full name for people
    label = "Game"            # short name used in log lines ("AoE4 is running")
    process = ""              # the game's process name, e.g. "RelicCardinal.exe"
    events = ("lobby", "match_start", "age", "match_end", "joined", "session_reset")
    phases = ()               # ((playlist key, label), ...) in match order, e.g. (("dark", "Dark"), ...)
    intro_phases = None       # phase keys that can have an intro song (default: all phases)
    default_intro_phase = None  # the phase whose intros start from the built-in default pools and is on by
                              # default (others start empty / off). None = the last intro phase.
    intro_group_label = "BUILT-IN"  # label over the built-in intro songs in the editor tray
    intro_pack = None         # optional: the built-in songs fold behind one emblem in the editor tray:
                              # {"name": ..., "emblem": file under asset_dir, "frame": "spiked8"|"ring", "color": "#rrggbb"}
    launcher = ""             # launcher that starts the game (e.g. "Steam"); "" = none / unknown
    factions = ()             # ((faction key, label), ...) shown as rows in the intro editor
    intro_songs = ()          # ((key, song, character, spotify track uri, ring colour), ...) built-in intro songs
    asset_dir = "assets"      # under the app's assets root: portraits/<song key>.jpg, flags/<faction>.png

    def intro_phase_keys(self):
        return tuple(self.intro_phases) if self.intro_phases is not None else tuple(k for k, _ in self.phases)
    def default_intro_key(self):
        """Phase key with default pools (see default_intro_phase)."""
        keys = self.intro_phase_keys()
        return self.default_intro_phase if self.default_intro_phase in keys else (keys[-1] if keys else None)
    def pack_emblem_path(self):
        import os
        from aoe4spotify.core.runtime import ASSETS
        return os.path.join(ASSETS, self.asset_dir, (self.intro_pack or {}).get("emblem", ""))
    def portrait_path(self, song_key):
        import os
        from aoe4spotify.core.runtime import ASSETS
        return os.path.join(ASSETS, self.asset_dir, "portraits", song_key + ".jpg")
    def flag_path(self, faction):
        import os
        from aoe4spotify.core.runtime import ASSETS
        p = os.path.join(ASSETS, self.asset_dir, "flags", faction + ".png")
        if not os.path.exists(p): p = os.path.join(ASSETS, self.asset_dir, "flags", "_unknown.png")
        return p

    # --- process / log -------------------------------------------------------------------
    def running(self):
        """True while the game process runs."""
        from aoe4spotify.core.runtime import proc_running
        return bool(self.process) and proc_running(self.process)
    def log_path(self, cfg):
        """The log file the tracker follows (cfg may override it)."""
        raise NotImplementedError
    def make_tracker(self, cfg, play):
        """A tracker object: feed(line), emit(...) -> on_event, lock, in_match, catching_up, replay, match_n,
        result, on_start/on_end/on_session_reset hooks. Replays are the adapter's business: the core sets
        tracker.replay_music (callable -> bool, 'Music in replays'); off = silence replays, on = follow them,
        paced so seeking never spams switches."""
        raise NotImplementedError
    def prepare_tracker(self, tracker, args, path):
        """Game-specific setup after make_tracker (launch args, side files). Default: nothing."""
    def follow(self, path, tracker, stop=None, skip_older_than=None):
        """Read the log and feed the tracker until stop() is true."""
        raise NotImplementedError
    def dry_run(self, cfg, play, args):
        """--dry-run <log> [...]: replay a log without Spotify calls."""
        raise NotImplementedError

    # --- events --------------------------------------------------------------------------
    def connect(self, handler):
        """Route the tracker's events to handler(tracker, event)."""

    # --- updater hooks -------------------------------------------------------------------
    def update_lock(self, tracker):
        """Held while deciding to install an update, so a match cannot start mid-install."""
        return tracker.match_lock()
    def safe_to_update(self, tracker):
        """True when an update may install now (between matches). Caller holds update_lock."""
        return tracker.between_matches()
    def in_match(self, tracker):
        return bool(getattr(tracker, "in_match", False))

    # --- launch option / game settings ---------------------------------------------------
    def launch_option_is_set(self): return None
    def set_launch_option(self): pass
    def fix_launch_option(self):
        """Set the launch option, closing the launcher first if it needs that."""
        return self.set_launch_option()
    def remove_launch_option(self): pass
    def launcher_running(self): return False
    def music_sync(self, enabled, running=None):
        """Mute the game's own music while the app is enabled (restore it when not)."""
