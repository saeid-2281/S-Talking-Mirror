param(
    [switch]$Snapshot,
    [switch]$VerifyObservation,
    [switch]$VerifySnapshot,
    [switch]$VerifyDecision,
    [switch]$VerifyPack,
    [string]$Path,
    [string]$Receipt
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project Python was not found: $Python"
}

$Arguments = @("-m", "app.frozen_main")
if ($Snapshot) { $Arguments += "--capacity-snapshot" }
if ($VerifyObservation) { $Arguments += @("--verify-capacity-observation", $Path) }
if ($VerifySnapshot) { $Arguments += @("--verify-capacity-snapshot", $Path) }
if ($VerifyDecision) { $Arguments += @("--verify-capacity-decision", $Path) }
if ($VerifyPack) {
    $Arguments += @("--verify-capacity-pack", $Path, "--capacity-receipt", $Receipt)
}
if ($Arguments.Count -eq 2) { $Arguments += "--capacity-snapshot" }

& $Python @Arguments
exit $LASTEXITCODE
