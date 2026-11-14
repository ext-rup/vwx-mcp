@echo off
REM vwx-mcp trigger watchdog — the file transport's "fire the menu command" half.
REM Rewrites ipc\native.alive every second and sends Ctrl+Shift+B (the
REM "VWX Bridge Start" menu command) when a job appears. Not needed once the
REM native palette (native\, VwxBridge.vlb) is built and deployed.
set VWXHOME=%USERPROFILE%\.local\share\vwx-mcp
"%VWXHOME%\.venv\Scripts\python.exe" "%VWXHOME%\wake_watch.py" -v
pause
