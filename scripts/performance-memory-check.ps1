param(
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "Project Python was not found: $python" }

& $python -m pytest `
    tests\test_final_performance_memory_phase86.py `
    tests\test_qt_runtime_performance_hardening_phase49.py `
    tests\test_performance_long_run_stability_phase57.py `
    tests\test_queue_mainwindow_migration_v021.py `
    tests\test_queue_table_model_v021_phase2.py `
    tests\test_operations_workspace_phase85.py `
    -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if ($Full) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\quality-gate.ps1 -Full
    exit $LASTEXITCODE
}
