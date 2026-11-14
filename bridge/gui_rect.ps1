# Print the physical screen rectangle of a window handle (see gui_click.ps1).
#   powershell -File gui_rect.ps1 -Hwnd 330552
param([Parameter(Mandatory = $true)][int]$Hwnd)

Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern int GetWindowTextW(System.IntPtr h, System.Text.StringBuilder s, int n);
public struct RECT { public int L, T, R, B; }
'@

[void][W.U]::SetProcessDPIAware()
$r = New-Object W.U+RECT
[void][W.U]::GetWindowRect([System.IntPtr]$Hwnd, [ref]$r)
$sb = New-Object System.Text.StringBuilder 512
[void][W.U]::GetWindowTextW([System.IntPtr]$Hwnd, $sb, 512)
Write-Output ("hwnd={0} rect={1},{2} size={3}x{4} title='{5}'" -f $Hwnd, $r.L, $r.T, ($r.R - $r.L), ($r.B - $r.T), $sb.ToString())
