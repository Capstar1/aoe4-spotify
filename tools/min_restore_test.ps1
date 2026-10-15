# Minimize/restore repaint test. Hidden desktop, sandbox, no real Spotify and no Age of Empires IV.
# Capture is BitBlt from the screen DC (SRCCOPY|CAPTUREBLT), never PrintWindow.
# A magenta sheet sits behind the panel, so a dropped DWM surface shows through as #FF00FF.
# usage: powershell -File tools\min_restore_test.ps1 [-Exe path]
param([switch]$RunWorker, [string]$Exe, [string]$OutDir)
$ErrorActionPreference = 'Stop'

$DeskName = 'aoe4s_minr'
$DeskB = 'aoe4s_minr_b'

if (-not ('MinR' -as [type])) {
Add-Type -AssemblyName System.Drawing
$src = @"
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Threading;
public static class MinR {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateDesktop(string n, IntPtr d, IntPtr m, int f, uint a, IntPtr s);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr OpenDesktop(string n, int f, bool inh, uint a);
  [DllImport("user32.dll")] public static extern bool CloseDesktop(IntPtr h);
  [DllImport("user32.dll")] static extern bool SetThreadDesktop(IntPtr h);
  public delegate bool EP(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumDesktopWindows(IntPtr d, EP f, IntPtr l);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, System.Text.StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h, uint msg, IntPtr w, IntPtr l, uint f, uint ms, out IntPtr res);
  [DllImport("user32.dll")] static extern IntPtr GetDC(IntPtr h);
  [DllImport("user32.dll")] static extern IntPtr GetWindowDC(IntPtr h);
  [DllImport("user32.dll")] static extern int ReleaseDC(IntPtr h, IntPtr dc);
  [DllImport("user32.dll")] static extern IntPtr GetDesktopWindow();
  [DllImport("user32.dll")] static extern IntPtr OpenInputDesktop(int f, bool inh, uint a);
  [DllImport("user32.dll")] public static extern bool SwitchDesktop(IntPtr h);
  [DllImport("user32.dll")] static extern int GetSystemMetrics(int i);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern ushort RegisterClassExW(ref WC wc);
  [DllImport("user32.dll")] static extern IntPtr DefWindowProcW(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern IntPtr CreateWindowExW(uint ex, string cls, string name, uint st, int x, int y, int w, int h, IntPtr p, IntPtr m, IntPtr i, IntPtr lp);
  [DllImport("user32.dll")] static extern bool UpdateLayeredWindow(IntPtr h, IntPtr dst, ref PT pt, ref SZ sz, IntPtr src, ref PT spt, uint key, ref BL b, uint f);
  [DllImport("user32.dll")] static extern bool DestroyWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int hh, uint f);
  [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleDC(IntPtr dc);
  [DllImport("gdi32.dll")] static extern IntPtr CreateCompatibleBitmap(IntPtr dc, int w, int h);
  [DllImport("gdi32.dll")] static extern bool DeleteDC(IntPtr dc);
  [DllImport("gdi32.dll")] static extern IntPtr SelectObject(IntPtr dc, IntPtr o);
  [DllImport("gdi32.dll")] static extern bool DeleteObject(IntPtr o);
  [DllImport("gdi32.dll")] static extern IntPtr CreateDIBSection(IntPtr dc, ref BIH bi, uint u, out IntPtr bits, IntPtr s, uint o);
  [DllImport("gdi32.dll")] static extern bool BitBlt(IntPtr d, int x, int y, int w, int h, IntPtr s, int sx, int sy, int rop);
  [DllImport("dwmapi.dll")] static extern int DwmSetWindowAttribute(IntPtr h, int a, ref int v, int n);
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode)] public static extern bool CreateProcess(string app, System.Text.StringBuilder cmd, IntPtr pa, IntPtr ta, bool inh, uint fl, IntPtr env, string dir, ref SI si, out PI pi);
  [DllImport("kernel32.dll")] static extern IntPtr GetModuleHandleW(string n);
  public struct R { public int L, T, Rt, B; }
  [StructLayout(LayoutKind.Sequential)] struct PT { public int X, Y; }
  [StructLayout(LayoutKind.Sequential)] struct SZ { public int Cx, Cy; }
  [StructLayout(LayoutKind.Sequential)] struct BL { public byte Op, Flags, Alpha, Fmt; }
  [StructLayout(LayoutKind.Sequential)] struct BIH { public int Size, W, H; public short Planes, Bits; public int Comp, Img, Xp, Yp, Used, Imp; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct WC { public uint Size, Style; public IntPtr Proc; public int Cls, Wnd; public IntPtr Inst, Icon, Cur, Bg; public string Menu, Name; public IntPtr Sm; }
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] public struct SI { public int cb; public string r; public string desk; public string t; public int a,b,c,d,e,f,g,flags; public short sw, r2; public IntPtr r3, i, o, er; }
  [StructLayout(LayoutKind.Sequential)] public struct PI { public IntPtr hp, ht; public int pid, tid; }
  public static IntPtr Desk;
  static IntPtr Bg;
  public static void Open(string name) {
    Desk = CreateDesktop(name, IntPtr.Zero, IntPtr.Zero, 0, 0x10000000, IntPtr.Zero);
    if (Desk == IntPtr.Zero) Desk = OpenDesktop(name, 0, false, 0x10000000);
  }
  public static int Launch(string exe, string args, string desk) {
    var si = new SI(); si.cb = Marshal.SizeOf(typeof(SI)); si.desk = desk; PI pi;
    var cmd = new System.Text.StringBuilder("\"" + exe + "\" " + args);
    if (!CreateProcess(exe, cmd, IntPtr.Zero, IntPtr.Zero, false, 0, IntPtr.Zero, null, ref si, out pi)) return -1;
    return pi.pid;
  }
  public static IntPtr Find(IntPtr desk, int pid) {
    IntPtr found = IntPtr.Zero;
    EnumDesktopWindows(desk, (h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (p == (uint)pid && IsWindowVisible(h)) {
        var s = new System.Text.StringBuilder(256); GetWindowText(h, s, 256);
        if (s.ToString() == "AoE4 Spotify") found = h;
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
  public static void Sheet() {
    if (Bg != IntPtr.Zero) return;
    int w = GetSystemMetrics(0); int h = GetSystemMetrics(1);
    if (w < 200 || h < 200) { w = 1920; h = 1080; }
    var wc = new WC(); wc.Size = (uint)Marshal.SizeOf(typeof(WC)); wc.Proc = Marshal.GetFunctionPointerForDelegate(Proc); wc.Inst = GetModuleHandleW(null); wc.Name = "AoE4sMinrBg";
    RegisterClassExW(ref wc);
    Bg = CreateWindowExW(0x80000 | 0x08000000 | 0x80, wc.Name, wc.Name, 0x80000000, 0, 0, w, h, IntPtr.Zero, IntPtr.Zero, wc.Inst, IntPtr.Zero);
    IntPtr scr = GetDC(IntPtr.Zero); IntPtr mem = CreateCompatibleDC(scr);
    var bi = new BIH(); bi.Size = 40; bi.W = w; bi.H = -h; bi.Planes = 1; bi.Bits = 32;
    IntPtr bits; IntPtr bmp = CreateDIBSection(mem, ref bi, 0, out bits, IntPtr.Zero, 0);
    if (bmp != IntPtr.Zero && bits != IntPtr.Zero) {
      int n = w * h;
      for (int i = 0; i < n; i++) Marshal.WriteInt32(bits, i * 4, unchecked((int)0xFFFF00FF));
      IntPtr old = SelectObject(mem, bmp);
      var pt = new PT(); var spt = new PT(); var sz = new SZ(); sz.Cx = w; sz.Cy = h;
      var bl = new BL(); bl.Op = 0; bl.Alpha = 255; bl.Fmt = 1;
      UpdateLayeredWindow(Bg, scr, ref pt, ref sz, mem, ref spt, 0, ref bl, 2);
      SelectObject(mem, old); DeleteObject(bmp);
    }
    DeleteDC(mem); ReleaseDC(IntPtr.Zero, scr);
    ShowWindow(Bg, 8);
    SetWindowPos(Bg, (IntPtr)1, 0, 0, 0, 0, 0x13);
  }
  delegate IntPtr Wnd(IntPtr h, uint m, IntPtr w, IntPtr l);
  static readonly Wnd Proc = DefWindowProcW;
  public static void Raise(IntPtr panel) {
    if (Bg != IntPtr.Zero) SetWindowPos(Bg, (IntPtr)1, 0, 0, 0, 0, 0x13);
    if (panel != IntPtr.Zero) SetWindowPos(panel, IntPtr.Zero, 0, 0, 0, 0, 0x1 | 0x2 | 0x10);
  }
  public static IntPtr InputDesk() { return OpenInputDesktop(0, false, 0x10000000); }
  public static void Back(IntPtr user) { if (user != IntPtr.Zero) SwitchDesktop(user); }
  static Bitmap Blt(IntPtr src, int x, int y, int w, int h) {
    IntPtr mem = CreateCompatibleDC(src);
    IntPtr bmp = CreateCompatibleBitmap(src, w, h);
    IntPtr old = SelectObject(mem, bmp);
    BitBlt(mem, 0, 0, w, h, src, x, y, 0x00CC0020 | 0x40000000);
    SelectObject(mem, old);
    Bitmap img = Image.FromHbitmap(bmp);
    DeleteObject(bmp); DeleteDC(mem);
    return img;
  }
  // Screen DC of this thread's desktop. While the hidden desktop is not the input desktop, DWM
  // does not put the panel into that DC, so the grab switches to it for the blit and switches back.
  public static Bitmap Grab(IntPtr hwnd) {
    R r; if (!GetWindowRect(hwnd, out r)) return null;
    int w = r.Rt - r.L, h = r.B - r.T; if (w < 20 || h < 20 || w > 4000 || h > 4000) return null;
    Raise(hwnd);
    IntPtr user = InputDesk();
    bool flipped = false;
    if (Desk != IntPtr.Zero) flipped = SwitchDesktop(Desk);
    Bitmap img = null;
    try {
      if (flipped) Thread.Sleep(40);
      IntPtr scr = GetDC(IntPtr.Zero);
      img = Blt(scr, r.L, r.T, w, h);
      ReleaseDC(IntPtr.Zero, scr);
    } finally {
      if (flipped && user != IntPtr.Zero) SwitchDesktop(user);
      if (user != IntPtr.Zero) CloseDesktop(user);
    }
    return img;
  }
  public static double Diff(Bitmap a, Bitmap b) {
    if (a == null || b == null || a.Width != b.Width || a.Height != b.Height) return 100;
    int bad = 0, n = a.Width * a.Height;
    var ra = new Rectangle(0, 0, a.Width, a.Height);
    var ba = a.LockBits(ra, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
    var bb = b.LockBits(ra, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
    int stride = ba.Stride;
    unsafe_copy(ba.Scan0, bb.Scan0, a.Height, a.Width, stride, ref bad);
    a.UnlockBits(ba); b.UnlockBits(bb);
    return 100.0 * bad / n;
  }
  static void unsafe_copy(IntPtr a, IntPtr b, int h, int w, int stride, ref int bad) {
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        int pa = Marshal.ReadInt32(a, y * stride + x * 4);
        int pb = Marshal.ReadInt32(b, y * stride + x * 4);
        int dr = Math.Abs(((pa >> 16) & 255) - ((pb >> 16) & 255));
        int dg = Math.Abs(((pa >> 8) & 255) - ((pb >> 8) & 255));
        int db = Math.Abs((pa & 255) - (pb & 255));
        if (dr > 16 || dg > 16 || db > 16) bad++;
      }
    }
  }
  public static string Header(Bitmap img, out bool thru, out bool title) {
    thru = false; title = false;
    if (img == null) return "none";
    int best = -1, bestN = 0, yMax = Math.Min(48, img.Height);
    for (int y = 0; y < yMax; y++) {
      int n = 0;
      for (int x = img.Width / 5; x < img.Width * 3 / 5; x += 2) {
        Color c = img.GetPixel(x, y);
        if (Math.Abs(c.R - 32) < 28 && Math.Abs(c.G - 32) < 28 && Math.Abs(c.B - 32) < 28) n++;
      }
      if (n > bestN) { bestN = n; best = y; }
    }
    int y0 = best >= 0 ? best : 10;
    int rs = 0, gs = 0, bs = 0, m = 0, see = 0, samples = 0;
    for (int x = img.Width / 5; x < img.Width * 3 / 5; x += 2) {
      Color c = img.GetPixel(x, y0);
      rs += c.R; gs += c.G; bs += c.B; samples++;
      if (c.R > 180 && c.B > 180 && c.G < 80) see++;
    }
    if (samples == 0) return "none";
    m = samples;
    thru = see * 5 > m;
    title = bestN * 2 > m;
    return (rs / m) + "," + (gs / m) + "," + (bs / m);
  }
  public static void Lose(IntPtr hwnd) {
    int on = 1, off = 0;
    DwmSetWindowAttribute(hwnd, 13, ref on, 4);
    Thread.Sleep(80);
    DwmSetWindowAttribute(hwnd, 13, ref off, 4);
    IntPtr ign;
    SendMessageTimeout(hwnd, 0x031E, IntPtr.Zero, IntPtr.Zero, 0, 500, out ign);
    // Second hidden desktop, attached from a thread that has no windows. SwitchDesktop is not
    // called: that would put the desktop on the monitor. Cloak + composition-changed drop the surface.
    IntPtr b = CreateDesktop("$DeskB", IntPtr.Zero, IntPtr.Zero, 0, 0x10000000, IntPtr.Zero);
    if (b == IntPtr.Zero) b = OpenDesktop("$DeskB", 0, false, 0x10000000);
    if (b != IntPtr.Zero) {
      var hold = b;
      var t = new Thread(() => { SetThreadDesktop(hold); Thread.Sleep(50); });
      t.IsBackground = true; t.Start(); t.Join();
      CloseDesktop(b);
    }
    SendMessageTimeout(hwnd, 0x031E, IntPtr.Zero, IntPtr.Zero, 0, 500, out ign);
  }
}
"@
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition $src
}

function Write-Result([string]$text, [int]$code) {
  if ($OutDir) {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText((Join-Path $OutDir 'result.txt'), $text, $utf8)
  }
  exit $code
}

if ($RunWorker) {
  $panel = 0
  try {
    [MinR]::Open($DeskName)
    [MinR]::Sheet()
    $panel = [MinR]::Launch($Exe, '--panel', $DeskName)
    if ($panel -lt 0) { Write-Result "SETUP fail: panel did not start" 2 }
    Set-Content (Join-Path $OutDir 'panel.pid') $panel
    $hwnd = [IntPtr]::Zero
    $until = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $until) {
      $hwnd = [MinR]::Find([MinR]::Desk, $panel)
      if ($hwnd -ne [IntPtr]::Zero) { break }
      if (-not (Get-Process -Id $panel -ErrorAction SilentlyContinue)) { Write-Result "SETUP fail: panel exited before show" 2 }
      Start-Sleep -Milliseconds 50
    }
    if ($hwnd -eq [IntPtr]::Zero) { Write-Result "SETUP fail: panel window not visible" 2 }
    Start-Sleep -Milliseconds 600
    $base = $null
    foreach ($try in 1..8) {
      $a = [MinR]::Grab($hwnd)
      Start-Sleep -Milliseconds 250
      $b = [MinR]::Grab($hwnd)
      if ($a -ne $null -and $b -ne $null -and [MinR]::Diff($a, $b) -lt 0.5) { $base = $b; $a.Dispose(); break }
      if ($a) { $a.Dispose() }
      if ($b) { $base = $b }
    }
    if ($base -eq $null) { Write-Result "SETUP fail: no capture" 2 }
    $base.Save((Join-Path $OutDir 'base.png'), [System.Drawing.Imaging.ImageFormat]::Png)
    $thru = $false; $title = $false
    $hc = [MinR]::Header($base, [ref]$thru, [ref]$title)
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("BASE header=$hc title=$title thru=$thru size=$($base.Width)x$($base.Height)")
    if (-not $title -or $thru) {
      $lines.Add('SETUP fail: baseline header is not the opaque title bar')
      Write-Result ($lines -join "`n") 2
    }
    $fail = $false
    function Check-One([string]$name, [scriptblock]$restore) {
      [MinR]::ShowWindow($hwnd, 6) | Out-Null
      Start-Sleep -Milliseconds 350
      [MinR]::Lose($hwnd)
      & $restore
      Start-Sleep -Milliseconds 1000
      $img = [MinR]::Grab($hwnd)
      if ($img -eq $null) { $script:lines.Add("$name diff=100 header=none see=1 FAIL"); $script:fail = $true; return }
      $img.Save((Join-Path $OutDir "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
      $d = [MinR]::Diff($base, $img)
      $th = $false; $ti = $false
      $hh = [MinR]::Header($img, [ref]$th, [ref]$ti)
      $ok = ($d -lt 0.5) -and (-not $th) -and $ti
      if (-not $ok) { $script:fail = $true }
      $script:lines.Add(('{0} diff={1:N2}% header={2} see={3} {4}' -f $name, $d, $hh, $(if ($th) {1} else {0}), $(if ($ok) {'PASS'} else {'FAIL'})))
      $img.Dispose()
    }
    Check-One 'sw_restore' { [MinR]::ShowWindow($hwnd, 9) | Out-Null }
    Check-One 'sw_show' {
      [MinR]::ShowWindow($hwnd, 5) | Out-Null
      Start-Sleep -Milliseconds 200
      if ([MinR]::IsIconic($hwnd)) { [MinR]::ShowWindow($hwnd, 9) | Out-Null }
    }
    Check-One 'signal' {
      $sig = [MinR]::Launch($Exe, '--panel', $DeskName)
      if ($sig -gt 0) {
        Set-Content (Join-Path $OutDir 'signal.pid') $sig
        $until = (Get-Date).AddSeconds(8)
        while ((Get-Date) -lt $until -and (Get-Process -Id $sig -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 50 }
      }
    }
    $base.Dispose()
    $lines.Add($(if ($fail) {'RESULT FAIL'} else {'RESULT PASS'}))
    Write-Result ($lines -join "`n") $(if ($fail) {1} else {0})
  } catch {
    Write-Result ("SETUP fail: " + $_.Exception.Message) 2
  } finally {
    if ($panel -gt 0) { Stop-Process -Id $panel -Force -ErrorAction SilentlyContinue }
    $sp = Join-Path $OutDir 'signal.pid'
    if (Test-Path $sp) { $sid = Get-Content $sp; if ($sid) { Stop-Process -Id $sid -Force -ErrorAction SilentlyContinue } }
  }
}

# ---- parent: sandbox + hidden desktop. The worker (and the panel) run on aoe4s_minr.
$root = Split-Path $PSScriptRoot -Parent
if (-not $Exe) { $Exe = Join-Path $root 'target\release\aoe4spotify-slint.exe' }
$Exe = (Resolve-Path $Exe).Path
$S = Join-Path $env:TEMP 'aoe4s_minr'
if (Test-Path $S) { Remove-Item -Recurse -Force $S }
New-Item -ItemType Directory -Force -Path "$S\Roaming\AoE4Spotify-1.1", "$S\Local", "$S\steam", "$S\out" | Out-Null
$src = Join-Path $env:APPDATA 'AoE4Spotify-1.1'
foreach ($n in @('config.json','settings.json','base.json','import.json','intros.json')) {
  $p = Join-Path $src $n
  if (Test-Path $p) { Copy-Item $p (Join-Path "$S\Roaming\AoE4Spotify-1.1" $n) -Force }
}
$env:APPDATA = "$S\Roaming"
$env:LOCALAPPDATA = "$S\Local"
$env:AOE4S_TEST = '1'
$env:AOE4S_FAKESP = '1'
$env:AOE4S_MUTEX_SUFFIX = '_minr'
$env:AOE4S_UPDATE_API = 'http://127.0.0.1:9/none'
$env:AOE4S_GAME_PROC = 'aoe4s_minr_dummy.exe'
$env:AOE4S_STEAM_PATH = "$S\steam"
$env:AOE4S_STEAM_PROC = 'dummysteam.exe'
$env:AOE4S_STEAM_EXE = "$S\nosteam.exe"
$env:AOE4S_DRYOPEN = "$S\opened.txt"
$env:AOE4S_DESKTOP = "$S\desk"
$env:AOE4S_ARP = 'HKCU\Software\AoE4SpotifyMinr\ARP'
[MinR]::Open($DeskName)
$ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$self = $PSCommandPath
$arg = '-NoProfile -ExecutionPolicy Bypass -File "' + $self + '" -RunWorker -Exe "' + $Exe + '" -OutDir "' + (Join-Path $S 'out') + '"'
$userDesk = [MinR]::InputDesk()
$worker = 0
$panelPid = 0
try {
  $worker = [MinR]::Launch($ps, $arg, $DeskName)
  if ($worker -lt 0) { Write-Output 'SETUP fail: worker did not start'; exit 2 }
  $until = (Get-Date).AddSeconds(90)
  $result = Join-Path $S 'out\result.txt'
  while ((Get-Date) -lt $until) {
    if (Test-Path $result) { break }
    if (-not (Get-Process -Id $worker -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 200
  }
  if (Test-Path (Join-Path $S 'out\panel.pid')) { $panelPid = [int](Get-Content (Join-Path $S 'out\panel.pid')) }
  if (Test-Path $result) {
    $text = [System.IO.File]::ReadAllText($result)
    Write-Output $text
    if ($text -match 'RESULT PASS') { exit 0 }
    if ($text -match 'SETUP fail') { exit 2 }
    exit 1
  }
  Write-Output 'SETUP fail: worker produced no result'
  exit 2
} finally {
  if ($userDesk -ne [IntPtr]::Zero) { [MinR]::Back($userDesk); [MinR]::CloseDesktop($userDesk) | Out-Null }
  if ($worker -gt 0) { Stop-Process -Id $worker -Force -ErrorAction SilentlyContinue }
  if ($panelPid -gt 0) { Stop-Process -Id $panelPid -Force -ErrorAction SilentlyContinue }
  $sp = Join-Path $S 'out\signal.pid'
  if (Test-Path $sp) { $sid = [int](Get-Content $sp); if ($sid -gt 0) { Stop-Process -Id $sid -Force -ErrorAction SilentlyContinue } }
  if ([MinR]::Desk -ne [IntPtr]::Zero) { [MinR]::CloseDesktop([MinR]::Desk) | Out-Null }
}
