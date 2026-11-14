# Real mouse drag (press, interpolated move, release) in PHYSICAL screen pixels.
# Needed for drag & drop in dialogs whose input stack ignores posted messages
# (Vectorworks' Workspace Editor is one).
#
#   powershell -File gui_drag.ps1 -X1 969 -Y1 741 -X2 1318 -Y2 419
param(
    [Parameter(Mandatory = $true)][int]$X1,
    [Parameter(Mandatory = $true)][int]$Y1,
    [Parameter(Mandatory = $true)][int]$X2,
    [Parameter(Mandatory = $true)][int]$Y2,
    [int]$Steps = 25,
    [int]$HoldMs = 250,
    [int]$ReleaseDelayMs = 800
)

Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
[DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.IntPtr e);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
public struct POINT { public int X, Y; }
'@

[void][W.U]::SetProcessDPIAware()
$LEFTDOWN = 0x0002
$LEFTUP = 0x0004

[void][W.U]::SetCursorPos($X1, $Y1)
Start-Sleep -Milliseconds 120
[W.U]::mouse_event($LEFTDOWN, 0, 0, 0, [System.IntPtr]::Zero)
Start-Sleep -Milliseconds $HoldMs

for ($i = 1; $i -le $Steps; $i++) {
    $x = [int][math]::Round($X1 + ($X2 - $X1) * $i / $Steps)
    $y = [int][math]::Round($Y1 + ($Y2 - $Y1) * $i / $Steps)
    [void][W.U]::SetCursorPos($x, $y)
    Start-Sleep -Milliseconds 25
}

# Hover over the drop target before releasing: BCG tree controls only accept
# a drop once the target has been highlighted, which takes a moment.
Start-Sleep -Milliseconds $ReleaseDelayMs
[W.U]::mouse_event($LEFTUP, 0, 0, 0, [System.IntPtr]::Zero)
Start-Sleep -Milliseconds 150

$p = New-Object W.U+POINT
[void][W.U]::GetCursorPos([ref]$p)
Write-Output ("dragged ({0},{1}) -> ({2},{3}); cursor=({4},{5})" -f $X1, $Y1, $X2, $Y2, $p.X, $p.Y)
