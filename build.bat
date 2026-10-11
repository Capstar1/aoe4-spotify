@echo off
rem Build the app exe and the installer from this folder. Needs Python 3.11+ and Inno Setup 6.
python -m venv .venv
.venv\Scripts\python -m pip install pyinstaller
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name "AoE4 Spotify" aoe4_spotify_friend.py
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" setup.iss
echo Done: out\AoE4 Spotify Setup.exe
