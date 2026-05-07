@echo off
REM Start Flask UI + Cloudflare tunnel together.
REM Double-click after a reboot to bring everything back online.

cd /d "%~dp0\.."

echo.
echo ============================================================
echo   Ratan's Private Battery Manager
echo   Starting local UI and Cloudflare tunnel...
echo ============================================================

REM Make sure Flask deps are present
python -c "import flask" 2>nul
if errorlevel 1 (
    echo Installing Flask...
    python -m pip install -r battery_ui\requirements.txt
)

REM Start Flask in a separate window so it survives this batch ending
start "Battery UI - Flask" /MIN cmd /c "python -m battery_ui.app > tunnel\flask.log 2>&1"

REM Give Flask a moment to bind port 5000
timeout /t 3 /nobreak >nul

REM Start Cloudflare tunnel in another window
start "Battery UI - Tunnel" /MIN cmd /c "tunnel\cloudflared.exe tunnel --url http://localhost:5000 > tunnel\tunnel.log 2>&1"

REM Wait a few seconds for the tunnel to register and grab the URL
timeout /t 8 /nobreak >nul

REM Pull URL out of the log and write it to tunnel-url.txt
powershell -Command "$line = Select-String -Path 'tunnel\tunnel.log' -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' | Select-Object -First 1; if ($line) { $u = [regex]::Match($line.Line, 'https://[a-z0-9-]+\.trycloudflare\.com').Value; Set-Content -Path 'tunnel\tunnel-url.txt' -Value $u; Write-Output ''; Write-Output ('TUNNEL URL: ' + $u); Write-Output ''; Write-Output 'Login (also stored in tunnel\credentials.json):'; $c = Get-Content 'tunnel\credentials.json' | ConvertFrom-Json; Write-Output ('  username: ' + $c.username); Write-Output ('  password: ' + $c.password); } else { Write-Output 'tunnel URL not yet visible — check tunnel\tunnel.log' }"

echo.
echo ============================================================
echo   Local UI:    http://127.0.0.1:5000/
echo   Public URL:  see tunnel\tunnel-url.txt
echo.
echo   To stop: close the two minimized windows (Flask and Tunnel).
echo ============================================================
echo.
pause
