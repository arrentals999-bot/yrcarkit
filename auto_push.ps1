# Auto-commit + push YRCARKIT changes to GitHub
# Runs silently. Logs to auto_push.log in the repo root.

$ErrorActionPreference = "Stop"
$repo = "C:\Users\ratha\Downloads\RATAN YRCARKIT\YRCARKIT"
$log  = Join-Path $repo "auto_push.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

try {
    Set-Location $repo

    # Any changes? (tracked OR untracked)
    $changes = git status --porcelain
    if (-not $changes) {
        Log "No changes."
        exit 0
    }

    $fileCount = ($changes | Measure-Object).Count
    Log "Detected $fileCount changed file(s). Committing..."

    git add -A | Out-Null
    $msg = "Auto-sync $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $fileCount file(s)"
    git commit -m $msg 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

    Log "Pushing to origin/main..."
    git push origin main 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    Log "Push complete."
}
catch {
    Log "ERROR: $_"
    exit 1
}
