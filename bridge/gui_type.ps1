# Type literal text into the focused control (real input, DPI-aware).
#
# The CUA driver posts text, and Vectorworks' own widgets ignore posted input;
# native Win32 dialogs (file open/save, message boxes) do accept it, but this
# script uses the same real-input path as gui_keys.ps1 so one tool covers both.
#
#   powershell -File gui_type.ps1 -Text "C:\path\file.vwx"
#   powershell -File gui_type.ps1 -Text "B" -Enter
param(
    [Parameter(Mandatory = $true)][string]$Text,
    [switch]$Enter,
    [int]$DelayMs = 12
)

Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, System.IntPtr extra);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
[DllImport("user32.dll")] public static extern short VkKeyScan(char ch);
[DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint mapType);
'@

[void][W.U]::SetProcessDPIAware()
$KEYUP = 0x0002

function Send-Vk([byte]$vk, [bool]$shift) {
    if ($shift) { [W.U]::keybd_event(0x10, 0, 0, [System.IntPtr]::Zero) }
    [W.U]::keybd_event($vk, 0, 0, [System.IntPtr]::Zero)
    Start-Sleep -Milliseconds 8
    [W.U]::keybd_event($vk, 0, $KEYUP, [System.IntPtr]::Zero)
    if ($shift) { [W.U]::keybd_event(0x10, 0, $KEYUP, [System.IntPtr]::Zero) }
    Start-Sleep -Milliseconds $DelayMs
}

foreach ($ch in $Text.ToCharArray()) {
    $scan = [W.U]::VkKeyScan($ch)
    if ($scan -eq -1) { continue }                     # not on this layout
    $vk = [byte]($scan -band 0xFF)
    $shift = (($scan -shr 8) -band 0x01) -ne 0
    Send-Vk $vk $shift
}

if ($Enter) {
    [W.U]::keybd_event(0x0D, 0, 0, [System.IntPtr]::Zero)
    Start-Sleep -Milliseconds 40
    [W.U]::keybd_event(0x0D, 0, $KEYUP, [System.IntPtr]::Zero)
}
"typed $($Text.Length) chars$(if ($Enter) { ' + enter' })"
