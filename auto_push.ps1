# Auto-commit + push YRCARKIT changes to GitHub
# Runs silently. Logs to auto_push.log in the repo root.

$repo = "C:\Users\ratha\Downloads\RATAN YRCARKIT\YRCARKIT"
$log  = Join-Path $repo "auto_push.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

Set-Location $repo

# Stage only .db files (new, modified, deleted)
git add -A -- "*.db" 2>&1 | Out-Null

# Any staged .db changes?
$staged = git diff --cached --name-only 2>&1
if (-not $staged) {
    Log "No DB changes."
    exit 0
}

$fileCount = ($staged | Measure-Object).Count
Log "Detected $fileCount changed DB file(s). Committing..."

$msg = "Auto-sync $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $fileCount DB file(s)"
$commitOut = git commit -m $msg 2>&1
Log ($commitOut -join " | ")

Log "Pushing to origin/main..."
$pushOut = git push origin main 2>&1
Log ($pushOut -join " | ")

if ($LASTEXITCODE -eq 0) {
    Log "Push complete."
} else {
    Log "Push failed with exit code $LASTEXITCODE"
}
