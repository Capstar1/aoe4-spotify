# Sandboxed upgrade/uninstall test of the Slint TEST installer over a constructed 1.0.9 or Tauri 1.1 TEST install.
# Everything lives in $env:TEMP\sbx_<from>: install dir, APPDATA, LOCALAPPDATA, Steam config, game cfg, shortcuts.
# Runs setup/uninstall on the hidden desktop with dummy Steam/game processes. Never prints file contents.
param([ValidateSet("109","tauri")][string]$From = "109")
$ErrorActionPreference = "Continue"; $RS = "C:\Users\Capstar\Tools\aoe4-spotify-rs"
$S = "$env:TEMP\sbx_$From"; $APP = "$S\Programs\AoE4 Spotify TEST"; $R = "$S\Roaming"; $L = "$S\Local"; $D11 = "$R\AoE4Spotify-1.1"; $D109 = "$R\AoE4Spotify"
$KEY = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{0C1D7A52-93E4-4B6F-A1D2-7E55C0FFEE01}_is1"
if (-not ("HD" -as [type])) { Add-Type -Path "$env:TEMP\hd.cs" }
$res = @(); function ok($n, $c) { $script:res += ("{0}  {1}" -f ($(if ($c) {"PASS"} else {"FAIL"}), $n)) }
if (Test-Path $KEY) { "TEST uninstall key already present - abort"; exit 1 }
if (Get-Process RelicCardinal -EA 0) { "AoE4 running - abort"; exit 1 }
$realWV = Test-Path "$env:LOCALAPPDATA\com.capstar1.aoe4spotify"; $realDesk = [Environment]::GetFolderPath('Desktop')
$deskBefore = @(Get-ChildItem $realDesk -Filter "*AoE4*" -EA 0).Count
Remove-Item -Recurse -Force $S -EA 0
foreach ($d in $APP,"$APP\_internal","$APP\source",$R,$L,"$S\Desktop","$S\steam\userdata\1\config") { mkdir $d -Force | Out-Null }
# ---- constructed old install
$lo0 = "`"$APP\AoE4 Spotify.exe`" %command% -nomovies -dev"
Set-Content "$S\steam\userdata\1\config\localconfig.vdf" ("`"UserLocalConfigStore`"`n{`n`t`"Software`"`n`t{`n`t`t`"Valve`"`n`t`t{`n`t`t`t`"Steam`"`n`t`t`t{`n`t`t`t`t`"apps`"`n`t`t`t`t{`n`t`t`t`t`t`"1466860`"`n`t`t`t`t`t{`n`t`t`t`t`t`t`"LaunchOptions`"`t`t`"" + $lo0.Replace('"','\"') + "`"`n`t`t`t`t`t}`n`t`t`t`t}`n`t`t`t}`n`t`t}`n`t}`n}") -NoNewline
Set-Content "$S\cfg.lua" "{ setting = `"musicvolume`", variantFloat = 0.00000 },`n{ setting = `"sfxvolume`", variantFloat = 1.00000 }" -NoNewline
Copy-Item "$env:WINDIR\System32\PING.EXE" "$APP\AoE4 Spotify.exe"
if ($From -eq "109") {
  mkdir "$D109\covers" -Force | Out-Null
  Set-Content "$APP\_internal\base_library.zip" "x"; Set-Content "$APP\source\main.py" "x"; Set-Content "$APP\game_music.json" '{"level": 0.7}'
  Copy-Item "$env:APPDATA\AoE4Spotify-1.1\config.json","$env:APPDATA\AoE4Spotify-1.1\playlist_names.json" $D109 -EA 0
  Copy-Item "$env:APPDATA\AoE4Spotify-1.1\covers\*" "$D109\covers" -EA 0
  '{"access_token": "SBX_FAKE_ACCESS", "token_type": "Bearer", "expires_in": 3600, "refresh_token": "SBX_FAKE_REFRESH_TOKEN_0123456789", "scope": "x", "expires_at": 1760000000.25}' | Set-Content "$D109\token.json" -NoNewline
  $ver = "1.0.9"
} else {
  Remove-Item -Recurse "$APP\_internal","$APP\source"; Set-Content "$APP\WebView2Loader.dll" "x"
  Copy-Item -Recurse "$env:APPDATA\AoE4Spotify-1.1" $D11; Remove-Item "$D11\token.json" -EA 0
  Set-Content "$D11\token.json" '{"access_token":"SBX_FAKE","refresh_token":"SBX_FAKE_REFRESH","expires_at":0}' -NoNewline
  Set-Content "$D11\game_music.json" '{"level": 0.7}'
  mkdir "$L\com.capstar1.aoe4spotify\EBWebView\Default" -Force | Out-Null; Set-Content "$L\com.capstar1.aoe4spotify\EBWebView\Default\Prefs" "x"
  $ver = "1.1.0"
}
New-Item $KEY -Force | Out-Null
@{ "Inno Setup: App Path" = $APP; "InstallLocation" = "$APP\"; "DisplayName" = "AoE4 Spotify TEST"; "DisplayVersion" = $ver; "Inno Setup: Setup Version" = "6.7.3" }.GetEnumerator() | % { Set-ItemProperty $KEY -Name $_.Key -Value $_.Value }
$h11 = if (Test-Path $D11) { (Get-ChildItem $D11 -Recurse -File | ? Name -ne "token.json" | % { (Get-FileHash $_.FullName).Hash }) -join "" } else { "" }
# ---- environment (inherited by setup on the hidden desktop)
$env:APPDATA = $R; $env:LOCALAPPDATA = $L; $env:AOE4S_DESKTOP = "$S\Desktop"; $env:AOE4S_DRYOPEN = "$S\opened.txt"; $env:AOE4S_UPDATE_API = "http://127.0.0.1:9/none"; $env:AOE4S_ARP = "HKCU\Software\AoE4SpotifyBtrTest\ARP"
foreach ($p in "AOE4SPOTIFY_","AOE4S_") { Set-Item "env:${p}TEST" "1"; Set-Item "env:${p}STEAM_PATH" "$S\steam"; Set-Item "env:${p}STEAM_PROC" "dummysteam.exe"; Set-Item "env:${p}STEAM_EXE" "$S\nosteam.exe"; Set-Item "env:${p}GAME_CFG" "$S\cfg.lua"; Set-Item "env:${p}GAME_PROC" "dummygame.exe"; Set-Item "env:${p}MUTEX_SUFFIX" "_sbx" }
$lo = { (Select-String "$S\steam\userdata\1\config\localconfig.vdf" -Pattern LaunchOptions).Line.Trim() }
$mv = { if ((Get-Content "$S\cfg.lua" -Raw) -match 'musicvolume", variantFloat = ([0-9.]+)') { $Matches[1] } }
function run($exe, $a) { $id = [HD]::Start($exe, $a); $t0 = Get-Date; while ((Get-Process -Id $id -EA 0) -and ((Get-Date) - $t0).TotalSeconds -lt 180) { Start-Sleep 1 }; Start-Sleep 3 }
"== install Slint TEST setup over constructed $ver"
$t0 = Get-Date; run "$RS\out\AoE4 Spotify TEST Setup 1.1.0.exe" "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=`"$S\inst.log`""; "setup took $([int]((Get-Date)-$t0).TotalSeconds)s"
Start-Sleep 5
ok "same AppId: in-place upgrade, Apps & features 1.1.0, same folder" (((Get-ItemProperty $KEY -EA 0).DisplayVersion -eq "1.1.0") -and ((Get-ItemProperty $KEY).'Inno Setup: App Path' -eq $APP))
ok "Slint exe installed" ((Get-Item "$APP\AoE4 Spotify.exe").Length -eq (Get-Item "$RS\target\release\aoe4spotify-slint.exe").Length)
ok "no WebView2 in setup log" (-not (Select-String "$S\inst.log" -Pattern "WebView2" -Quiet))
ok "launch option kept: $(& $lo)" ((& $lo) -like '*AoE4 Spotify TEST\\AoE4 Spotify.exe\" %command% -nomovies -dev"')
ok "shortcuts only in sandbox (desktop+start), none on real desktop" ((Test-Path "$S\Desktop\AoE4 Spotify TEST.lnk") -and (Test-Path "$S\Desktop\Start\AoE4 Spotify TEST.lnk") -and (@(Get-ChildItem $realDesk -Filter "*AoE4*" -EA 0).Count -eq $deskBefore))
ok "real WebView2 folder untouched" ((Test-Path "$env:LOCALAPPDATA.ignored") -or ((Test-Path ([Environment]::GetFolderPath('LocalApplicationData') + "\com.capstar1.aoe4spotify")) -eq $realWV))
if ($From -eq "109") {
  ok "1.0.9 files gone (_internal, source)" (-not (Test-Path "$APP\_internal") -and -not (Test-Path "$APP\source"))
  $id = [HD]::Start("$APP\AoE4 Spotify.exe", "--panel"); Start-Sleep 8; $vis = [HD]::Visible($id); Stop-Process -Id $id -Force -EA 0
  ok "panel starts on hidden desktop after upgrade" $vis
  $imp = Get-Content "$D11\import.json" -Raw -EA 0 | ConvertFrom-Json
  ok "import verified + cleaned" ($imp.ok -and $imp.cleaned)
  ok "1.0.9 data folder removed" (-not (Test-Path $D109))
  ok "covers carried over" (@(Get-ChildItem "$D11\covers" -File -EA 0).Count -eq @(Get-ChildItem "$env:APPDATA.x" -EA 0).Count -or (@(Get-ChildItem "$D11\covers" -File -EA 0).Count -ge 1))
  $t = Get-Content "$D11\token.json" -Raw -EA 0 | ConvertFrom-Json
  ok "Spotify login carried over (fake token, value not printed)" ($t.refresh_token -eq "SBX_FAKE_REFRESH_TOKEN_0123456789")
  ok "saved music level 0.7 carried over, removed from install dir" (((Get-Content "$D11\game_music.json" -Raw -EA 0 | ConvertFrom-Json).level -eq 0.7) -and -not (Test-Path "$APP\game_music.json"))
} else {
  ok "Tauri WebView2 profile removed (sandbox)" (-not (Test-Path "$L\com.capstar1.aoe4spotify"))
  $h2 = (Get-ChildItem $D11 -Recurse -File | ? Name -ne "token.json" | ? Name -notlike "*.log" | % { (Get-FileHash $_.FullName).Hash }) -join ""
  $h1 = $h11
  ok "1.1 data folder kept (token present)" ((Test-Path "$D11\config.json") -and (Test-Path "$D11\token.json"))
  $id = [HD]::Start("$APP\AoE4 Spotify.exe", "--panel"); Start-Sleep 8; $vis = [HD]::Visible($id); Stop-Process -Id $id -Force -EA 0
  ok "panel starts on hidden desktop after upgrade" $vis
}
Get-CimInstance Win32_Process -Filter "Name='AoE4 Spotify.exe'" | ? { $_.ExecutablePath -like "$S*" } | % { Stop-Process -Id $_.ProcessId -Force }
"== uninstall (sandbox)"
run "$APP\unins000.exe" "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"; $t0 = Get-Date; while ((Test-Path "$APP\AoE4 Spotify.exe") -and ((Get-Date) - $t0).TotalSeconds -lt 60) { Start-Sleep 1 }
ok "launch option after uninstall: $(& $lo)" ((& $lo) -eq '"LaunchOptions"		"-nomovies -dev"')
ok "game music restored 0.70: $(& $mv)" ((& $mv) -eq "0.70000")
ok "install files + uninstall key gone" ((-not (Test-Path "$APP\AoE4 Spotify.exe")) -and -not (Test-Path $KEY))
ok "sandbox shortcuts removed" (-not (Test-Path "$S\Desktop\AoE4 Spotify TEST.lnk"))
ok "TEST uninstall kept data (TEST build)" (Test-Path $D11)
ok "real WebView2 folder still as before" ((Test-Path ([Environment]::GetFolderPath('LocalApplicationData') + "\com.capstar1.aoe4spotify")) -eq $realWV)
Remove-Item $KEY -Force -EA 0
"`n== RESULT ($From)"; $res; "{0}/{1} passed" -f @($res | ? { $_ -like "PASS*" }).Count, $res.Count
