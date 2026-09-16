@echo off
rem ---------------------------------------------------------------
rem  Indic Script Transliterator - double-click launcher (Windows)
rem ---------------------------------------------------------------
cd /d "%~dp0"

set "SCRIPT=%~dp0indic_transliterate.py"

rem Prefer the windowed interpreters so no black console box appears.
set "PYW="
where pyw.exe      >nul 2>&1 && set "PYW=pyw -3"
if not defined PYW where pythonw.exe >nul 2>&1 && set "PYW=pythonw"

set "PYC="
where py.exe       >nul 2>&1 && set "PYC=py -3"
if not defined PYC where python.exe  >nul 2>&1 && set "PYC=python"

if not defined PYW if not defined PYC goto :nopython

if defined PYW (
    start "" %PYW% "%SCRIPT%"
) else (
    %PYC% "%SCRIPT%"
    if errorlevel 1 pause
)
exit /b 0

:nopython
echo.
echo   Python 3 was not found on this computer.
echo.
echo   Install it from https://www.python.org/downloads/ and tick
echo   "Add python.exe to PATH" during setup, then run this file again.
echo.
pause
exit /b 1
