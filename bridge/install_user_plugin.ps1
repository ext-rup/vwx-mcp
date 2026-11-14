<#
Install the user-side half of the VWX bridge for one Vectorworks year:
vwx-plugin\*  ->  %APPDATA%\Nemetschek\Vectorworks\<year>\Plug-ins\VW-MCP\
A new major version's Migration Manager does not copy that folder.

Two steps stay manual, because the automated versions were tried on 2027 and
failed silently (2026-10-23):
  - The "VWX Bridge Start" Python menu command. A .vsm copied from 2026 shows
    up in the menu but never executes. It must be created in the new year's
    Plug-in Manager.
  - The Extras menu entries. Entries written into the .vww by hand show the
    raw universal name and are not linked to the plug-in. They must be added
    with the Workspace Editor.
The script prints both procedures at the end.

The native half (VwxBridge.vlb/.vwr into Program Files) is
deploy_native_bridge.bat.

Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File bridge\install_user_plugin.ps1 [-Year 2027]
#>
param([string]$Year = $env:VWX_VW_VERSION)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$vwRoot = Join-Path $env:APPDATA 'Nemetschek\Vectorworks'

if (-not $Year) {
    $Year = Get-ChildItem 'C:\Program Files' -Directory -Filter 'Vectorworks *' |
        ForEach-Object { ($_.Name -split ' ')[1] } |
        Where-Object { $_ -match '^\d{4}$' } | Sort-Object -Descending | Select-Object -First 1
}
if (-not $Year) { throw 'No Vectorworks install found; pass -Year.' }
Write-Host "Target: Vectorworks $Year"

$plugins = Join-Path $vwRoot "$Year\Plug-ins"
if (-not (Test-Path $plugins)) { throw "$plugins does not exist. Start Vectorworks $Year once first." }

# Safe while Vectorworks runs: the pump hot-reloads vwx_pump.py, commands.py and
# commands_spotlight.py (the pump dispatches to every module it can import).
# Copy every .py plus the index — a hardcoded list silently skipped
# commands_spotlight.py the first time it was added.
$dst = Join-Path $plugins 'VW-MCP'
New-Item -ItemType Directory -Force $dst | Out-Null
Get-ChildItem (Join-Path $repo 'vwx-plugin') -File |
    Where-Object { $_.Extension -in '.py', '.json' } |
    ForEach-Object {
        Copy-Item $_.FullName $dst -Force
        Write-Host "  VW-MCP\$($_.Name)"
    }

$vsm = Join-Path $plugins 'VWX Bridge Start.vsm'
Write-Host ''
if (Test-Path $vsm) {
    Write-Host "Menu command present ($vsm). If it was copied from an older year, recreate it (step 1)."
}
Write-Host @"
Manual steps in Vectorworks $Year (once per new major version):
 1. Extras > Plug-ins > Plug-in-Manager > Eigene Plug-ins > Neu... > Menuebefehl,
    name exactly "VWX Bridge Start". Select it > Code... > language Python >
    paste vwx-plugin\BridgeStart_MenuCommand.py > OK.
 2. Menu + shortcut, scripted (Vectorworks CLOSED):
      python bridge\patch_workspace.py --workspace Spotlight --year $Year
    It adds "VWX Bridge Start" (Ctrl+Shift+B) to Tools, gives it a real
    ResourceManagerID, and points defaultWorkspace at the user copy — all three
    are required; a hand-written entry with ID 0 is dropped silently.
    (GUI alternative: Arbeitsumgebung anpassen > Menues, drag the command in.)
 3. Trigger: either the native palette (bridge\deploy_native_bridge.bat,
    Vectorworks closed, UAC) or, without it, bridge\wake_watch.py, which keeps
    ipc\native.alive fresh and fires Ctrl+Shift+B when a job appears.
 4. Restart the vwx-mcp server: it picks the plug-in folder at startup.
Check: every runner start logs "start: invoked" in VW-MCP\bridge.log.
"@
