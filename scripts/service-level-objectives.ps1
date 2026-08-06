param(
    [string[]]$Observation = @(),
    [string[]]$ContinuityResult = @(),
    [string[]]$ContinuityAttestation = @(),
    [string[]]$ContinuityPack = @(),
    [string[]]$ContinuityReceipt = @(),
    [ValidateRange(1, 365)]
    [int]$WindowDays = 30,
    [ValidateRange(90.0, 100.0)]
    [double]$AvailabilityTarget = 99.9,
    [ValidateRange(90.0, 100.0)]
    [double]$SuccessTarget = 99.0,
    [ValidateRange(1, 600000)]
    [int]$P95LatencyTargetMs = 2000,
    [switch]$CreateObservation,
    [string]$WindowStart = "",
    [string]$WindowEnd = "",
    [ValidateRange(0, 1000000000)]
    [int]$TotalOperations = 0,
    [ValidateRange(0, 1000000000)]
    [int]$SuccessfulOperations = 0,
    [ValidateRange(0, 1000000000)]
    [int]$FailedOperations = 0,
    [ValidateRange(0, 525600)]
    [int]$UnavailableMinutes = 0,
    [ValidateRange(0, 600000)]
    [int]$ObservedP95LatencyMs = 0,
    [switch]$CreateDecision,
    [ValidateSet("allow", "manual_review", "hold")]
    [string]$Decision = "hold",
    [string]$Owner = "",
    [string]$Statement = "",
    [string]$Notes = "",
    [string]$VerifyObservation = "",
    [string]$VerifySnapshot = "",
    [string]$VerifyDecision = "",
    [string]$VerifyPack = "",
    [string]$Receipt = "",
    [switch]$Acknowledge
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python was not found: $Python"
}

$Arguments = @("-m", "app.frozen_main")

if ($VerifyObservation) {
    $Arguments += @("--verify-slo-observation", $VerifyObservation)
}
elseif ($VerifySnapshot) {
    $Arguments += @("--verify-slo-snapshot", $VerifySnapshot)
}
elseif ($VerifyDecision) {
    $Arguments += @("--verify-slo-decision", $VerifyDecision)
}
elseif ($VerifyPack) {
    if (-not $Receipt) {
        throw "-Receipt is required when verifying an SLO audit pack."
    }
    $Arguments += @("--verify-slo-pack", $VerifyPack, "--slo-receipt", $Receipt)
}
elseif ($CreateObservation) {
    $Arguments += @(
        "--create-slo-observation",
        "--slo-window-start", $WindowStart,
        "--slo-window-end", $WindowEnd,
        "--slo-total-operations", $TotalOperations,
        "--slo-successful-operations", $SuccessfulOperations,
        "--slo-failed-operations", $FailedOperations,
        "--slo-unavailable-minutes", $UnavailableMinutes,
        "--slo-observed-p95-latency-ms", $ObservedP95LatencyMs,
        "--slo-owner", $Owner,
        "--slo-notes", $Notes
    )
}
elseif ($CreateDecision) {
    $Arguments += @(
        "--create-slo-decision",
        "--slo-decision", $Decision,
        "--slo-owner", $Owner,
        "--slo-statement", $Statement
    )
}
else {
    $Arguments += "--slo-snapshot"
}

foreach ($Path in $Observation) {
    $Arguments += @("--slo-observation", $Path)
}
foreach ($Path in $ContinuityResult) {
    $Arguments += @("--slo-continuity-result", $Path)
}
foreach ($Path in $ContinuityAttestation) {
    $Arguments += @("--slo-continuity-attestation", $Path)
}
foreach ($Path in $ContinuityPack) {
    $Arguments += @("--slo-continuity-pack", $Path)
}
foreach ($Path in $ContinuityReceipt) {
    $Arguments += @("--slo-continuity-receipt", $Path)
}
$Arguments += @(
    "--slo-window-days", $WindowDays,
    "--slo-availability-target", $AvailabilityTarget,
    "--slo-success-target", $SuccessTarget,
    "--slo-p95-latency-target-ms", $P95LatencyTargetMs
)
if ($Acknowledge) {
    $Arguments += "--acknowledge-slo"
}

Push-Location $ProjectRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
