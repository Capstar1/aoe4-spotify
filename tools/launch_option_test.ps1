cd C:\Users\Capstar\Tools\aoe4-spotify-rs
cargo build --release -p aoe4spotify 2>&1 | Select -Last 1
$S="$env:TEMP\lot"; Remove-Item $S -r -fo -ea 0; mkdir "$S\inst","$S\steam\userdata\1\config","$S\R" | Out-Null
Copy-Item target\release\aoe4spotify.exe "$S\inst\AoE4 Spotify.exe"
$env:APPDATA="$S\R"; $env:AOE4S_TEST="1"; $env:AOE4S_STEAM_PATH="$S\steam"; $env:AOE4S_STEAM_PROC="dummysteam.exe"; $env:AOE4S_GAME_CFG="$S\cfg.lua"; $env:AOE4S_GAME_PROC="dummygame.exe"; $env:AOE4S_MUTEX_SUFFIX="_lot"
Set-Content "$S\cfg.lua" '{ setting = "musicvolume", variantFloat = 0.00000 },' -NoNewline
$v="$S\steam\userdata\1\config\localconfig.vdf"; $me=("$S\inst\AoE4 Spotify.exe").Replace('\','\\')
function lo { (Select-String $v -Pattern '"LaunchOptions"').Line.Trim() }
function run($a) { $p=Start-Process "$S\inst\AoE4 Spotify.exe" -ArgumentList $a -PassThru; $p.WaitForExit(30000) | Out-Null }
function vdf($val) { Set-Content $v "`"UserLocalConfigStore`"`n{`n`"Software`"{`"Valve`"{`"Steam`"{`"apps`"{`"1466860`"{`n`t`"LaunchOptions`"`t`t`"$val`"`n}}}}}`n}" -NoNewline; Remove-Item "$S\inst\launch_option_backup.json" -ea 0 }
$o11='\\\"C:\\\\Old\\\\AoE4 Spotify 1.1\\\\AoE4 Spotify.exe\\\"'.Replace('\\\\','\\').Replace('\\\"','\"')
$cases = @(
 @("doubled", "\`"$me\`" \`"C:\\Old\\AoE4 Spotify 1.1\\AoE4 Spotify.exe\`" %command% -nomovies", "-nomovies"),
 @("old 1.1 path", "\`"C:\\Old\\AoE4 Spotify 1.1\\AoE4 Spotify.exe\`" %command% -nomovies -dev", "-nomovies -dev"),
 @("1.0.9 path", "\`"C:\\U\\Programs\\AoE4 Spotify\\AoE4 Spotify.exe\`" %command% +fps_max 144 -dev", "+fps_max 144 -dev"),
 @("plain user args", "-nomovies -x", "-nomovies -x"))
$fail=0
foreach ($c in $cases) { vdf $c[1]; run "--set-launch-option"; $a=lo; run "--set-launch-option"; $b=lo; run "--remove-launch-option"; $r=lo
  $want="`"LaunchOptions`"`t`t`"\`"$me\`" %command% $($c[2])`""; $okk = ($a -eq $want) -and ($b -eq $a) -and ($r -eq "`"LaunchOptions`"`t`t`"$($c[2])`"")
  if (-not $okk) { $fail++ }; "{0}  {1}: set={2} | remove={3}" -f ($(if($okk){"PASS"}else{"FAIL"}), $c[0], $a.Split("`t")[-1], $r.Split("`t")[-1]) }
# Steam rewrite-on-close: dummy steam that rewrites the vdf as it exits; the edit must land after it is fully gone
Copy-Item "$env:WINDIR\System32\cmd.exe" "$S\dummysteam.exe"; vdf "-nomovies"
$ds = Start-Process "$S\dummysteam.exe" -ArgumentList "/c","ping -n 4 127.0.0.1 >nul & copy /y `"$v`" `"$v.tmp`" >nul & copy /y `"$v.tmp`" `"$v`" >nul" -PassThru -WindowStyle Hidden
run "--set-launch-option"; Start-Sleep 1; $a=lo; $okk = $a -like "*$me*%command% -nomovies*"; if (-not $okk) { $fail++ }
"{0}  edit lands after Steam exits (its close-time rewrite doesn't undo it): {1}" -f ($(if($okk){"PASS"}else{"FAIL"}), $a.Split("`t")[-1])
"fails: $fail"
