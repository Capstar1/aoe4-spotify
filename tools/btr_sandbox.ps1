# BTR sandbox runner: copies the real 1.1 data into a sandbox APPDATA, runs the Slint exe on a hidden desktop with
# every test guard (dummy game / Steam / ARP key / mutex suffix / dry page opening), waits, and syncs a refreshed
# Spotify token back only when the real file is untouched. Never prints file contents.
param([string]$Name = "s1", [string[]]$ExeArgs = @(), [hashtable]$Env = @{}, [int]$Timeout = 180, [switch]$NoToken, [switch]$NoWait, [string]$Exe = "")
$ErrorActionPreference = "Stop"
$root = "$env:TEMP\aoe4s_btr"; $sb = "$root\$Name"
if (-not $Exe) { $Exe = "C:\Users\Capstar\Tools\aoe4-spotify-rs\target\release\aoe4spotify-slint.exe" }
if (-not ("HD" -as [type])) { Add-Type -Path "$env:TEMP\hd.cs" }
Remove-Item -Recurse -Force $sb -EA 0; New-Item -ItemType Directory "$sb\Roaming","$sb\Local","$root\desk","$root\steam" -Force | Out-Null
$real = "$env:APPDATA\AoE4Spotify-1.1"
Copy-Item -Recurse $real "$sb\Roaming\AoE4Spotify-1.1"
if ($NoToken) { Remove-Item "$sb\Roaming\AoE4Spotify-1.1\token.json" -EA 0 }
$h0 = if (Test-Path "$real\token.json") { (Get-FileHash "$real\token.json").Hash } else { "" }
if (-not (Test-Path "$root\game.lua")) { Set-Content "$root\game.lua" 'setting = "musicvolume", variantFloat = 0.50000' }
$vars = @{ APPDATA = "$sb\Roaming"; LOCALAPPDATA = "$sb\Local"; AOE4S_TEST = "1"; AOE4S_GAME_PROC = "aoe4s_dummy_game.exe"; AOE4S_GAME_CFG = "$root\game.lua";
  AOE4S_ARP = "HKCU\Software\AoE4SpotifyBtrTest\ARP"; AOE4S_MUTEX_SUFFIX = "_btr"; AOE4S_DRYOPEN = "$sb\dry.txt"; AOE4S_DESKTOP = "$root\desk";
  AOE4S_STEAM_PATH = "$root\steam"; AOE4S_STEAM_EXE = "$root\steam\steam_dummy.exe"; AOE4S_STEAM_PROC = "steam_dummy.exe"; AOE4S_UPDATE_API = "http://127.0.0.1:9/none" }
foreach ($k in $Env.Keys) { $vars[$k] = $Env[$k] }
$old = @{}; foreach ($k in $vars.Keys) { $old[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $vars[$k]) }
try { $pid_ = [HD]::Start($Exe, ($ExeArgs -join " ")) } finally { foreach ($k in $old.Keys) { [Environment]::SetEnvironmentVariable($k, $old[$k]) } }
if ($pid_ -le 0) { throw "start failed" }
$p = Get-Process -Id $pid_; $t0 = Get-Date
if ($NoWait) { return [pscustomobject]@{ Pid = $pid_; Sandbox = $sb } }
if (-not $p.WaitForExit($Timeout * 1000)) { Stop-Process -Id $pid_ -Force; "TIMEOUT: killed after $Timeout s" }
"exit $($p.ExitCode) after {0:N1} s" -f ((Get-Date) - $t0).TotalSeconds
# token: keep the real file valid if the sandbox refreshed (rotated) it
$st = "$sb\Roaming\AoE4Spotify-1.1\token.json"
if (-not $NoToken -and (Test-Path $st) -and $h0) { $h1 = (Get-FileHash $st).Hash; $hr = (Get-FileHash "$real\token.json").Hash
  if ($h1 -ne $h0 -and $hr -eq $h0) { Copy-Item $st "$real\token.json" -Force; "token: refreshed in the sandbox, synced back" } elseif ($h1 -eq $h0) { "token: unchanged" } else { "token: real file changed meanwhile, left alone" } }
