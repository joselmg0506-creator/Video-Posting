# Unregisters all VideoPOsting scheduled tasks.
#   .\scripts\remove_schedule.ps1
$ErrorActionPreference = "Stop"
$tasks = Get-ScheduledTask -TaskName "VideoPOsting_*" -ErrorAction SilentlyContinue
if (-not $tasks) {
    Write-Host "No VideoPOsting scheduled tasks found."
    return
}
foreach ($t in $tasks) {
    Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
    Write-Host "Removed $($t.TaskName)"
}
