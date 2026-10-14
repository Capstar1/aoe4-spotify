@echo off
rem Build the app exe and the installer from this folder. Needs Python 3.11+ and Inno Setup 6.
python -m venv .venv
.venv\Scripts\python -m pip install pyinstaller pillow pycaw tkinterdnd2
.venv\Scripts\python make_icon.py
.venv\Scripts\pyinstaller --noconfirm --onedir --windowed --name "AoE4 Spotify" --icon assets\app.ico --add-data "assets;assets" --add-data "config.json;." --hidden-import pycaw.pycaw --collect-submodules comtypes --collect-submodules aoe4spotify --collect-all tkinterdnd2 aoe4_spotify.py
rem README screenshots are not part of the app
rmdir /s /q "dist\AoE4 Spotify\_internal\assets\screenshots" 2>nul
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" setup.iss
echo Done: out\AoE4 Spotify Setup.exe
