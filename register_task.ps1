$scriptPath = "C:\Users\ratha\Downloads\RATAN YRCARKIT\YRCARKIT\auto_push.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 2)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "YRCARKIT_AutoPush" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description "Auto-commit and push YRCARKIT changes to GitHub every 2 minutes" -Force | Out-Null
Get-ScheduledTask -TaskName "YRCARKIT_AutoPush" | Select-Object TaskName, State
