@echo off
setlocal
cd /d "%~dp0"

echo Installing build dependencies...
python -m pip install --upgrade pyinstaller -r requirements.txt
if errorlevel 1 goto :failed

echo Building Transcript Cleaner.exe...
python -m PyInstaller --noconfirm --clean TranscriptCleaner.spec
if errorlevel 1 goto :failed

copy /y "dist\Transcript Cleaner.exe" "Transcript Cleaner.exe" >nul
echo Done: %~dp0Transcript Cleaner.exe
exit /b 0

:failed
echo Build failed.
exit /b 1
