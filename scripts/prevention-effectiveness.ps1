param(
    [string]$Baseline = "",
    [string]$Register = "",
    [string[]]$Closure = @(),
    [ValidateRange(7, 3650)]
    [int]$ObservationDays = 30,
    [switch]$CreateReview,
    [ValidateSet(
        "continue_monitoring",
        "escalate_prevention",
        "accept_residual_risk",
        "close_effective"
    )]
    [string]$Decision = "continue_monitoring",
    [string]$Rationale = "",
    [switch]$RecordAttestation,
    [string]$ActionCode = "",
    [ValidateSet("completed", "deferred", "risk_accepted")]
    [string]$ActionStatus = "completed",
    [string]$Owner = "",
    [string]$Evidence = "",
    [string]$EvidenceReference = "",
    [string]$VerifyAttestation = "",
    [string]$VerifyReview = "",
    [string]$VerifyDecision = "",
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

if ($VerifyAttestation) {
    $Arguments += @("--verify-preventive-action-attestation", $VerifyAttestation)
}
elseif ($VerifyReview) {
    $Arguments += @("--verify-prevention-effectiveness-review", $VerifyReview)
}
elseif ($VerifyDecision) {
    $Arguments += @("--verify-prevention-effectiveness-decision", $VerifyDecision)
}
elseif ($RecordAttestation) {
    $Arguments += @(
        "--record-preventive-action-attestation",
        "--preventive-action-code", $ActionCode,
        "--preventive-action-status", $ActionStatus,
        "--preventive-action-owner", $Owner,
        "--preventive-action-evidence", $Evidence,
        "--preventive-action-reference", $EvidenceReference
    )
}
elseif ($CreateReview) {
    $Arguments += @(
        "--create-prevention-effectiveness-review",
        "--prevention-review-decision", $Decision,
        "--prevention-review-rationale", $Rationale
    )
}
else {
    $Arguments += "--prevention-effectiveness-snapshot"
}

if ($Baseline) {
    $Arguments += @("--prevention-baseline", $Baseline)
}
if ($Register) {
    $Arguments += @("--preventive-action-register", $Register)
}
foreach ($Path in $Closure) {
    $Arguments += @("--prevention-effectiveness-closure", $Path)
}
$Arguments += @("--prevention-observation-days", $ObservationDays)
if ($Acknowledge) {
    $Arguments += "--acknowledge-prevention-effectiveness"
}

Push-Location $ProjectRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
