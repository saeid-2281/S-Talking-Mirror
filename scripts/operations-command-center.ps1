param(
    [int]$ProjectId = -1,
    [switch]$ExportSnapshot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python was not found: $Python"
}

Set-Location $ProjectRoot

$Arguments = @(
    "-m",
    "app.frozen_main",
    "--operations-command-center-snapshot"
)

if ($ProjectId -ge 0) {
    $Arguments += @("--operations-command-center-project-id", $ProjectId)
}
if ($ExportSnapshot) {
    $Arguments += "--export-operations-command-center-snapshot"
}

& $Python @Arguments
exit $LASTEXITCODE
