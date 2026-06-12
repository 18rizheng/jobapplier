# Registers the daily 8:00 AM discovery sweep as a Windows scheduled task.
# Run once, manually:  powershell -ExecutionPolicy Bypass -File scripts\register_daily_task.ps1

$repo = Split-Path $PSScriptRoot -Parent
$action = New-ScheduledTaskAction `
    -Execute "$repo\.venv\Scripts\python.exe" `
    -Argument "-u run_discovery.py" `
    -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)
Register-ScheduledTask -TaskName "jobapplier-daily-discovery" `
    -Action $action -Trigger $trigger -Settings $settings `
    -Description "Daily job discovery + scoring sweep for the jobapplier pipeline" -Force
Write-Host "Registered. The sweep runs daily at 8:00 AM; review with review.py afterwards."
