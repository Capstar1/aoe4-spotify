param($out, $color = "White")
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W { [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern int GetWindowRgnBox(IntPtr h, out R r); [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x,int y,int cx,int cy,uint f);
 public struct R { public int L,T,Rt,B; } }
"@
$p = Get-Process "AoE4 Spotify" | ? MainWindowHandle -ne 0 | select -First 1; $h = $p.MainWindowHandle
$r = New-Object W+R; [W]::GetWindowRect($h, [ref]$r) | Out-Null; $b = New-Object W+R; [W]::GetWindowRgnBox($h, [ref]$b) | Out-Null
$x0 = $r.L + $b.L; $y0 = $r.T + $b.T; $wd = $b.Rt - $b.L
$f = New-Object Windows.Forms.Form; $f.FormBorderStyle = "None"; $f.BackColor = [Drawing.Color]::FromName($color); $f.StartPosition = "Manual"
$f.Bounds = New-Object Drawing.Rectangle ($x0 - 60), ($y0 - 60), ($wd + 120), 200; $f.ShowInTaskbar = $false; $f.Show(); [Windows.Forms.Application]::DoEvents()
[W]::SetWindowPos($h, [IntPtr]::new(-1), 0,0,0,0, 3) | Out-Null; [W]::SetWindowPos($h, [IntPtr]::new(-2), 0,0,0,0, 3) | Out-Null; Start-Sleep -m 700; [Windows.Forms.Application]::DoEvents()
$n = 20; $z = 8; $img = New-Object Drawing.Bitmap ($n*$z*2 + 8), ($n*$z); $g = [Drawing.Graphics]::FromImage($img); $g.InterpolationMode = "NearestNeighbor"; $g.PixelOffsetMode = "Half"; $g.Clear([Drawing.Color]::Magenta)
foreach ($i in 0,1) { $sx = if ($i) { $x0 + $wd - $n + 4 } else { $x0 - 4 }; $c = New-Object Drawing.Bitmap $n, $n; $cg = [Drawing.Graphics]::FromImage($c); $cg.CopyFromScreen($sx, $y0 - 4, 0, 0, $c.Size)
  $g.DrawImage($c, (New-Object Drawing.Rectangle ($i * ($n*$z + 8)), 0, ($n*$z), ($n*$z))) }
$img.Save($out); $f.Close(); "saved $out  win=$($r.L),$($r.T) rgn=$($b.L),$($b.T),$($b.Rt),$($b.B)"
