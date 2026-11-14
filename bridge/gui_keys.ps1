# Send a key combination with REAL modifier state (keybd_event).
#
# The CUA driver's hotkey tool posts keys, and Vectorworks reads the live
# keyboard state (GetKeyState) instead of the posted lParam, so modified
# shortcuts never fire. This sends real input.
#
#   powershell -File gui_keys.ps1 -Keys "ctrl+shift+b"
#   powershell -File gui_keys.ps1 -Keys "ctrl+shift+alt+w"
#   powershell -File gui_keys.ps1 -Keys "escape"
param(
    [Parameter(Mandatory = $true)][string]$Keys,
    [int]$HoldMs = 60
)

Add-Type -Namespace W -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, System.IntPtr extra);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
'@

[void][W.U]::SetProcessDPIAware()

$mods = @{ 'ctrl' = 0x11; 'shift' = 0x10; 'alt' = 0x12; 'win' = 0x5B }
$names = @{
    'escape' = 0x1B; 'esc' = 0x1B; 'enter' = 0x0D; 'return' = 0x0D; 'tab' = 0x09
    'space' = 0x20; 'delete' = 0x2E; 'backspace' = 0x08
    'left' = 0x25; 'up' = 0x26; 'right' = 0x27; 'down' = 0x28
    'home' = 0x24; 'end' = 0x23; 'pageup' = 0x21; 'pagedown' = 0x22
    'f1' = 0x70; 'f2' = 0x71; 'f3' = 0x72; 'f4' = 0x73; 'f5' = 0x74; 'f6' = 0x75
    'f7' = 0x76; 'f8' = 0x77; 'f9' = 0x78; 'f10' = 0x79; 'f11' = 0x7A; 'f12' = 0x7B
}

$parts = $Keys.ToLower().Split('+')
$held = @()
foreach ($p in $parts) {
    if ($mods.ContainsKey($p)) {
        [W.U]::keybd_event([byte]$mods[$p], 0, 0, [System.IntPtr]::Zero)
        $held += $mods[$p]
    }
    else {
        if ($names.ContainsKey($p)) { $vk = $names[$p] }
        elseif ($p.Length -eq 1) { $vk = [int][char]$p.ToUpper() }
        else { Write-Error "unknown key '$p'"; exit 2 }
        Start-Sleep -Milliseconds 40
        [W.U]::keybd_event([byte]$vk, 0, 0, [System.IntPtr]::Zero)
        Start-Sleep -Milliseconds $HoldMs
        [W.U]::keybd_event([byte]$vk, 0, 2, [System.IntPtr]::Zero)
    }
}
Start-Sleep -Milliseconds 40
[array]::Reverse($held)
foreach ($m in $held) {
    [W.U]::keybd_event([byte]$m, 0, 2, [System.IntPtr]::Zero)
}
Write-Output ("sent {0}" -f $Keys)
