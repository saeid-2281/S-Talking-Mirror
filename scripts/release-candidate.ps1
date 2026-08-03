param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment Python not found: $Python"
}

if (-not $SkipChecks) {
    Write-Host "==> release checks"
    powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "release-check.ps1") -Python $Python
    if ($LASTEXITCODE -ne 0) {
        throw "Release checks failed. Candidate packaging was not started."
    }
}

Write-Host "==> build and verify release candidate"
$code = @'
from app.container import create_service_container

container = create_service_container()
snapshot = container.release_candidate_service.build_candidate()
print(f"Status:   {snapshot.status}")
print(f"Version:  {snapshot.version}")
print(f"Commit:   {snapshot.commit}")
print(f"Package:  {snapshot.package_path}")
print(f"Manifest: {snapshot.manifest_path}")
print(f"SHA file: {snapshot.checksum_path}")
if snapshot.status != "ready":
    raise SystemExit(2)
'@

& $Python -c $code
if ($LASTEXITCODE -ne 0) {
    throw "Release candidate build or verification failed."
}

Write-Host "Release candidate created and verified." -ForegroundColor Green
