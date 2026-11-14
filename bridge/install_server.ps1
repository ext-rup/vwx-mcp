# Install the MCP server half of vwx-mcp into the user profile.
#
#   powershell -ExecutionPolicy Bypass -File bridge\install_server.ps1
#   powershell -ExecutionPolicy Bypass -File bridge\install_server.ps1 -Start
#
# Copies the vendored server AND the fork modules. The upstream README lists
# only vwx_mcp_server.py / tool_tags.py / requirements.txt — copying just those
# gives you the 272 upstream tools and none of the fork's 18 (spotlight,
# connectcad, braceworks, mvr), because fork_tools.py imports them by name and
# fails at startup. That is why this script exists.
#
# Re-run it after any change to mcp-server/ to refresh the installed copy.
param(
    [string]$Target = (Join-Path $env:USERPROFILE '.local\share\vwx-mcp'),
    [string]$LauncherDir = (Join-Path $env:USERPROFILE 'bridge'),
    [switch]$Start
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$src = Join-Path $repo 'mcp-server'

# vendored server + every fork module it imports (fork_tools.py is the entry)
$files = @(
    'vwx_mcp_server.py',
    'tool_tags.py',
    'requirements.txt',
    'fork_tools.py',
    'spotlight_tools.py',
    'connectcad_tools.py',
    'braceworks_tools.py',
    'mvr_tools.py',
    'mvr_file.py',
    'vwx_gui.py'
)

New-Item -ItemType Directory -Force -Path $Target | Out-Null
New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null

$copied = 0
foreach ($f in $files) {
    $from = Join-Path $src $f
    if (-not (Test-Path $from)) {
        Write-Host "  MISSING in repo: $f" -ForegroundColor Red
        continue
    }
    Copy-Item -Force $from (Join-Path $Target $f)
    $copied++
}
Write-Host "copied $copied/$($files.Count) files to $Target"

# The trigger half lives in bridge/, not mcp-server/: the file transport needs
# something to fire the menu command (the native palette once it is built,
# wake_watch.py otherwise).
Copy-Item -Force (Join-Path $repo 'bridge\wake_watch.py') (Join-Path $Target 'wake_watch.py')
Copy-Item -Force (Join-Path $repo 'bridge\vwx-mcp.bat') (Join-Path $LauncherDir 'vwx-mcp.bat')
Copy-Item -Force (Join-Path $repo 'bridge\vwx-watch.bat') (Join-Path $LauncherDir 'vwx-watch.bat')
Write-Host "launchers: $LauncherDir\vwx-mcp.bat, $LauncherDir\vwx-watch.bat"

# Dependencies: the launcher would bootstrap these on first run, but then the
# first tool call pays the install and a failure is invisible. Do it here.
$venv = Join-Path $Target '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
    Write-Host "creating venv in $venv ..."
    & python -m venv $venv
}
Write-Host "installing requirements (fastmcp, pillow) ..."
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r (Join-Path $Target 'requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed (exit $LASTEXITCODE)" -ForegroundColor Red
}

# The fork modules are the part that silently disappears on a partial install,
# so prove the installed copy can import them before calling this done.
$py = $venvPy
$check = @'
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1])))
import importlib
missing = []
for mod in ("tool_tags", "fork_tools", "spotlight_tools", "connectcad_tools",
            "braceworks_tools", "mvr_tools", "mvr_file", "vwx_gui"):
    try:
        importlib.import_module(mod)
    except Exception as exc:
        missing.append("%s: %s" % (mod, exc))
print("IMPORT-OK" if not missing else "IMPORT-FAIL " + "; ".join(missing))
'@
$checkFile = Join-Path $env:TEMP 'vwx_install_check.py'
Set-Content -Path $checkFile -Value $check -Encoding UTF8
$result = & $py $checkFile (Join-Path $Target 'vwx_mcp_server.py') 2>&1
Remove-Item -Force $checkFile -ErrorAction SilentlyContinue
if ($result -match 'IMPORT-OK') {
    Write-Host "import check: OK (all fork modules load)" -ForegroundColor Green
} else {
    Write-Host "import check: FAILED -> $result" -ForegroundColor Red
    Write-Host "  (the modules import fastmcp; a missing dependency shows here too)"
}

Write-Host ""
Write-Host "Next:"
Write-Host "  1. Start the server:  $LauncherDir\vwx-mcp.bat"
Write-Host "     and the trigger:    $LauncherDir\vwx-watch.bat"
Write-Host "     (the venv + deps are installed above; wake_watch is only needed"
Write-Host "      while the native palette is not built)"
Write-Host "  2. Point your MCP client at  http://127.0.0.1:8082/mcp"
Write-Host "     Claude Code:  claude mcp add --transport http vwx http://127.0.0.1:8082/mcp"
Write-Host "  3. Vectorworks must be running with the VW-MCP plug-in installed"
Write-Host "     (bridge\install_user_plugin.ps1) and the 'VWX Bridge Start' menu"
Write-Host "     command assigned to Ctrl+Shift+B."

if ($Start) {
    Write-Host ""
    Write-Host "starting the server..."
    Start-Process -FilePath (Join-Path $LauncherDir 'vwx-mcp.bat')
}
