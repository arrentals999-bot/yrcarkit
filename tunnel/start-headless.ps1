# Headless launcher used by Windows Task Scheduler at user logon.
# Starts Flask + Cloudflare tunnel as background processes, captures the
# new tunnel URL, writes it to tunnel/tunnel-url.txt + a Windows toast.
# No console windows, no pauses, no browser pop.

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$flaskLog  = Join-Path $PSScriptRoot "flask.log"
$tunLog    = Join-Path $PSScriptRoot "tunnel.log"
$urlFile   = Join-Path $PSScriptRoot "tunnel-url.txt"
$bootLog   = Join-Path $PSScriptRoot "autostart.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $bootLog -Append -Encoding utf8
}

Log "=== autostart fired ==="

# 1) Make sure Flask is installed
$flaskOk = $false
try {
    & python -c "import flask" 2>$null
    if ($LASTEXITCODE -eq 0) { $flaskOk = $true }
} catch { }
if (-not $flaskOk) {
    Log "Flask not present, installing..."
    & python -m pip install -r "$repo\battery_ui\requirements.txt" 2>&1 | Out-File -Append -FilePath $bootLog
}

# 2) Kill any leftover python.exe / cloudflared from a previous session
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# 3) Start Flask hidden, headless
$env:BATTERY_UI_NO_BROWSER = "1"
Log "Starting Flask..."
$flask = Start-Process -FilePath "python" `
    -ArgumentList "-m","battery_ui.app" `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $flaskLog `
    -RedirectStandardError "$flaskLog.err" `
    -WindowStyle Hidden `
    -PassThru
Log "Flask PID: $($flask.Id)"

# 4) Wait for Flask to bind port 5000 (use lightweight thresholds endpoint, generous timeout)
$bound = $false
for ($i = 0; $i -lt 12; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:5000/api/thresholds" -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) { $bound = $true; break }
    } catch { }
}
if (-not $bound) { Log "WARNING: Flask did not respond within 12s, continuing anyway" }
else             { Log "Flask up at :5000" }

# 5) Start cloudflared tunnel
$cfExe = Join-Path $PSScriptRoot "cloudflared.exe"
if (-not (Test-Path $cfExe)) {
    Log "ERROR: cloudflared.exe not found at $cfExe"
    return
}
"" | Out-File -FilePath $tunLog -Encoding utf8
Log "Starting cloudflared..."
$tun = Start-Process -FilePath $cfExe `
    -ArgumentList "tunnel","--url","http://localhost:5000" `
    -WorkingDirectory $repo `
    -RedirectStandardOutput $tunLog `
    -RedirectStandardError "$tunLog.err" `
    -WindowStyle Hidden `
    -PassThru
Log "cloudflared PID: $($tun.Id)"

# 6) Wait for tunnel URL to appear in either stdout or stderr log.
#    Cloudflared writes its registration banner to stderr.
$url = $null
for ($i = 0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 1
    foreach ($candidate in @($tunLog, "$tunLog.err")) {
        if (Test-Path $candidate) {
            $match = Select-String -Path $candidate -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($match) {
                $url = [regex]::Match($match.Line, 'https://[a-z0-9-]+\.trycloudflare\.com').Value
                break
            }
        }
    }
    if ($url) { break }
}

if ($url) {
    # Write WITHOUT a BOM (Set-Content -Encoding utf8 adds one on Win PS 5,
    # which makes the file unreadable by curl/wget downstream).
    [System.IO.File]::WriteAllText($urlFile, $url)
    Log "TUNNEL URL: $url"

    # Toast notification visible to user when logged in
    try {
        Add-Type -AssemblyName System.Windows.Forms
        $notify = New-Object System.Windows.Forms.NotifyIcon
        $notify.Icon = [System.Drawing.SystemIcons]::Information
        $notify.Visible = $true
        $msg = "Public URL: $url`r`nLogin saved in tunnel\credentials.json"
        $notify.ShowBalloonTip(8000, "Battery Manager online", $msg, [System.Windows.Forms.ToolTipIcon]::Info)
        Start-Sleep -Seconds 2
        $notify.Dispose()
    } catch { Log "Toast notification skipped: $_" }
} else {
    Log "Tunnel URL not visible after 30s, check tunnel.log"
}

Log "autostart complete"
