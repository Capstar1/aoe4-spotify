# AoE4 Spotify benchmark vs the 1.0.9 baseline: startup, idle RAM/CPU, hidden-switcher RAM, exe + installer size.
# Sandboxed (copied settings, no token, fake Spotify) on the hidden desktop; never touches the real install or the game.
# usage: powershell -File tools\bench.ps1 [-Exe target\release\aoe4spotify-slint.exe] [-Setup "out\AoE4 Spotify Setup 1.1.0.exe"] [-Tag after]
param([string]$Exe = "$PSScriptRoot\..\target\release\aoe4spotify-slint.exe", [string]$Setup = "$PSScriptRoot\..\out\AoE4 Spotify Setup 1.1.0.exe", [string]$Tag = "run")
$Exe = (Resolve-Path $Exe).Path
$S = "$env:TEMP\sbx_modes"; Remove-Item -Recurse -Force $S -EA 0; mkdir "$S\Roaming","$S\Local","$S\steam" -Force | Out-Null
Copy-Item -Recurse "$env:APPDATA\AoE4Spotify-1.1" "$S\Roaming\AoE4Spotify-1.1"; Remove-Item "$S\Roaming\AoE4Spotify-1.1\token.json" -EA 0
Set-Content "$S\cfg.lua" 'setting = "musicvolume", variantFloat = 0.50000'; Copy-Item "$env:WINDIR\System32\PING.EXE" "$S\aoe4s_dummy_game.exe"
if (-not ("HD" -as [type])) { Add-Type -Path "$env:TEMP\hd.cs" }
$env:APPDATA = "$S\Roaming"; $env:LOCALAPPDATA = "$S\Local"; $env:AOE4S_TEST = "1"; $env:AOE4S_GAME_PROC = "aoe4s_dummy_game.exe"; $env:AOE4S_GAME_CFG = "$S\cfg.lua"
$env:AOE4S_STEAM_PATH = "$S\steam"; $env:AOE4S_STEAM_PROC = "dummysteam.exe"; $env:AOE4S_STEAM_EXE = "$S\nosteam.exe"; $env:AOE4S_ARP = "HKCU\Software\AoE4SpotifyBtrTest\ARP"
$env:AOE4S_DESKTOP = "$S\desk"; $env:AOE4S_UPDATE_API = "http://127.0.0.1:9/none"; $env:AOE4S_DRYOPEN = "$S\opened.txt"; $env:AOE4S_MUTEX_SUFFIX = "_modes"; $env:AOE4S_FAKESP = "1"
$res = @(); function ok($n, $c) { $script:res += ("{0}  {1}" -f ($(if ($c) {"PASS"} else {"FAIL"}), $n)) }
$EXE = $Exe
$ts = @(); foreach ($i in 1..5) { $sw = [Diagnostics.Stopwatch]::StartNew(); $id = [HD]::Start($EXE, "--panel"); while (-not [HD]::Visible($id) -and $sw.ElapsedMilliseconds -lt 10000) { Start-Sleep -m 5 }; $ts += $sw.ElapsedMilliseconds; Stop-Process -Id $id -Force; Start-Sleep 1 }
$st = ($ts | sort)[2]
$A = [HD]::Start($EXE, "--panel"); Start-Sleep 20; $p = Get-Process -Id $A; $c0 = $p.TotalProcessorTime.TotalMilliseconds; Start-Sleep 30; $p.Refresh(); $c1 = $p.TotalProcessorTime.TotalMilliseconds
$ws = $p.WorkingSet64 / 1MB; $pv = $p.PrivateMemorySize64 / 1MB; $cpu = ($c1 - $c0) / 300 / [Environment]::ProcessorCount; Stop-Process -Id $A -Force; Start-Sleep 1
# hidden switcher (game mode with a dummy game): working set 10 s after start
$G = [HD]::Start($EXE, "`"$S\aoe4s_dummy_game.exe`" -n 30 127.0.0.1"); Start-Sleep 10; $hp = Get-Process -Id $G -EA 0; $hws = if ($hp) { $hp.WorkingSet64 / 1MB } else { [double]::NaN }; $hvis = [HD]::Visible($G)
Get-Process aoe4s_dummy_game -EA 0 | Stop-Process -Force; Get-Process -Id $G -EA 0 | Stop-Process -Force
$exeMB = (Get-Item $EXE).Length / 1MB; $set = if (Test-Path $Setup) { (Get-Item $Setup).Length / 1MB } else { [double]::NaN }
"[$Tag] startup ms (5 runs): $($ts -join ', ')"
"{0,-26}{1,12}{2,14}" -f "metric", "1.0.9", $Tag
"{0,-26}{1,12}{2,14:N1}" -f "RAM idle WS (MB)", "74.1", $ws
"{0,-26}{1,12}{2,14:N1}" -f "RAM idle private (MB)", "-", $pv
"{0,-26}{1,12}{2,14}" -f "RAM hidden switcher (MB)", "-", ("{0:N1}{1}" -f $hws, $(if ($hvis) { " (visible!)" } else { "" }))
"{0,-26}{1,12}{2,14:N3}" -f "CPU idle (%)", "0.26", $cpu
"{0,-26}{1,12}{2,14}" -f "startup median (ms)", "~300", $st
"{0,-26}{1,12}{2,14:N2}" -f "exe size (MB)", "-", $exeMB
"{0,-26}{1,12}{2,14:N2}" -f "installer size (MB)", "26.4", $set