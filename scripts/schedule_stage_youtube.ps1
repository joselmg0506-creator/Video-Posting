# Registers a daily Windows task that STAGES YouTube clips: it downloads the best moments from
# the priority creators (where YouTube isn't bot-blocked, i.e. your home IP) and pushes them to
# the cloud 'yt-clips' Release, which the cloud then posts from.
#
# It ONLY stages — it never posts — so it is safe to run alongside the cloud (the cloud is the
# sole poster; there is no double-post risk). Runs only while the laptop is on; if it's off at
# the scheduled time, it runs at the next opportunity (StartWhenAvailable).
#
#   .\scripts\schedule_stage_youtube.ps1                 # daily at 10:00
#   .\scripts\schedule_stage_youtube.ps1 -At 08:30       # custom time
# Remove with:  Unregister-ScheduledTask -TaskName VideoPOsting_StageYouTube -Confirm:$false
param([string]$At = "10:00")
$ErrorActionPreference = "Stop"

$proj = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $proj "scripts\run.ps1"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$argLine = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -StageYoutube"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory $proj
$trigger = New-ScheduledTaskTrigger -Daily -At $At
Register-ScheduledTask -TaskName "VideoPOsting_StageYouTube" -Action $action -Trigger $trigger `
    -Settings $settings -Description "VideoPOsting: stage top YouTube clips to the cloud cache (downloads only, never posts)" -Force | Out-Null
Write-Host "Registered VideoPOsting_StageYouTube -> daily at $At (stages YouTube clips; never posts)."
