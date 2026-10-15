# single instance + start modes + RAM/CPU/startup, sandboxed, hidden desktop
$ErrorActionPreference = "Continue"; $EXE = "C:\Users\Capstar\Tools\aoe4-spotify-rs\target\release\aoe4spotify-slint.exe"
$S = "$env:TEMP\sbx_modes"; Remove-Item -Recurse -Force $S -EA 0; mkdir "$S\Roaming","$S\Local","$S\steam" -Force | Out-Null
Copy-Item -Recurse "$env:APPDATA\AoE4Spotify-1.1" "$S\Roaming\AoE4Spotify-1.1"; Remove-Item "$S\Roaming\AoE4Spotify-1.1\token.json" -EA 0
Set-Content "$S\cfg.lua" 'setting = "musicvolume", variantFloat = 0.50000'; Copy-Item "$env:WINDIR\System32\PING.EXE" "$S\aoe4s_dummy_game.exe"
if (-not ("HD" -as [type])) { Add-Type -Path "$env:TEMP\hd.cs" }
$env:APPDATA = "$S\Roaming"; $env:LOCALAPPDATA = "$S\Local"; $env:AOE4S_TEST = "1"; $env:AOE4S_GAME_PROC = "aoe4s_dummy_game.exe"; $env:AOE4S_GAME_CFG = "$S\cfg.lua"
$env:AOE4S_STEAM_PATH = "$S\steam"; $env:AOE4S_STEAM_PROC = "dummysteam.exe"; $env:AOE4S_STEAM_EXE = "$S\nosteam.exe"; $env:AOE4S_ARP = "HKCU\Software\AoE4SpotifyBtrTest\ARP"
$env:AOE4S_DESKTOP = "$S\desk"; $env:AOE4S_UPDATE_API = "http://127.0.0.1:9/none"; $env:AOE4S_DRYOPEN = "$S\opened.txt"; $env:AOE4S_MUTEX_SUFFIX = "_modes"; $env:AOE4S_FAKESP = "1"
$res = @(); function ok($n, $c) { $script:res += ("{0}  {1}" -f ($(if ($c) {"PASS"} else {"FAIL"}), $n)) }
function exits($a, $sec) { $id = [HD]::Start($EXE, $a); $t = Get-Date; while ((Get-Process -Id $id -EA 0) -and ((Get-Date) - $t).TotalSeconds -lt $sec) { Start-Sleep -m 100 }; $alive = [bool](Get-Process -Id $id -EA 0); if ($alive) { Stop-Process -Id $id -Force }; -not $alive }
# startup: 5 cold-ish runs, time to visible window
$ts = @(); foreach ($i in 1..5) { $sw = [Diagnostics.Stopwatch]::StartNew(); $id = [HD]::Start($EXE, "--panel"); while (-not [HD]::Visible($id) -and $sw.ElapsedMilliseconds -lt 10000) { Start-Sleep -m 5 }; $ts += $sw.ElapsedMilliseconds; Stop-Process -Id $id -Force; Start-Sleep 1 }
"startup ms: $($ts -join ', ')"
$A = [HD]::Start($EXE, "--panel"); Start-Sleep 4
ok "--panel shows the panel (hidden desktop)" ([HD]::Visible($A))
ok "second --panel exits (single instance)" (exits "--panel" 8)
ok "no-args second start exits" (exits "" 8)
ok "--updated second start exits" (exits "--panel --updated" 8)
ok "first instance still running + visible" ((Get-Process -Id $A -EA 0) -and [HD]::Visible($A))
Start-Sleep 20; $p = Get-Process -Id $A; $c0 = $p.TotalProcessorTime.TotalMilliseconds; Start-Sleep 60; $p.Refresh(); $c1 = $p.TotalProcessorTime.TotalMilliseconds
"idle: WS {0:N1} MB, private {1:N1} MB, peak WS {2:N1} MB, CPU {3:N3}% (of all cores, 60 s), threads {4}" -f ($p.WorkingSet64/1MB), ($p.PrivateMemorySize64/1MB), ($p.PeakWorkingSet64/1MB), (($c1-$c0)/600/[Environment]::ProcessorCount), $p.Threads.Count
"child processes: $(@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$A").Count)"
Stop-Process -Id $A -Force; Start-Sleep 1
ok "--attach without game exits" (exits "--attach" 15)
$G = [HD]::Start($EXE, "`"$S\aoe4s_dummy_game.exe`" -n 4 127.0.0.1"); Start-Sleep 2
ok "game mode starts the game exe" ([bool](Get-Process aoe4s_dummy_game -EA 0))
$t = Get-Date; while ((Get-Process -Id $G -EA 0) -and ((Get-Date) - $t).TotalSeconds -lt 30) { Start-Sleep 1 }
ok "game mode exits after the game closes" (-not (Get-Process -Id $G -EA 0))
Get-Process aoe4s_dummy_game -EA 0 | Stop-Process -Force; Get-Process -Id $G -EA 0 | Stop-Process -Force
"`n== RESULT"; $res
