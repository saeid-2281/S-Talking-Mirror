param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python was not found: $Python"
}

Set-Location $ProjectRoot

Write-Host "==> Phase 83 evidence-integrity compile check" -ForegroundColor Cyan
& $Python -m compileall `
    app\services\evidence_integrity.py `
    app\services\operations_command_center_service.py `
    app\services\evidence_refresh_service.py `
    app\services\operational_readiness_service.py
if ($LASTEXITCODE -ne 0) { throw "Phase 83 compile check failed." }

Write-Host "==> Phase 83 dedicated tests" -ForegroundColor Cyan
& $Python -m pytest tests\test_evidence_integrity_foundation_phase83.py -q
if ($LASTEXITCODE -ne 0) { throw "Phase 83 dedicated tests failed." }

if ($Full) {
    Write-Host "==> Full Quality Gate" -ForegroundColor Cyan
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
    if ($LASTEXITCODE -ne 0) { throw "Full Quality Gate failed." }
}

Write-Host "Evidence integrity foundation checks passed." -ForegroundColor Green
