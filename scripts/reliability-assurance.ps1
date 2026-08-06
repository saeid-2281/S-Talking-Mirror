param(
    [string[]]$Review = @(),
    [string[]]$DecisionRecord = @(),
    [ValidateRange(7, 3650)]
    [int]$WindowDays = 90,
    [switch]$CreateAssurance,
    [ValidateSet("assure", "assure_with_exceptions", "withhold_assurance")]
    [string]$Outcome = "assure",
    [string]$Owner = "",
    [string]$Statement = "",
    [string]$ExceptionOwner = "",
    [string]$NextReviewDate = "",
    [string]$VerifyAttestation = "",
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

if ($VerifyAttestation) {
    $Arguments += @("--verify-reliability-assurance-attestation", $VerifyAttestation)
}
elseif ($VerifyPack) {
    if (-not $Receipt) {
        throw "-Receipt is required when verifying an audit pack."
    }
    $Arguments += @(
        "--verify-reliability-assurance-pack", $VerifyPack,
        "--reliability-assurance-receipt", $Receipt
    )
}
elseif ($CreateAssurance) {
    $Arguments += @(
        "--create-reliability-assurance",
        "--reliability-assurance-outcome", $Outcome,
        "--reliability-assurance-owner", $Owner,
        "--reliability-assurance-statement", $Statement,
        "--reliability-assurance-exception-owner", $ExceptionOwner,
        "--reliability-assurance-next-review", $NextReviewDate
    )
}
else {
    $Arguments += "--reliability-assurance-snapshot"
}

foreach ($Path in $Review) {
    $Arguments += @("--reliability-assurance-review", $Path)
}
foreach ($Path in $DecisionRecord) {
    $Arguments += @("--reliability-assurance-decision", $Path)
}
$Arguments += @("--reliability-assurance-window-days", $WindowDays)
if ($Acknowledge) {
    $Arguments += "--acknowledge-reliability-assurance"
}

Push-Location $ProjectRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
