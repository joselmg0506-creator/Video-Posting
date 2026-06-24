# Pushes your LOCAL .env + secrets/ to GitHub repo Secrets (encrypted), and uploads the
# gameplay b-roll to a GitHub Release, so the Actions workflow can run the pipeline in the
# cloud. Secrets are never committed to the repo — they go into encrypted GitHub Secrets.
#
# Prereqs: GitHub CLI installed + authenticated:  winget install GitHub.cli  ;  gh auth login
#
#   .\scripts\setup_github_secrets.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    throw "GitHub CLI (gh) not found. Install: winget install GitHub.cli  then: gh auth login"
}

Write-Host "1/3  .env  ->  ENV_FILE secret"
if (-not (Test-Path ".env")) { throw "No .env found." }
gh secret set ENV_FILE < .env

Write-Host "2/3  secrets/  ->  SECRETS_TAR_B64 secret"
if (-not (Test-Path "secrets")) { throw "No secrets/ folder found." }
tar -czf secrets.tgz secrets
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path "secrets.tgz")))
$tmp = New-TemporaryFile
Set-Content -Path $tmp -Value $b64 -NoNewline
gh secret set SECRETS_TAR_B64 < $tmp
Remove-Item secrets.tgz, $tmp -Force

Write-Host "3/3  gameplay b-roll  ->  'assets' release"
$mp4 = @(Get-ChildItem "data\broll_gameplay\*.mp4" -ErrorAction SilentlyContinue)
if ($mp4.Count -gt 0) {
    gh release view assets *> $null 2>&1
    if ($LASTEXITCODE -ne 0) {
        gh release create assets -t "Pipeline assets" -n "Gameplay b-roll for the stories channel"
    }
    gh release upload assets ($mp4.FullName) --clobber
    Write-Host "   uploaded $($mp4.Count) gameplay clip(s)"
} else {
    Write-Host "   (no gameplay in data\broll_gameplay — skipping; add clips + re-run if you want the stories channel)"
}

Write-Host ""
Write-Host "Done. Secrets pushed. Next: commit data/state.json (dedup history) + the workflows, then push."
