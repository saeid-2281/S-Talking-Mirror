param(
    [switch]$RefreshCertification,
    [int]$ProjectId = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python was not found: $python"
}

$argsList = @("-m", "app.frozen_main", "--evidence-refresh")
if ($ProjectId -gt 0) {
    $argsList += @("--evidence-refresh-project-id", "$ProjectId")
}
if ($RefreshCertification) {
    $argsList += "--refresh-certification-evidence"
}

& $python @argsList
exit $LASTEXITCODE
