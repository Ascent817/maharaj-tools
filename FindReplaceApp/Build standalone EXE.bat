@echo off
rem ===================================================================
rem  Optional: build FindAndReplace.exe so the app runs on PCs that do
rem  not have Python installed.  Needs an internet connection once.
rem  The finished .exe appears in the "dist" folder.
rem ===================================================================
setlocal
cd /d "%~dp0"

echo Installing / updating PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
    echo.
    echo   Could not install PyInstaller. Check your internet connection.
    pause
    exit /b 1
)

echo.
echo Building FindAndReplace.exe ...
python -m PyInstaller --noconfirm --onefile --windowed ^
    --name FindAndReplace find_replace_app.py
if errorlevel 1 (
    echo.
    echo   Build failed - see the messages above.
    pause
    exit /b 1
)

echo.
echo   Done.  Your program is here:
echo   %~dp0dist\FindAndReplace.exe
echo.
echo   Copy that single file anywhere; no Python needed to run it.
echo.
pause
