param(
    [switch]$Sync,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Project Python was not found: $python"
}

$argsList = @("-m", "app.frozen_main", "--operational-persistence")
if ($Sync) {
    $argsList += "--sync-operational-persistence"
}
if ($Verify) {
    $argsList += "--verify-operational-persistence"
}

& $python @argsList
exit $LASTEXITCODE
