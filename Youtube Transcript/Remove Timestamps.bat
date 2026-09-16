@echo off
rem Double-click this to launch the Remove Timestamps app.
setlocal
set "APP=%~dp0Remove Timestamps.pyw"
where pythonw >nul 2>&1 && (start "" pythonw "%APP%" %* & exit /b)
where python  >nul 2>&1 && (start "" python  "%APP%" %* & exit /b)
echo Python was not found on this PC. Install it from https://python.org and try again.
pause
