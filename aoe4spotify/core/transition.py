"""'We are changing the music right now' marker, shared by the Spotify driver and the pause watcher.
Fades, switches, intro->playlist hand-overs and pauses we make go quiet on purpose: none of that is the
user pausing. While a transition runs, and for GRACE s after it, silence means nothing."""
import functools, threading, time
GRACE = 5.0
_lock = threading.Lock()
_st = {"n": 0, "until": 0.0}
def begin():
    with _lock: _st["n"] += 1
def end(grace=GRACE):
    with _lock: _st["n"] = max(0, _st["n"] - 1); _st["until"] = max(_st["until"], time.time() + grace)
def hold(seconds):
    """Quiet stretch we know is coming (an intro's fading outro): silence means nothing until now + seconds."""
    with _lock: _st["until"] = max(_st["until"], time.time() + seconds)
def active(now=None):
    now = time.time() if now is None else now
    with _lock: return _st["n"] > 0 or now < _st["until"]
def wrap(fn):
    """Decorator: the call is a transition (begin before, end + grace after, also on errors)."""
    @functools.wraps(fn)
    def w(*a, **k):
        begin()
        try: return fn(*a, **k)
        finally: end()
    return w
def reset():                                            # tests
    with _lock: _st["n"] = 0; _st["until"] = 0.0
