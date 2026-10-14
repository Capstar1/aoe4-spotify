"""Composition root: wire the active game adapter to Spotify and run the process.
The core never imports a game module; it talks to games.registry.active().
"""

import os, sys, threading, time
from aoe4spotify.core.access import access_dialog, access_status
from aoe4spotify.core.byo import byo_dialog
def good_to_go(*a, **k):                           # UI loads only when a window opens (the in-game switcher never needs it)
    from aoe4spotify.core.ui.gtg import good_to_go as f; return f(*a, **k)
def panel(*a, **k):
    from aoe4spotify.core.ui.panel import panel as f; return f(*a, **k)
from aoe4spotify.core.playback import PauseWatch, set_now_playing, boss_age, install_after_match, make_switcher, on_game_event, pick_boss_track
from aoe4spotify.core.runtime import FROZEN, child_env, clean_env, entry_py, install_crash_log, log, single_instance, switcher_running, wait_single_instance
from aoe4spotify.core.branding import STARTUP_LNK
from aoe4spotify.core.settings import ConfigMissing, load_config, using_own_app
from aoe4spotify.core.spotify import STORE_APP, Spotify, SpotifySession, _spotify_protocol_registered, local_guard_restore
from aoe4spotify.core.updater import auto_update, silent_install
from aoe4spotify.games.registry import active as game, set_event_handler

def attach_if_running():
    """App opened (panel, after an update...) while the game runs without a switcher: start one for that game (no relaunch)."""
    try:
        if os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX") and not os.environ.get("AOE4SPOTIFY_ATTACH_TEST"): return False  # tests
        if not game().running() or not load_config().get("enabled", True) or switcher_running(): return False
        import subprocess
        cmd = [sys.executable, "--attach"] if FROZEN else [sys.executable, entry_py(), "--attach"]
        subprocess.Popen(cmd, env=clean_env(), creationflags=0x08000000); return True
    except Exception as e: log("Attach failed: %r" % e); return False
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
    try: st["steam"] = game().launch_option_is_set()
    except Exception as e: log("Launch option check failed: %r" % e)
    return st
def open_panel_process():
    import subprocess
    cmd = [sys.executable, "--panel"] if FROZEN else [sys.executable, entry_py(), "--panel"]
    subprocess.Popen(cmd, env=child_env())
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
            nxt = []
            if using_own_app():
                byo_dialog(None, problem=True, on_saved=lambda: nxt.append("retry"), on_shared=lambda: nxt.append("retry"))
            else:
                access_dialog(None, on_allowed=lambda: nxt.append("ok"), on_own=lambda: nxt.append("retry"))
            if "ok" in nxt:
                pass
            elif nxt:
                sp = Spotify(load_config()); continue
            else:
                return
        st = setup_status(sp)
        again = []
        good_to_go(st, on_retry=lambda: again.append(1), fix=lambda: game().fix_launch_option())
        if not again: return
SPOTIFY_WAKE_MAX = 45      # s: longest we hold back starting Spotify while the game boots
def wake_spotify_after_game(sp, g, log_path, since, poll=1.0, max_wait=SPOTIFY_WAKE_MAX):
    """Start Spotify (if no device) only once the game is through its own start: never in the same moment as the
    game launch. Game started by us (since = launch time): wait until it writes its new log (it is up and talking to
    Steam), at most max_wait s, or stop if it closed. Background thread only; never blocks or delays the game."""
    t0 = time.time()
    while since and time.time() - t0 < max_wait:
        try:
            if os.path.getmtime(log_path) >= since: break
        except OSError: pass
        if not g.running(): return False
        time.sleep(poll)
    try: return sp.ensure_device()
    except Exception as e: log("Spotify wake failed: %r" % e); return False
def remove_old_startup_shortcut():
    lnk = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", STARTUP_LNK)
    if os.path.exists(lnk): os.remove(lnk); log("Removed old Startup shortcut")
def main():
    install_crash_log()
    try: return _main()
    except ConfigMissing as e: log(str(e)); return    # broken install: log it, never a crash popup
def _main():
    args = sys.argv[1:]
    if args[:1] == ["--set-launch-option"]:
        g = game(); g.fix_launch_option(); g.music_sync(load_config().get("enabled", True)); return   # no-op close if Setup already closed Steam
    if args[:1] == ["--remove-launch-option"]: g = game(); g.remove_launch_option(); g.music_sync(False); return
    if args[:1] == ["--fade-selftest"]:                # diagnostics: is the local fader usable? (reads only)
        sess = SpotifySession.find(); msg = "local fader: " + ("Spotify session found, volume %.2f" % sess.get() if sess else "not available")
        try:
            import tkinter as _tk; from tkinterdnd2 import TkinterDnD; _r = _tk.Tk(); _r.withdraw(); TkinterDnD._require(_r); _r.destroy(); msg += "; drag-in: ok"
        except Exception as ex: msg += "; drag-in: %r" % ex
        log(msg)
        try: open(os.path.join(os.environ.get("TEMP", "."), "aoe4_fade_selftest.txt"), "w").write(msg)
        except Exception: pass
        return
    if args[:1] == ["--fire-preview"]: panel(preview=True); return   # dev view of the row fire (own temp settings, see entry file)
    if args[:1] == ["--panel"]: attach_if_running(); panel(); return        # (--panel --updated: just upgraded, shows "Updated to x.y")
    cfg = load_config()
    local_guard_restore()
    if args[:1] == ["--dry-run"]:
        game().dry_run(cfg, lambda k, civ=None: log("   [dry-run] would play %s%s: %s" % (k, (" (%s intro for %s: %s)" % (k, civ, pick_boss_track(cfg, civ, k))) if civ and boss_age(cfg, k) else "", cfg["playlists"].get(k))), args)
        return
    remove_old_startup_shortcut()
    sp = Spotify(cfg)
    if not args:
        # Started by hand / installer Finish page: log in to Spotify, show "You're good to go", exit.
        attach_if_running(); login_flow(cfg); return
    if args[:1] == ["--attach"]:                     # app opened while AoE4 already runs: follow that game
        if not cfg.get("enabled", True) or not game().running(): return
        if not single_instance(): return
        if not sp.tok: log(game().label + " is running but you are not logged in to Spotify - switcher not attached"); return
        log(game().label + " already running - attaching the music switcher")
    else:
        # Started by Steam with the game command (%command%) as args: start the game first.
        import subprocess
        game_dir = os.path.dirname(args[0]) if os.path.isfile(args[0]) else None
        try: game().music_sync(cfg.get("enabled", True))      # game reads its music volume at launch (quick file edit)
        except Exception as e: log("Music volume sync failed (game starts anyway): %r" % e)
        launched_at = time.time() - 2                  # log older than this = previous session
        subprocess.Popen(args, env=child_env(), cwd=game_dir, close_fds=True)   # the game keeps Steam's variables; nothing else does
        log("Started game: %s" % " ".join(args))
        if not cfg.get("enabled", True): log("Disabled in the app - game started, doing nothing else"); return
        if not wait_single_instance(): log("Another switcher is already running - exiting"); return
        if not sp.tok:
            try: sp.login()
            except SystemExit as e: log("Continuing without Spotify login (%s) - log in from the app and the music starts" % e)
    g = game()
    t0 = time.time()
    while not g.running():                      # wait for the game process (max 5 min)
        if time.time() - t0 > 300: log("%s did not start within 5 minutes - exiting" % g.label); return
        time.sleep(3)
    log("%s is running" % g.label)
    threading.Thread(target=wake_spotify_after_game, args=(sp, g, g.log_path(cfg), locals().get("launched_at")), daemon=True).start()
    play, jobs = make_switcher(sp)
    path = g.log_path(cfg)
    t = g.make_tracker(cfg, play); t.start_delay = 3.0
    g.prepare_tracker(t, args, path)
    t.replay_music = lambda: bool(load_config().get("music_in_replays", False))   # 'Music in replays' (cog menu), read live
    install_after_match(t, sp)
    t.on_session_reset = lambda: (sp.clear_hold(), set_now_playing(None))    # a held age playlist never outlives its session
    _on_start = t.on_start
    t.on_start = lambda: jobs.put((_on_start, ()))                           # snapshot before the Dark Age switch, off the lock
    upd = {}
    def _upd(): time.sleep(8); upd["setup"] = auto_update(t)                # after catch-up: we know if a match is on
    threading.Thread(target=_upd, daemon=True).start()
    def stop_check():
        if not load_config().get("enabled", True) and getattr(sp, "_user_mode", None): sp.clear_hold(); sp.hand_back("Disabled")
        return not g.running()
    done = []
    threading.Thread(target=PauseWatch().run, args=(lambda: bool(done),), daemon=True).start()   # row glow sleeps while you pause
    g.follow(path, t, stop=stop_check, skip_older_than=locals().get("launched_at"))   # returns ~10s after the game closes
    log("%s closed - exiting" % g.label)
    done.append(1)
    set_now_playing(None)
    sp.clear_hold()
    try: sp.hand_back("Game closed")
    except Exception as e: log("Hand back failed: %r" % e)
    time.sleep(2); g.music_sync(load_config().get("enabled", True))   # game rewrote its settings on exit: re-mute / restore
    time.sleep(3)                                     # let a running fade finish
    if upd.get("setup") and os.path.isfile(upd["setup"]):
        log("Auto-update: game closed - installing now"); silent_install(upd["setup"])

set_event_handler(on_game_event)
