# Auto-commit + push YRCARKIT changes to GitHub
# Runs silently. Logs to auto_push.log in the repo root.

$repo = "C:\Users\ratha\Downloads\RATAN YRCARKIT\YRCARKIT"
$log  = Join-Path $repo "auto_push.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

Set-Location $repo

# Any changes? (tracked OR untracked)
$changes = git status --porcelain 2>&1
if (-not $changes) {
    Log "No changes."
    exit 0
}

$fileCount = ($changes | Measure-Object).Count
Log "Detected $fileCount changed file(s). Committing..."

git add -A 2>&1 | Out-Null
$msg = "Auto-sync $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $fileCount file(s)"
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
