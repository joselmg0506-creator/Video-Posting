# Registers Windows scheduled tasks that run the pipeline a few times a day.
# Default: 3 runs/day (morning / lunch / evening), 1 clip each = 3 Shorts/day, spaced out.
#
#   .\scripts\setup_schedule.ps1                       # 3x/day, posts if posting.enabled: true
#   .\scripts\setup_schedule.ps1 -DryRun               # 3x/day PREVIEW only (never posts)
#   .\scripts\setup_schedule.ps1 -Times 10:00,20:00    # custom times (1 clip each)
#
# Tasks are named VideoPOsting_Run_N. Re-running updates them. Remove with remove_schedule.ps1.
# Note: even without -DryRun, nothing posts until posting.enabled: true in config.yaml.
param(
    [string[]]$Times = @("09:00", "13:00", "19:00"),
    [int]$PerRun = 1,
    [string]$MetricsTime = "23:00",
    [switch]$DryRun
)
$ErrorActionPreference = "Stop"

$proj = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $proj "scripts\run.ps1"
$dry = if ($DryRun) { " -DryRun" } else { "" }
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)

for ($i = 0; $i -lt $Times.Count; $i++) {
    $name = "VideoPOsting_Run_$($i + 1)"
    $argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Max $PerRun$dry"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory $proj
    $trigger = New-ScheduledTaskTrigger -Daily -At $Times[$i]
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
        -Description "VideoPOsting: generate + post a YouTube Short" -Force | Out-Null
    Write-Host "Registered $name -> daily at $($Times[$i])  (Max $PerRun$dry)"
}

# Daily metrics digest (end of day).
$mArg = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Metrics"
$mAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $mArg -WorkingDirectory $proj
$mTrigger = New-ScheduledTaskTrigger -Daily -At $MetricsTime
Register-ScheduledTask -TaskName "VideoPOsting_Metrics" -Action $mAction -Trigger $mTrigger -Settings $settings `
    -Description "VideoPOsting: daily metrics digest to Discord" -Force | Out-Null
Write-Host "Registered VideoPOsting_Metrics -> daily at $MetricsTime"

Write-Host ""
Write-Host "Done. View/edit in Task Scheduler, or run: Get-ScheduledTask -TaskName VideoPOsting_*"
if (-not $DryRun) {
    Write-Host "Reminder: nothing posts until posting.enabled: true in config.yaml (+ YouTube OAuth)."
}
