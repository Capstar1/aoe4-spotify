"""Which games the app knows. Game modules register themselves; the core asks for the active one.

The core never imports a game module directly. The entry file (aoe4_spotify.py) imports the games
it ships, and each one calls register() when it loads.
"""

_GAMES = {}
_ACTIVE = [None]
_HANDLER = [None]
DEFAULT_GAMES = ("aoe4spotify.games.aoe4",)   # loaded by name only if nothing registered yet

def register(adapter, make_active=None):
    """Add a game adapter. The first one registered becomes active unless make_active says otherwise."""
    _GAMES[adapter.key] = adapter
    if make_active or (make_active is None and _ACTIVE[0] is None):
        _ACTIVE[0] = adapter
    if _HANDLER[0] is not None:
        adapter.connect(_HANDLER[0])
    return adapter

def set_active(key):
    _ACTIVE[0] = _GAMES[key]
    return _ACTIVE[0]

def games():
    return dict(_GAMES)

def active():
    """The game the switcher follows."""
    if _ACTIVE[0] is None:
        import importlib
        for name in DEFAULT_GAMES:
            importlib.import_module(name)
    if _ACTIVE[0] is None:
        raise RuntimeError("No game adapter registered")
    return _ACTIVE[0]

def set_event_handler(handler):
    """The core's handler(tracker, event); connected to every adapter, now and later."""
    _HANDLER[0] = handler
    for g in _GAMES.values():
        g.connect(handler)
