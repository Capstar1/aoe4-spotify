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
