# single instance + start modes + RAM/CPU/startup, sandboxed, hidden desktop
param([string]$Out)
$ErrorActionPreference = "Continue"; $EXE = "C:\Users\Capstar\Tools\aoe4-spotify-rs\target\release\aoe4spotify-slint.exe"
$S = "$env:TEMP\sbx_modes"; Remove-Item -Recurse -Force $S -EA 0; mkdir "$S\Roaming","$S\Local","$S\steam" -Force | Out-Null
Copy-Item -Recurse "$env:APPDATA\AoE4Spotify-1.1" "$S\Roaming\AoE4Spotify-1.1"; Remove-Item "$S\Roaming\AoE4Spotify-1.1\token.json" -EA 0
Set-Content "$S\cfg.lua" 'setting = "musicvolume", variantFloat = 0.50000'; Copy-Item "$env:WINDIR\System32\PING.EXE" "$S\aoe4s_dummy_game.exe"
if (-not ("HD" -as [type])) { Add-Type -Path "$env:TEMP\hd.cs" }
$env:APPDATA = "$S\Roaming"; $env:LOCALAPPDATA = "$S\Local"; $env:AOE4S_TEST = "1"; $env:AOE4S_GAME_PROC = "aoe4s_dummy_game.exe"; $env:AOE4S_GAME_CFG = "$S\cfg.lua"
$env:AOE4S_STEAM_PATH = "$S\steam"; $env:AOE4S_STEAM_PROC = "dummysteam.exe"; $env:AOE4S_STEAM_EXE = "$S\nosteam.exe"; $env:AOE4S_ARP = "HKCU\Software\AoE4SpotifyBtrTest\ARP"
$env:AOE4S_DESKTOP = "$S\desk"; $env:AOE4S_UPDATE_API = "http://127.0.0.1:9/none"; $env:AOE4S_DRYOPEN = "$S\opened.txt"; $env:AOE4S_MUTEX_SUFFIX = "_modes"; $env:AOE4S_FAKESP = "1"
$res = @(); function ok($n, $c) { $script:res += ("{0}  {1}" -f ($(if ($c) {"PASS"} else {"FAIL"}), $n)) }
$env:AOE4S_SHOT=$Out; $id=[HD]::Start($EXE,"--panel"); $t=Get-Date; while((Get-Process -Id $id -EA 0) -and ((Get-Date)-$t).TotalSeconds -lt 20){Start-Sleep -m 200}; Get-Process -Id $id -EA 0 | Stop-Process -Force; "shot: $(Test-Path $Out)"
