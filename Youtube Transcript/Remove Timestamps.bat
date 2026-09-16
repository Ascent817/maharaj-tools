@echo off
rem Double-click this to launch the Remove Timestamps app.
setlocal
set "APP=%~dp0Remove Timestamps.pyw"
where python >nul 2>&1 || goto :nopython
python -c "import youtube_transcript_api, yt_dlp" >nul 2>&1
if errorlevel 1 (
    echo Installing transcript dependencies...
    python -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo Could not install dependencies. Check your internet connection.
        pause
        exit /b 1
    )
)
where pythonw >nul 2>&1 && (start "" pythonw "%APP%" %* & exit /b)
where python  >nul 2>&1 && (start "" python  "%APP%" %* & exit /b)
:nopython
echo Python was not found on this PC. Install it from https://python.org and try again.
pause
