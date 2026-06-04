# Runs the VideoPOsting pipeline once. Used by Task Scheduler and for manual runs.
#
#   .\scripts\run.ps1                 # one run, posts if posting.enabled: true in config
#   .\scripts\run.ps1 -Max 1          # cap to 1 clip this run (a single scheduled slot)
#   .\scripts\run.ps1 -DryRun         # generate + stage only, never post
param(
    [int]$Max = 1,
    [switch]$DryRun,
    [switch]$Metrics      # run the daily metrics digest instead of the pipeline
)
$ErrorActionPreference = "Stop"

$proj = Split-Path -Parent $PSScriptRoot     # the project root (parent of scripts\)
Set-Location $proj

# Make sure ffmpeg/ffprobe resolve even in a bare scheduled-task environment.
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    $ff = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($ff) { $env:PATH = "$($ff.DirectoryName);$env:PATH" }
}
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = "1"

$py = Join-Path $proj ".venv\Scripts\python.exe"
if ($Metrics) {
    $pyArgs = @("main.py", "--metrics")
} else {
    $pyArgs = @("main.py", "--max-per-run", "$Max")
    if ($DryRun) { $pyArgs += "--dry-run" }
}

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm')] running: python $($pyArgs -join ' ')"
& $py @pyArgs
