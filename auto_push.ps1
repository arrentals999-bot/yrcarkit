# Auto-commit + push YRCARKIT changes to GitHub
# Scans the entire repo folder and pushes any tracked + new files
# (respects .gitignore for build artifacts, dlls, etc.)
# Runs silently. Logs to auto_push.log in the repo root.

$repo = "C:\Users\ratha\Downloads\RATAN YRCARKIT\YRCARKIT"
$log  = Join-Path $repo "auto_push.log"

function Log($msg) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8
}

Set-Location $repo

# Stage every change in the repo (new, modified, deleted)
# .gitignore filters out the noise (dlls, __pycache__, *.log, etc.)
git add -A 2>&1 | Out-Null

# Any staged changes at all?
$staged = git diff --cached --name-only 2>&1
if (-not $staged) {
    Log "No changes."
    exit 0
}

$fileCount = ($staged | Measure-Object).Count
Log "Detected $fileCount changed file(s). Committing..."

# Categorize for a more descriptive commit message
$dbCount    = ($staged | Where-Object { $_ -like "*.db" }    | Measure-Object).Count
$xlsxCount  = ($staged | Where-Object { $_ -like "*.xlsx" }  | Measure-Object).Count
$otherCount = $fileCount - $dbCount - $xlsxCount

$parts = @()
if ($dbCount    -gt 0) { $parts += "$dbCount db" }
if ($xlsxCount  -gt 0) { $parts += "$xlsxCount xlsx" }
if ($otherCount -gt 0) { $parts += "$otherCount other" }
$summary = $parts -join ", "

$msg = "Auto-sync $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') - $summary"
$commitOut = git commit -m $msg 2>&1
Log ($commitOut -join " | ")

# Pull --rebase first so a remote-only commit can't jam future pushes
Log "Rebasing on origin/main..."
$pullOut = git pull --rebase origin main 2>&1
Log ($pullOut -join " | ")
if ($LASTEXITCODE -ne 0) {
    Log "Rebase failed with exit code $LASTEXITCODE - aborting and bailing out"
    git rebase --abort 2>&1 | Out-Null
    exit 1
}

Log "Pushing to origin/main..."
$pushOut = git push origin main 2>&1
Log ($pushOut -join " | ")

if ($LASTEXITCODE -eq 0) {
    Log "Push complete."
} else {
    Log "Push failed with exit code $LASTEXITCODE"
}
