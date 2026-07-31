param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

Write-Host "==> compileall"
& $Python -m compileall app
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> ruff"
& $Python -m ruff check app tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Full) {
    Write-Host "==> pytest (full)"
    & $Python -m pytest
} else {
    Write-Host "==> pytest (fast)"
    & $Python -m pytest -q `
        tests/test_product_centers_v020_phase_c.py `
        tests/test_generation_monitor_v08.py `
        tests/test_workspace_layout_v0181.py
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Quality gate passed."
