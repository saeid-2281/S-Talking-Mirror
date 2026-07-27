param(
    [switch]$Console,
    [ValidateSet("ffmpeg", "windows")]
    [string]$MediaBackend = "ffmpeg"
)

$ErrorActionPreference = "Stop"

# Usage examples:
#   .\scripts\run.ps1 -MediaBackend ffmpeg
#   .\scripts\run.ps1 -MediaBackend windows
#   .\scripts\run.ps1 -Console -MediaBackend ffmpeg

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PythonWindowed = Join-Path $Root ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $Python)) {
    Write-Host "Missing virtual environment: .venv" -ForegroundColor Red
    Write-Host "Create it and install the project before running S Talking."
    exit 1
}

$env:S_TALKING_MEDIA_BACKEND = $MediaBackend
$env:S_TALKING_GUI_CONSOLE = if ($Console) { "1" } else { "0" }

if ($Console -or -not (Test-Path $PythonWindowed)) {
    & $Python -m app.gui.main
    exit $LASTEXITCODE
}

# Normal production-style launch: no console window, therefore harmless FFmpeg
# decoder diagnostics cannot flood the terminal or confuse users.
Start-Process -FilePath $PythonWindowed -ArgumentList "-m", "app.gui.main" -WorkingDirectory $Root
