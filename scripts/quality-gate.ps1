param(
    [switch]$Full,
    [string]$Workers = "auto",
    [switch]$LegacyFull
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
& $Python -m ruff check app tests scripts
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Full) {
    if ($LegacyFull -or $env:S_TALKING_LEGACY_FULL_GATE -eq "1") {
        Write-Host "==> pytest (full / legacy serial)"
        & $Python -m pytest
    } else {
        Write-Host "==> pytest (full / safe multi-process)"
        & $Python scripts/parallel_pytest.py `
            --workers $Workers `
            --report artifacts/quality-gate-performance/latest.json
    }
} else {
    Write-Host "==> pytest (fast)"
    & $Python -m pytest -q `
        tests/test_product_centers_v020_phase_c.py `
        tests/test_generation_monitor_v08.py `
        tests/test_workspace_layout_v0181.py
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Quality gate passed."
