param(
    [switch]$Create,
    [switch]$Export,
    [string]$Reviewer = "",
    [string]$Statement = "",
    [int]$MinimumTests = 1100,
    [string]$SourceCommit = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment Python not found: $Python"
}

$argsList = @(
    "-m", "app.frozen_main",
    "--final-production-certification",
    "--final-production-minimum-tests", "$MinimumTests"
)
if ($SourceCommit) {
    $argsList += @("--final-production-source-commit", $SourceCommit)
}
if ($Export) {
    $argsList += "--export-final-production-certification"
}
if ($Create) {
    $argsList += @(
        "--create-final-production-certification",
        "--final-production-reviewer", $Reviewer,
        "--final-production-statement", $Statement,
        "--acknowledge-final-production-certification"
    )
}

& $Python @argsList
exit $LASTEXITCODE
