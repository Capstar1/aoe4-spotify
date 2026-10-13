"""Composition root: wire the AoE4 adapter to Spotify and run the process.
"""

import os, sys, threading, time
from aoe4spotify.core.access import access_dialog, access_status
from aoe4spotify.core.byo import byo_dialog
from aoe4spotify.core.gui import good_to_go, panel
from aoe4spotify.core.playback import boss_age, install_after_match, make_switcher, on_game_event, pick_boss_track
from aoe4spotify.core.runtime import DEFAULT_LOG, FROZEN, child_env, entry_py, install_crash_log, log, single_instance, switcher_running, wait_single_instance
from aoe4spotify.core.settings import load_config, using_own_app
from aoe4spotify.core.spotify import STORE_APP, Spotify, SpotifySession, _spotify_protocol_registered, local_guard_restore
from aoe4spotify.core.updater import auto_update, silent_install
from aoe4spotify.games.aoe4 import RE_BEGIN, RE_START, Tracker, pick_id, slot_to_id, tail
from aoe4spotify.games.aoe4_setup import aoe_running, launch_option_is_set, music_sync, remove_launch_option, set_launch_option, with_steam_closed

def attach_if_running():
    """App opened (panel, after an update...) while AoE4 runs without a switcher: start one for that game (no relaunch)."""
    try:
        if os.environ.get("AOE4SPOTIFY_MUTEX_SUFFIX") and not os.environ.get("AOE4SPOTIFY_ATTACH_TEST"): return False  # tests
        if not aoe_running() or not load_config().get("enabled", True) or switcher_running(): return False
        import subprocess
        cmd = [sys.executable, "--attach"] if FROZEN else [sys.executable, entry_py(), "--attach"]
        subprocess.Popen(cmd, env=child_env(), creationflags=0x08000000); return True
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
    try: st["steam"] = launch_option_is_set()
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
        good_to_go(st, on_retry=lambda: again.append(1), fix=lambda: with_steam_closed(set_launch_option))
        if not again: return
def remove_old_startup_shortcut():
    lnk = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup", "AoE4 Spotify.lnk")
    if os.path.exists(lnk): os.remove(lnk); log("Removed old Startup shortcut")
def main():
    install_crash_log()
    args = sys.argv[1:]
    if args[:1] == ["--set-launch-option"]:
        with_steam_closed(set_launch_option); music_sync(load_config().get("enabled", True)); return   # no-op close if Setup already closed Steam
    if args[:1] == ["--remove-launch-option"]: remove_launch_option(); music_sync(False); return
    if args[:1] == ["--fade-selftest"]:                # diagnostics: is the local fader usable? (reads only)
        sess = SpotifySession.find(); msg = "local fader: " + ("Spotify session found, volume %.2f" % sess.get() if sess else "not available")
        try:
            import tkinter as _tk; from tkinterdnd2 import TkinterDnD; _r = _tk.Tk(); _r.withdraw(); TkinterDnD._require(_r); _r.destroy(); msg += "; drag-in: ok"
        except Exception as ex: msg += "; drag-in: %r" % ex
        log(msg)
        try: open(os.path.join(os.environ.get("TEMP", "."), "aoe4_fade_selftest.txt"), "w").write(msg)
        except Exception: pass
        return
    if args[:1] == ["--panel"]: attach_if_running(); panel(); return        # (--panel --updated: just upgraded, shows "Updated to x.y")
    cfg = load_config()
    local_guard_restore()
    if args[:1] == ["--dry-run"]:
        t = Tracker(cfg, lambda k, civ=None: log("   [dry-run] would play %s%s: %s" % (k, (" (%s intro for %s: %s)" % (k, civ, pick_boss_track(cfg, civ, k))) if civ and boss_age(cfg, k) else "", cfg["playlists"].get(k))))
        crcs = args[2:]
        for line in open(args[1], encoding="utf-8", errors="replace"):
            if RE_BEGIN.search(line) and crcs:
                t.crc_dir = None; t.feed(line); t.begin_t = 0
                t._crc = crcs.pop(0); continue
            if RE_START.search(line) and getattr(t, "_crc", None):
                t.my_id = pick_id(slot_to_id(t._crc), t.my_slot, getattr(t, "my_hidx", None))
                log("Identified you as player id %s (slot %s, from %s)" % (t.my_id, t.my_slot, os.path.basename(t._crc)))
            t.feed(line)
        return
    remove_old_startup_shortcut()
    sp = Spotify(cfg)
    if not args:
        # Started by hand / installer Finish page: log in to Spotify, show "You're good to go", exit.
        attach_if_running(); login_flow(cfg); return
    if args[:1] == ["--attach"]:                     # app opened while AoE4 already runs: follow that game
        if not cfg.get("enabled", True) or not aoe_running(): return
        if not single_instance(): return
        if not sp.tok: log("AoE4 is running but you are not logged in to Spotify - switcher not attached"); return
        log("AoE4 already running - attaching the music switcher")
    else:
        # Started by Steam with the game command (%command%) as args: start the game first.
        import subprocess
        game_dir = os.path.dirname(args[0]) if os.path.isfile(args[0]) else None
        music_sync(cfg.get("enabled", True))           # game reads its music volume at launch
        launched_at = time.time() - 2                  # log older than this = previous session
        subprocess.Popen(args, env=child_env(), cwd=game_dir)
        log("Started game: %s" % " ".join(args))
        if not cfg.get("enabled", True): log("Disabled in the app - game started, doing nothing else"); return
        if not wait_single_instance(): log("Another switcher is already running - exiting"); return
        if not sp.tok:
            try: sp.login()
            except SystemExit as e: log("Continuing without Spotify login (%s) - log in from the app and the music starts" % e)
    t0 = time.time()
    while not aoe_running():                    # wait for RelicCardinal.exe (max 5 min)
        if time.time() - t0 > 300: log("AoE4 did not start within 5 minutes - exiting"); return
        time.sleep(3)
    log("AoE4 is running")
    threading.Thread(target=sp.ensure_device, daemon=True).start()   # start Spotify now if closed
    play, jobs = make_switcher(sp)
    path = os.path.expandvars(cfg.get("log_path") or DEFAULT_LOG)
    t = Tracker(cfg, play); t.start_delay = 3.0
    if any(str(x).lower() in ("-replay", "/replay") for x in args):          # Steam launch option '-replay playback:...'
        t.replay_session = True; log("Game started to watch a replay - the music is left alone")
    t.crc_dir = os.path.join(os.path.dirname(path), "LogFiles")
    install_after_match(t, sp)
    t.on_session_reset = sp.clear_hold                                       # a held age playlist never outlives its session
    _on_start = t.on_start
    t.on_start = lambda: jobs.put((_on_start, ()))                           # snapshot before the Dark Age switch, off the lock
    upd = {}
    def _upd(): time.sleep(8); upd["setup"] = auto_update(t)                # after catch-up: we know if a match is on
    threading.Thread(target=_upd, daemon=True).start()
    def stop_check():
        if not load_config().get("enabled", True) and getattr(sp, "_user_mode", None): sp.clear_hold(); sp.hand_back("Disabled")
        return not aoe_running()
    tail(path, t, stop=stop_check, skip_older_than=locals().get("launched_at"))   # returns ~10s after the game closes
    log("AoE4 closed - exiting")
    sp.clear_hold()
    try: sp.hand_back("Game closed")
    except Exception as e: log("Hand back failed: %r" % e)
    time.sleep(2); music_sync(load_config().get("enabled", True))   # game rewrote its settings on exit: re-mute / restore
    time.sleep(3)                                     # let a running fade finish
    if upd.get("setup") and os.path.isfile(upd["setup"]):
        log("Auto-update: game closed - installing now"); silent_install(upd["setup"])

Tracker.on_event = on_game_event
