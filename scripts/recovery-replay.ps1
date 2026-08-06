param(
    [switch]$Snapshot,
    [switch]$CreatePlan,
    [switch]$CreateResult,
    [switch]$Acknowledge,
    [int]$ExpectedJobs = 10,
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
if ($CreatePlan) { $Arguments += "--create-recovery-replay-plan" }
elseif ($CreateResult) { $Arguments += "--create-recovery-replay-result" }
else { $Arguments += "--recovery-replay-snapshot" }
$Arguments += @("--recovery-replay-expected-jobs", "$ExpectedJobs")
if ($Owner) { $Arguments += @("--recovery-replay-owner", $Owner) }
if ($Statement) { $Arguments += @("--recovery-replay-statement", $Statement) }
if ($Acknowledge) { $Arguments += "--acknowledge-recovery-replay" }

& $Python @Arguments
exit $LASTEXITCODE
