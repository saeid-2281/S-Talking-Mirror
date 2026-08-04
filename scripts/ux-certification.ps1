param(
    [switch]$Export,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not $Python) {
    $Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python executable not found: $Python"
}

$arguments = @("-m", "app.frozen_main", "--ux-certification")
if ($Export) {
    $arguments += "--ux-certification-export"
}

Write-Host "==> UX, accessibility and theme certification"
& $Python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "UX certification failed."
}
