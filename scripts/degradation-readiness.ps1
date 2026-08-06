param(
    [switch]$Snapshot,
    [switch]$CreatePlan,
    [switch]$CreateResult,
    [switch]$Acknowledge,
    [string]$Scenario = "provider_throttle",
    [string]$Owner = "",
    [string]$Statement = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project Python was not found: $Python"
}

$Arguments = @("-m", "app.frozen_main")
if ($CreatePlan) { $Arguments += "--create-degradation-plan" }
elseif ($CreateResult) { $Arguments += "--create-degradation-result" }
else { $Arguments += "--degradation-snapshot" }
$Arguments += @("--degradation-scenario", $Scenario)
if ($Owner) { $Arguments += @("--degradation-owner", $Owner) }
if ($Statement) { $Arguments += @("--degradation-statement", $Statement) }
if ($Acknowledge) { $Arguments += "--acknowledge-degradation" }

& $Python @Arguments
exit $LASTEXITCODE
