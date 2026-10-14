"""The settings window, playlist picker, age-intro editor, and good-to-go screen.

The code lives in core/ui/ (split in 1.0.9). This module re-exports every name so older imports keep working.
"""

from aoe4spotify.core.ui.glow import GLOW_N, chip_px, even_px, ink_centre, render_glow
from aoe4spotify.core.ui.library import ROMAN, _G, AGES, Art, BUILTIN_SONGS, CIV_LIST, COVERS, LIB_SCOPES, LIKED_ID, LIKED_URI, NAMES_CACHE, RELEASES_URL, RE_PLAYLIST, SONGS, SONG_BY_URI, SW_H, SW_W, _MYLIB, _next_path, _pl_total, cover_file, custom_key, default_pool, fetch_track, fetch_tracks, http_get, lib_cover, lib_scopes_ok, liked_tracks, load_custom_songs, my_library, normalize_pools, now_playing, open_playlist, parse_track, parse_tracks, pick_image, playlist_total, search_tracks, song_sorted, store_track, track_cover, update_cover
from aoe4spotify.core.ui.widgets import GlassTip, ImageChops_offset, _Pen, _dashed_rr, _pen_icon, after_mouse_up, app_badge, canvas_rect, get_tip, install_edit_menu, mosaic_image, save_mosaic, set_app_icon
from aoe4spotify.core.ui.gtg import good_to_go
from aoe4spotify.core.ui.picker import list_picker
from aoe4spotify.core.ui.intros import pool_editor
from aoe4spotify.core.ui.panel import panel
from aoe4spotify.core.ui.panel import _g_app
import json, os, re, sys, threading, time, urllib.error, urllib.parse, urllib.request, webbrowser
from aoe4spotify.core.access import access_dialog, access_status
from aoe4spotify.core.byo import byo_dialog
from aoe4spotify.core.runtime import ASSETS, DATA, GITHUB_URL, HERE, ImageColor_rgb, LOGFILE, TOKEN, VERSION, atomic_write, child_env, dark_window, focus_window, log, note_window, release_window, reveal, set_canvas_height, single_window, win_hidden
from aoe4spotify.core.settings import CUSTOM_MAX, CUSTOM_PREFIX, DEFAULT_PRESET_NAME, INTRO_AGES, _LIVE_USER, after_match_cfg, apply_preset, apply_user, build_intros, custom_cover, custom_get, decode_preset, encode_preset, is_custom, load_config, load_user, load_user_settings, merge_user, migrate_intros_v2, preset_counts, preset_from_user, preset_key, preset_songs, save_user, unique_preset_name, user_presets, using_own_app
from aoe4spotify.core.spotify import Spotify
from aoe4spotify.core.updater import check_update, download_update, run_update
from aoe4spotify.games.registry import active as game
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageTk
