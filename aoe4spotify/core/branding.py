"""App identity in one place: names, URI/share prefixes, URLs. Values must stay identical across versions:
share codes (SHARE_PREFIX), saved custom lists (LIST_PREFIX), the settings folder (APP_ID) and window/mutex names
depend on them. A different game build changes these here (and its adapter), not in the core modules."""
APP_NAME = "AoE4 Spotify"                      # shown to people: window titles, dialogs, login pages
APP_ID = "AoE4Spotify"                         # %APPDATA% folder, mutex / window-lock names, HTTP user agent
URI_SCHEME = "aoe4s"                           # our own pseudo-URIs next to spotify:...
LIST_PREFIX = URI_SCHEME + ":list:"            # custom song lists: aoe4s:list:<id>
LIKED_URI = URI_SCHEME + ":liked"              # Liked Songs pseudo-playlist
SHARE_PREFIX = "AOE4S"                         # intro preset share codes: AOE4S<ver>:<payload>
USER_AGENT = "AoE4-Spotify"                    # GitHub API / downloads
SETUP_FILE = "AoE4.Spotify.Setup-%s.exe"       # downloaded installer (auto update)
SETUP_FILE_MANUAL = APP_NAME + " Setup %s.exe" # downloaded installer (Update button)
STARTUP_LNK = APP_NAME + ".lnk"
GITHUB_REPO = "Capstar1/aoe4-spotify"
GITHUB_URL = "https://github.com/" + GITHUB_REPO
RELEASES_URL = GITHUB_URL + "/releases"
LATEST_API = "https://api.github.com/repos/" + GITHUB_REPO + "/releases/latest"
ACCESS_PREFIX = "https://capstar.app/api/aoe4-spotify/"
ACCESS_URL = ACCESS_PREFIX + "access-request"
