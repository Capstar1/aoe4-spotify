param($tag, $order, $n)
$d="$env:TEMP\cshot\cap"; $o="$d\$tag"; Remove-Item -Recurse -Force $o -EA 0; New-Item -ItemType Directory $o | Out-Null
$py="C:\Users\Capstar\Tools\aoe4-spotify-src\.venv\Scripts\python.exe"
$c=Start-Process $py -ArgumentList "`"$d\capw.py`"","`"$o`"" -PassThru -NoNewWindow -RedirectStandardOutput "$o\cap.log" -RedirectStandardError "$o\cap.err"
$env:AOE4S_SWITCHTEST=$o; if($order -ne "none"){$env:AOE4S_ORDER=$order}; $env:AOE4S_N="$n"; $env:APPDATA="$env:TEMP\cshot\cmp\appdata"
$h=Start-Process "C:\Users\Capstar\Tools\aoe4-spotify-rs\target\debug\aoe4spotify.exe" -PassThru
if (-not $h.WaitForExit(120000)) { Stop-Process -Id $h.Id -Force; "app killed" }
if (-not $c.WaitForExit(30000)) { Stop-Process -Id $c.Id -Force; "capture killed" }
gc "$o\cap.log","$o\cap.err"
& $py "$d\analyze.py" $o "$o\bad" 2>&1 | Select-String 'TOTAL|in-between frames: [1-9]' | select -First 8

