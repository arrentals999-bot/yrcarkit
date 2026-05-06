@echo off
REM YRCARKIT Battery Manager — local launcher
REM Double-click this file to start the web UI in your browser.

cd /d "%~dp0\.."
echo.
echo ============================================================
echo   YRCARKIT Battery Manager
echo   Starting at http://127.0.0.1:5000/
echo   Browser will open automatically. Close this window to stop.
echo ============================================================
echo.

REM Install Flask if missing (one-time)
python -c "import flask" 2>nul
if errorlevel 1 (
    echo Installing Flask...
    python -m pip install -r battery_ui\requirements.txt
)

python -m battery_ui.app

pause
