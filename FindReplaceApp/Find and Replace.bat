@echo off
rem ===================================================================
rem  Find & Replace - double-click launcher
rem  Starts the app with whichever Python is installed on this PC.
rem ===================================================================
setlocal
cd /d "%~dp0"
set "SCRIPT=%~dp0find_replace_app.py"

if not exist "%SCRIPT%" (
    echo.
    echo   Cannot find find_replace_app.py
    echo   Keep this .bat file in the same folder as the app.
    echo.
    pause
    exit /b 1
)

rem 1. Preferred: the Python launcher, windowed (no black console box).
where pyw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pyw.exe -3 "%SCRIPT%" %*
    exit /b 0
)

rem 2. pythonw.exe on the PATH.
where pythonw.exe >nul 2>&1
if not errorlevel 1 (
    start "" pythonw.exe "%SCRIPT%" %*
    exit /b 0
)

rem 3. Plain python.exe - works, but leaves a console window open.
where python.exe >nul 2>&1
if not errorlevel 1 (
    python.exe "%SCRIPT%" %*
    exit /b 0
)

echo.
echo   Python was not found on this computer.
echo.
echo   Install it from https://www.python.org/downloads/windows/
echo   and tick "Add python.exe to PATH" during setup, then
echo   double-click this file again.
echo.
pause
exit /b 1
