param(
    [int]$ProjectId = -1,
    [int]$MinimumSessions = 3,
    [switch]$CreateGovernance,
    [string]$Owner = "",
    [string]$Statement = "",
    [switch]$Acknowledge
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
    "--provider-governance-snapshot",
    "--provider-governance-minimum-sessions",
    $MinimumSessions
)

if ($ProjectId -ge 0) {
    $Arguments += @("--provider-governance-project-id", $ProjectId)
}
if ($CreateGovernance) {
    $Arguments += "--create-provider-governance"
    $Arguments += @("--provider-governance-owner", $Owner)
    $Arguments += @("--provider-governance-statement", $Statement)
}
if ($Acknowledge) {
    $Arguments += "--acknowledge-provider-governance"
}

& $Python @Arguments
exit $LASTEXITCODE
