# Register a Windows Scheduled Task that runs start-headless.ps1 at user logon.
# Run this script ONCE to install the autostart. After that, Flask + tunnel
# come up automatically every time you log in (including after a reboot).
#
# To uninstall: Unregister-ScheduledTask -TaskName "BatteryUI_AutoStart" -Confirm:$false

$scriptPath = Join-Path $PSScriptRoot "start-headless.ps1"

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -NonInteractive -File `"$scriptPath`""

# Trigger at logon for current user
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

# Restart on failure (up to 3 times, 1 minute apart)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)   # never time out

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName "BatteryUI_AutoStart" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Auto-start Flask + Cloudflare tunnel for Ratans Private Battery Manager at logon" `
    -Force | Out-Null

Write-Output ""
Write-Output "Registered: BatteryUI_AutoStart"
Get-ScheduledTask -TaskName "BatteryUI_AutoStart" | Format-List TaskName, State, Description
Write-Output ""
Write-Output "It will fire on next logon. To run it now without rebooting:"
Write-Output "  Start-ScheduledTask -TaskName BatteryUI_AutoStart"
Write-Output ""
Write-Output "To check status:"
Write-Output "  Get-ScheduledTaskInfo -TaskName BatteryUI_AutoStart"
