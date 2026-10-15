# e2e: fresh 1.0.9 TEST install -> 1.0.9's own auto-updater pulls a locally served 1.1 release -> verify migration. Sandbox only.
$ErrorActionPreference = "Continue"; $S = "$env:TEMP\sbx"; $RS = "C:\Users\Capstar\Tools\aoe4-spotify-rs"; $SRC = "C:\Users\Capstar\Tools\aoe4-spotify-src"
$PY = "$SRC\.venv\Scripts\python.exe"; $R = "$S\Roaming"; $D109 = "$R\AoE4Spotify"; $D11 = "$R\AoE4Spotify-1.1"; $APP = "$env:LOCALAPPDATA\Programs\AoE4 Spotify TEST"
$res = @(); function ok($n, $c) { $script:res += ("{0}  {1}" -f ($(if ($c) {"PASS"} else {"FAIL"}), $n)) }
if (Test-Path $APP) { "TEST install already present - abort"; exit 1 }
foreach ($d in "$R","$D109\covers","$S\steam\userdata\1\config","$S\srv") { mkdir $d -Force | Out-Null }
# fake 1.0.9 user data (copied from 1.1's import of the real 1.0.9 files) + a FAKE token
Copy-Item "$env:APPDATA\AoE4Spotify-1.1\config.json","$env:APPDATA\AoE4Spotify-1.1\playlist_names.json" $D109
Copy-Item "$env:APPDATA\AoE4Spotify-1.1\covers\*" "$D109\covers"
'{"access_token": "SBX_FAKE_ACCESS", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "SBX_FAKE_REFRESH_TOKEN_0123456789", "scope": "x", "expires_at": 1760000000.25}' | Set-Content "$D109\token.json" -NoNewline
Set-Content "$S\steam\userdata\1\config\localconfig.vdf" "`"UserLocalConfigStore`"`n{`n`t`"Software`"`n`t{`n`t`t`"Valve`"`n`t`t{`n`t`t`t`"Steam`"`n`t`t`t{`n`t`t`t`t`"apps`"`n`t`t`t`t{`n`t`t`t`t`t`"1466860`"`n`t`t`t`t`t{`n`t`t`t`t`t`t`"LaunchOptions`"`t`t`"-nomovies -dev`"`n`t`t`t`t`t}`n`t`t`t`t}`n`t`t`t}`n`t`t}`n`t}`n}" -NoNewline
Set-Content "$S\cfg.lua" "{ setting = `"musicvolume`", variantFloat = 0.70000 },`n{ setting = `"sfxvolume`", variantFloat = 1.00000 }" -NoNewline
$env:APPDATA = $R
foreach ($p in "AOE4SPOTIFY_","AOE4S_") { Set-Item "env:${p}TEST" "1"; Set-Item "env:${p}STEAM_PATH" "$S\steam"; Set-Item "env:${p}STEAM_PROC" "dummysteam.exe"; Set-Item "env:${p}GAME_CFG" "$S\cfg.lua"; Set-Item "env:${p}GAME_PROC" "dummygame.exe"; Set-Item "env:${p}MUTEX_SUFFIX" "_sbx" }
$env:AOE4SPOTIFY_UPDATE_API = "http://127.0.0.1:8765/latest.json"
$lo = { (Select-String "$S\steam\userdata\1\config\localconfig.vdf" -Pattern LaunchOptions).Line.Trim() }
$mv = { if ((Get-Content "$S\cfg.lua" -Raw) -match 'musicvolume", variantFloat = ([0-9.]+)') { $Matches[1] } }
$c109 = Get-Content "$D109\config.json" -Raw | ConvertFrom-Json; $ncov = (Get-ChildItem "$D109\covers" -File).Count
$tokHash = (Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes("SBX_FAKE_REFRESH_TOKEN_0123456789")))).Hash

"== 1. fresh 1.0.9 TEST install (silent)"
$p = Start-Process "$S\AoE4 Spotify TEST Setup.exe" -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/LOG=$S\inst109.log" -PassThru; $p.WaitForExit(); Start-Sleep 3
ok "1.0.9 installed (PyInstaller _internal present)" (Test-Path "$APP\_internal")
ok "1.0.9 set the launch option, kept -nomovies -dev: $(& $lo)" ((& $lo) -like '*AoE4 Spotify TEST\\AoE4 Spotify.exe\" %command% -nomovies -dev"')
ok "1.0.9 muted game music (0.70 saved next to its exe): now $(& $mv)" (((& $mv) -eq "0.00000") -and (Test-Path "$APP\game_music.json"))
Get-CimInstance Win32_Process -Filter "Name='AoE4 Spotify.exe'" | ? { $_.ExecutablePath -like "$APP*" } | % { Stop-Process -Id $_.ProcessId -Force }

"== 2. serve 1.1 as a GitHub-style release"
$asset = "$S\srv\AoE4.Spotify.Setup-1.1.0.exe"; Copy-Item "$RS\out\AoE4 Spotify TEST Setup 1.1.0.exe" $asset
$sha = (Get-FileHash $asset -Algorithm SHA256).Hash.ToLower(); $size = (Get-Item $asset).Length
@{ tag_name = "v1.1.0"; assets = @(@{ name = "AoE4.Spotify.Setup-1.1.0.exe"; size = $size; digest = "sha256:$sha"; browser_download_url = "http://127.0.0.1:8765/AoE4.Spotify.Setup-1.1.0.exe" }) } | ConvertTo-Json -Depth 5 | Set-Content "$S\srv\latest.json"
$srv = Start-Process $PY -ArgumentList "-m","http.server","8765","--bind","127.0.0.1","--directory","$S\srv" -PassThru -WindowStyle Hidden; Start-Sleep 2

"== 3. 1.0.9's own auto_update() (switcher path: check, download + size/sha256 check, silent_install /FROMSWITCHER=1)"
@"
import sys, contextlib; sys.path.insert(0, r'$SRC')
from aoe4spotify.core import updater
from aoe4spotify.core.runtime import VERSION
class T:
    def match_lock(self): return contextlib.nullcontext()
    def between_matches(self): return True
print('1.0.9 VERSION', VERSION, 'check ->', (updater.check_update() or {}).get('version'))
print('auto_update returned', updater.auto_update(T()))
"@ | Set-Content "$S\upd.py"
& $PY "$S\upd.py" 2>&1
$t0 = Get-Date
do { Start-Sleep 2; $v = (Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{0C1D7A52-93E4-4B6F-A1D2-7E55C0FFEE01}_is1" -ea 0).DisplayVersion
     $busy = Get-Process | ? { $_.Name -like "AoE4.Spotify.Setup-1.1.0*" -or ($_.Name -like "*.tmp" -and $_.Path -like "*\Temp\is-*") } } while ((($v -ne "1.1.0") -or $busy) -and ((Get-Date) - $t0).TotalSeconds -lt 180)
Start-Sleep 4; "installer done after $([int]((Get-Date) - $t0).TotalSeconds)s"

"== 4. verify"
ok "Apps & features entry now 1.1.0 (same AppId: in-place upgrade)" ($v -eq "1.1.0")
ok "1.1 exe installed (Rust build, same size as target\release)" ((Get-Item "$APP\AoE4 Spotify.exe").Length -eq (Get-Item "$RS\target\release\aoe4spotify.exe").Length)
ok "1.0.9 files gone (_internal, source)" (-not (Test-Path "$APP\_internal") -and -not (Test-Path "$APP\source"))
ok "launch option unchanged, still 1.1 exe + your options: $(& $lo)" ((& $lo) -like '*AoE4 Spotify TEST\\AoE4 Spotify.exe\" %command% -nomovies -dev"')
ok "game music still muted: $(& $mv)" ((& $mv) -eq "0.00000")
$imp = Get-Content "$D11\import.json" -Raw | ConvertFrom-Json
ok "import verified (import.json ok=true, cleaned=true)" ($imp.ok -and $imp.cleaned)
$i11 = Get-Content "$D11\intros.json" -Raw | ConvertFrom-Json; $c11 = Get-Content "$D11\config.json" -Raw | ConvertFrom-Json
ok "custom songs $($c109.custom_songs.Count)/$($i11.custom_songs.Count), presets $($c109.intro_presets.Count)/$($i11.intro_presets.Count), age lists $(@($c109.intro_pools.PSObject.Properties).Count)/$(@($i11.intro_pools.PSObject.Properties).Count), playlists $(@($c109.playlists.PSObject.Properties).Count)/$(@($c11.playlists.PSObject.Properties).Count)" (($c109.custom_songs.Count -eq $i11.custom_songs.Count) -and ($c109.intro_presets.Count -eq $i11.intro_presets.Count) -and (@($c109.intro_pools.PSObject.Properties).Count -eq @($i11.intro_pools.PSObject.Properties).Count) -and (@($c109.playlists.PSObject.Properties).Count -eq @($c11.playlists.PSObject.Properties).Count))
ok "covers $ncov/$((Get-ChildItem "$D11\covers" -File).Count)" ($ncov -eq (Get-ChildItem "$D11\covers" -File).Count)
$t11 = Get-Content "$D11\token.json" -Raw | ConvertFrom-Json
ok "Spotify login carried over (refresh token hash matches, expires_at=0 -> refresh on first use; value not printed)" (((Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($t11.refresh_token)))).Hash -eq $tokHash) -and ($t11.expires_at -eq 0))
ok "saved music level carried over (0.7) and removed from install dir" (((Get-Content "$D11\game_music.json" -Raw | ConvertFrom-Json).level -eq 0.7) -and -not (Test-Path "$APP\game_music.json"))
ok "real playback on" ((Get-Content "$D11\settings.json" -Raw | ConvertFrom-Json).real_playback -eq $true)
$left = Test-Path $D109; if ($left) { "   1.0.9 data folder still there (open update log): $((Get-ChildItem $D109 -r -File | % Name) -join ', ')" }
$pp = Start-Process "$APP\AoE4 Spotify.exe" -ArgumentList "--panel" -PassThru; Start-Sleep 6; Stop-Process -Id $pp.Id -Force -ea 0
ok "1.0.9 data folder removed (after verified import; leftover log finished on first start)" (-not (Test-Path $D109))
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut("$([Environment]::GetFolderPath('Desktop'))\AoE4 Spotify TEST.lnk")
ok "desktop shortcut -> 1.1 exe --panel, app.ico" (($lnk.TargetPath -eq "$APP\AoE4 Spotify.exe") -and ($lnk.Arguments -eq "--panel") -and ($lnk.IconLocation -like "*app.ico*"))
ok "no panel/switcher left running after silent update (--attach without game exits)" (-not (Get-CimInstance Win32_Process -Filter "Name='AoE4 Spotify.exe'" | ? { $_.ExecutablePath -like "$APP*" }))

"== 5. never update while AoE4 runs (silent run waits; WebView2 bootstrapper path forced)"
Copy-Item "$env:WINDIR\System32\PING.EXE" "$S\dummygame.exe"; $g = Start-Process "$S\dummygame.exe" -ArgumentList "-n","300","127.0.0.1" -PassThru -WindowStyle Hidden
$env:AOE4S_TEST_WV2_MISSING = "1"; $u = Start-Process $asset -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/FROMSWITCHER=1","/LOG=$S\upd2.log" -PassThru; Start-Sleep 12
ok "setup waits while the game runs (still running, log says waiting, nothing touched)" ((-not $u.HasExited) -and (Select-String "$S\upd2.log" -Pattern "waiting until it closes" -Quiet))
Stop-Process -Id $g.Id -Force; $u.WaitForExit(120000) | Out-Null; Remove-Item env:AOE4S_TEST_WV2_MISSING
ok "after the game closed it installed (exit $($u.ExitCode))" ($u.HasExited -and $u.ExitCode -eq 0)
ok "WebView2 bootstrapper ran when the runtime is missing: $((Select-String "$S\upd2.log" -Pattern 'WebView2 bootstrapper exit code.*' | % { $_.Matches[0].Value }))" (Select-String "$S\upd2.log" -Pattern "WebView2 bootstrapper exit code" -Quiet)

"== 6. uninstall 1.1 (silent)"
$un = Start-Process "$APP\unins000.exe" -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -PassThru; $un.WaitForExit(); $t0 = Get-Date
while ((Test-Path $APP) -and ((Get-Date) - $t0).TotalSeconds -lt 60) { Start-Sleep 1 }
ok "launch option restored exactly: $(& $lo)" ((& $lo) -eq '"LaunchOptions"		"-nomovies -dev"')
ok "game music restored to your 0.70: $(& $mv)" ((& $mv) -eq "0.70000")
ok "install dir + Apps & features entry gone" ((-not (Test-Path $APP)) -and -not (Test-Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{0C1D7A52-93E4-4B6F-A1D2-7E55C0FFEE01}_is1"))

Stop-Process -Id $srv.Id -Force -ea 0
Remove-Item "$([Environment]::GetFolderPath('Desktop'))\AoE4 Spotify TEST.lnk","$([Environment]::GetFolderPath('Programs'))\AoE4 Spotify TEST.lnk" -ea 0
"`n== RESULT"; $res; "{0}/{1} passed" -f ($res | ? { $_ -like "PASS*" }).Count, $res.Count
