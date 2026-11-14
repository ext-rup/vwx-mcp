# Real mouse input for GUI automation (bypasses PostMessage-based drivers).
# Vectorworks' BCG menu bar hit-tests against the PHYSICAL cursor position, so
# posted clicks never open a menu. This script moves the real cursor and uses
# mouse_event, which VW honours.
#
#   powershell -File gui_click.ps1 -X 341 -Y 22            # left click
#   powershell -File gui_click.ps1 -X 341 -Y 22 -Double    # double click
#   powershell -File gui_click.ps1 -X 341 -Y 22 -Right     # right click
#   powershell -File gui_click.ps1 -X 341 -Y 22 -MoveOnly  # just move
#
# Coordinates are PHYSICAL screen pixels (what screenshots show). The script
# converts them to the logical space of this (DPI-unaware) process.
param(
    [Parameter(Mandatory = $true)][int]$X,
    [Parameter(Mandatory = $true)][int]$Y,
    [switch]$Double,
    [switch]$Right,
    [switch]$MoveOnly,
    [int]$DelayMs = 120
)

Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
[DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
[DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.IntPtr e);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
public struct POINT { public int X, Y; }
'@

[void][W.U]::SetProcessDPIAware()
$sw = [W.U]::GetSystemMetrics(0)
$sh = [W.U]::GetSystemMetrics(1)
$scale = 1.0
if ($sw -gt 0) {
    # 3840x2160 panel reported as 2560x1440 before DPI awareness; after
    # SetProcessDPIAware the metrics are physical, so no conversion is needed.
    $scale = 1.0
}
$px = [int][math]::Round($X / $scale)
$py = [int][math]::Round($Y / $scale)

[void][W.U]::SetCursorPos($px, $py)
Start-Sleep -Milliseconds 80
$p = New-Object W.U+POINT
[void][W.U]::GetCursorPos([ref]$p)

$LEFTDOWN = 0x0002; $LEFTUP = 0x0004
$RIGHTDOWN = 0x0008; $RIGHTUP = 0x0010
if ($Right) { $d = $RIGHTDOWN; $u = $RIGHTUP } else { $d = $LEFTDOWN; $u = $LEFTUP }

if (-not $MoveOnly) {
    [W.U]::mouse_event($d, 0, 0, 0, [System.IntPtr]::Zero)
    Start-Sleep -Milliseconds $DelayMs
    [W.U]::mouse_event($u, 0, 0, 0, [System.IntPtr]::Zero)
    if ($Double) {
        Start-Sleep -Milliseconds 60
        [W.U]::mouse_event($d, 0, 0, 0, [System.IntPtr]::Zero)
        Start-Sleep -Milliseconds $DelayMs
        [W.U]::mouse_event($u, 0, 0, 0, [System.IntPtr]::Zero)
    }
}

Write-Output ("requested=({0},{1}) cursor=({2},{3}) screen={4}x{5}" -f $X, $Y, $p.X, $p.Y, $sw, $sh)
