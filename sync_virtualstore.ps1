# Auto-sync YRCARKIT VirtualStore data to Flask UI folder
# Runs continuously, copying any new/changed .db files every 30 seconds
$src = "C:\Users\ratha\AppData\Local\VirtualStore\Windows\SysWOW64\w_lxdzdb"
$dst = "C:\Users\ratha\Downloads\RATAN YRCARKIT\YRCARKIT\w_lxdzdb"

if (-not (Test-Path $src)) { Write-Host "Source folder does not exist: $src"; exit 1 }
if (-not (Test-Path $dst)) { Write-Host "Dest folder does not exist: $dst"; exit 1 }

Write-Host "[sync] Watching $src -> $dst"
while ($true) {
    try {
        # robocopy /MIR-like behavior but only copying newer files (not deleting)
        robocopy $src $dst "A*.db" /XO /NJH /NJS /NDL /NC /NS /NP > $null 2>&1
    } catch {
        Write-Host "[sync] error: $_"
    }
    Start-Sleep -Seconds 30
}
