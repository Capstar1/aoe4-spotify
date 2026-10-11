@echo off
rem Build the app exe and the installer from this folder. Needs Python 3.11+ and Inno Setup 6.
python -m venv .venv
.venv\Scripts\python -m pip install pyinstaller pillow
.venv\Scripts\python make_icon.py
.venv\Scripts\pyinstaller --noconfirm --onedir --windowed --name "AoE4 Spotify" --icon assets\app.ico --add-data "assets;assets" aoe4_spotify.py
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" setup.iss
echo Done: out\AoE4 Spotify Setup.exe
