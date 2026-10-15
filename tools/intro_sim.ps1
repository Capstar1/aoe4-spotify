# Hidden-desktop sandbox: match start as japanese, then a feudal age-up.
# Asserts the fake Spotify log is intro, playlist, intro, playlist.
# Does not touch the real Spotify login, the real game log, or RelicCardinal.
$ErrorActionPreference = 'Stop'
$root = 'C:\Users\Capstar\Tools\aoe4-spotify-rs'
$exe = Join-Path $root 'target\release\aoe4spotify-slint.exe'
if (-not (Test-Path $exe)) { Write-Output 'FAIL missing release exe'; exit 1 }

$sand = Join-Path $env:TEMP 'aoe4s_intro_sim'
if (Test-Path $sand) { Remove-Item -Recurse -Force $sand }
$app = Join-Path $sand 'AoE4Spotify-1.1'
$logs = Join-Path $sand 'LogFiles'
New-Item -ItemType Directory -Force -Path $app, $logs, (Join-Path $sand 'Local'), (Join-Path $sand 'steam') | Out-Null

$utf8 = New-Object System.Text.UTF8Encoding $false
function Write-Utf8([string]$path, [string]$text) { [System.IO.File]::WriteAllText($path, $text, $utf8) }

$warn = Join-Path $sand 'warnings.log'
Write-Utf8 $warn ''
Write-Utf8 (Join-Path $logs 'DataCRC_sim.txt') "playermap: {`r`nsetupindex: [0]`r`nsimid: [1006]`r`n}`r`n"
Write-Utf8 (Join-Path $sand 'game.lua') "-- sandbox`r`n"
Write-Utf8 (Join-Path $app 'import.json') '{"ok":true,"cleaned":true}'
Write-Utf8 (Join-Path $app 'base.json') '{"client_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","boss_intro":{"enabled":true,"pools":{},"default":[]},"default_playlists":{"dark":"spotify:playlist:dark","feudal":"spotify:playlist:feudal","castle":"spotify:playlist:castle","imperial":"spotify:playlist:imperial"}}'
Write-Utf8 (Join-Path $app 'settings.json') '{"music_in_replays":false,"finish_song":false}'
Write-Utf8 (Join-Path $app 'intros.json') '{"intro_ages":{"dark":true,"feudal":true},"intro_pools":{"dark":{"japanese":["spotify:track:jpdark"]},"feudal":{"japanese":["spotify:track:jpfeud"]}}}'
Write-Utf8 (Join-Path $app 'token.json') '{"access_token":"sim","refresh_token":"sim","expires_at":4000000000}'
$cfg = @{
    enabled = $true
    fade_seconds = 0
    boss_intro_enabled = $true
    music_in_replays = $false
    log_path = $warn
    playlists = @{
        dark = 'spotify:playlist:dark'
        feudal = 'spotify:playlist:feudal'
        castle = 'spotify:playlist:castle'
        imperial = 'spotify:playlist:imperial'
    }
} | ConvertTo-Json -Depth 5 -Compress
Write-Utf8 (Join-Path $app 'config.json') $cfg

$env:APPDATA = $sand
$env:LOCALAPPDATA = Join-Path $sand 'Local'
$env:AOE4S_TEST = '1'
$env:AOE4S_GAME_PROC = 'aoe4s_intro_dummy.exe'
$env:AOE4S_LOGFILES = $logs
$env:AOE4S_MUTEX_SUFFIX = '_intro'
$env:AOE4S_GAME_CFG = Join-Path $sand 'game.lua'
$env:AOE4S_UPDATE_API = 'http://127.0.0.1:9/none'
$env:AOE4S_DRYOPEN = Join-Path $sand 'dryopen.txt'
$env:AOE4S_STEAM_PATH = Join-Path $sand 'steam'

$dummyExe = Join-Path $sand 'aoe4s_intro_dummy.exe'
Copy-Item "$env:SystemRoot\System32\ping.exe" $dummyExe -Force
Add-Type -Path "$env:TEMP\hd.cs"

function Wait-Plays([string]$path, [int]$n, [int]$sec, [int]$procId) {
    $until = (Get-Date).AddSeconds($sec)
    while ((Get-Date) -lt $until) {
        if (-not (Get-Process -Id $procId -ErrorAction SilentlyContinue)) { return 'dead' }
        if (Test-Path $path) {
            try { $lines = [System.IO.File]::ReadAllLines($path) } catch { $lines = @() }
            $plays = @($lines | Where-Object { $_ -like 'play *' })
            if ($plays.Count -ge $n) { return 'ok' }
        }
        Start-Sleep -Milliseconds 200
    }
    return 'timeout'
}

function Run-One([string]$mode) {
    $env:AOE4S_FAKESP = $mode
    $appLog = Join-Path $app 'aoe4_spotify.log'
    $fake = Join-Path $app 'fake_spotify.log'
    Write-Utf8 $warn ''
    foreach ($p in @($appLog, $fake, (Join-Path $app 'intro_last.json'))) { if (Test-Path $p) { Remove-Item $p -Force } }
    $dummy = 0
    $sw = 0
    $fail = ''
    try {
        $dummy = [HD]::Start($dummyExe, '-n 180 127.0.0.1')
        if ($dummy -le 0) { $fail = 'dummy did not start'; throw $fail }
        Start-Sleep -Milliseconds 400
        $sw = [HD]::Start($exe, '--attach')
        if ($sw -le 0) { $fail = 'switcher did not start'; throw $fail }

        $deadline = (Get-Date).AddSeconds(20)
        $watching = $false
        while ((Get-Date) -lt $deadline) {
            if (-not (Get-Process -Id $sw -ErrorAction SilentlyContinue)) { $fail = 'switcher exited before Watching'; throw $fail }
            if (Test-Path $appLog) {
                try { $t = [System.IO.File]::ReadAllText($appLog) } catch { $t = '' }
                if ($t.Contains('Watching') -and $t.Contains($warn)) { $watching = $true; break }
            }
            Start-Sleep -Milliseconds 200
        }
        if (-not $watching) { $fail = 'timed out waiting for Watching'; throw $fail }

        $open = @(
            'GAME -- Current Steam name is [Capstar]',
            '[Match Flow] GameApp::RequestGameBegin()',
            'GAME -- Human Player: 0 Capstar 111 0 japanese',
            'GAME -- Starting mission'
        ) -join "`r`n"
        [System.IO.File]::AppendAllText($warn, $open + "`r`n", $utf8)

        $darkWait = if ($mode -eq 'slow') { 40 } else { 25 }
        $feuWait = if ($mode -eq 'slow') { 30 } else { 20 }
        $dark = Wait-Plays $fake 2 $darkWait $sw
        if ($dark -ne 'ok') { $fail = "dark intro then playlist: $dark"; throw $fail }
        [System.IO.File]::AppendAllText($warn, "Age up started from dark_age to feudal_age for player id 6`r`n", $utf8)
        $feu = Wait-Plays $fake 4 $feuWait $sw
        if ($feu -ne 'ok') { $fail = "feudal intro then playlist: $feu"; throw $fail }

        $got = @([System.IO.File]::ReadAllLines($fake) | Where-Object { $_.Trim() -ne '' })
        $want = @(
            'repeat off',
            'play spotify:track:jpdark',
            'repeat context',
            'play spotify:playlist:dark',
            'repeat off',
            'play spotify:track:jpfeud',
            'repeat context',
            'play spotify:playlist:feudal'
        )
        if (($got -join "`n") -ne ($want -join "`n")) {
            $fail = "spotify order mismatch`nGOT:`n$($got -join "`n")`nWANT:`n$($want -join "`n")"
            throw $fail
        }
        Write-Output "PASS FAKESP=$mode intro -> playlist -> intro -> playlist"
        Write-Output ($got -join "`n")
        $script:oneOk = $true
        return
    }
    catch {
        if (-not $fail) { $fail = $_.Exception.Message }
        Write-Output "FAIL FAKESP=$mode $fail"
        if (Test-Path $fake) { Write-Output '--- fake_spotify.log ---'; Write-Output ([System.IO.File]::ReadAllText($fake)) }
        if (Test-Path $appLog) {
            $tail = @(Get-Content $appLog -Tail 40 -ErrorAction SilentlyContinue)
            Write-Output '--- aoe4_spotify.log ---'
            Write-Output ($tail -join "`n")
        }
        $script:oneOk = $false
        return
    }
    finally {
        foreach ($p in @($sw, $dummy)) {
            if ($p -gt 0) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue }
        }
    }
}

$pass = $true
foreach ($mode in @('1', 'slow')) {
    Write-Output "=== AOE4S_FAKESP=$mode ==="
    $script:oneOk = $false
    Run-One $mode
    if (-not $script:oneOk) { $pass = $false; break }
    Start-Sleep -Milliseconds 400
}
if (-not $pass) { exit 1 }
exit 0
