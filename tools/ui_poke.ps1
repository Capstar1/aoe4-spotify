param($act="none", $x=0, $y=0, $out="shot")
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W { [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out R r); [DllImport("user32.dll")] public static extern int GetWindowRgnBox(IntPtr h, out R r);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y); [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern void mouse_event(int f,int x,int y,int d,int e);
 [DllImport("user32.dll")] public static extern bool GetCursorInfo(ref CI c); [DllImport("user32.dll")] public static extern IntPtr LoadCursor(IntPtr h, int id);
 [StructLayout(LayoutKind.Sequential)] public struct CI { public int cb, flags; public IntPtr h; public int x, y; } public struct R { public int L,T,Rt,B; } }
"@
$h=(Get-Process "AoE4 Spotify" | ? MainWindowHandle -ne 0 | select -First 1).MainWindowHandle
$r=New-Object W+R; [W]::GetWindowRect($h,[ref]$r)|Out-Null; $b=New-Object W+R; [W]::GetWindowRgnBox($h,[ref]$b)|Out-Null; $ox=$r.L+$b.L; $oy=$r.T+$b.T
[W]::SetForegroundWindow($h)|Out-Null; Start-Sleep -m 300
$old=[Windows.Forms.Cursor]::Position
if ($act -ne "none") { [W]::SetCursorPos($ox+$x,$oy+$y); Start-Sleep -m 500; if ($act -eq "click") { [W]::mouse_event(2,0,0,0,0); [W]::mouse_event(4,0,0,0,0); Start-Sleep -m 900 } }
$ci=New-Object W+CI; $ci.cb=24; [W]::GetCursorInfo([ref]$ci)|Out-Null; "hand=$($ci.h -eq [W]::LoadCursor([IntPtr]::Zero,32649))"
[W]::GetWindowRgnBox($h,[ref]$b)|Out-Null; $w=$b.Rt-$b.L; $hh=$b.B-$b.T; $bm=New-Object Drawing.Bitmap $w,$hh; [Drawing.Graphics]::FromImage($bm).CopyFromScreen($r.L+$b.L,$r.T+$b.T,0,0,$bm.Size); $bm.Save("$env:TEMP\t_$out.png")
if ($act -ne "hover") { [W]::SetCursorPos($old.X,$old.Y)|Out-Null }

