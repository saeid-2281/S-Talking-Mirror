$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Missing virtual environment: .venv" -ForegroundColor Red
    Write-Host "Create it and install the project before running S Talking."
    exit 1
}

& $Python -m app.gui.main
