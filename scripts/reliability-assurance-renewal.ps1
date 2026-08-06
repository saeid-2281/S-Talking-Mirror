param(
    [string[]]$Attestation = @(),
    [string[]]$AuditPack = @(),
    [string[]]$SourceReceipt = @(),
    [ValidateRange(7, 3650)]
    [int]$ValidityDays = 90,
    [ValidateRange(1, 365)]
    [int]$DueSoonDays = 14,
    [switch]$CreateRenewal,
    [ValidateSet("renew", "renew_with_follow_up", "withhold_renewal")]
    [string]$Outcome = "renew",
    [string]$Owner = "",
    [string]$Statement = "",
    [string]$FollowUpOwner = "",
    [string]$NextReviewDate = "",
    [string]$VerifyRenewal = "",
    [string]$VerifyFollowUp = "",
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

if ($VerifyRenewal) {
    $Arguments += @("--verify-reliability-renewal", $VerifyRenewal)
}
elseif ($VerifyFollowUp) {
    $Arguments += @("--verify-reliability-renewal-follow-up", $VerifyFollowUp)
}
elseif ($VerifyPack) {
    if (-not $Receipt) {
        throw "-Receipt is required when verifying a renewal audit pack."
    }
    $Arguments += @(
        "--verify-reliability-renewal-pack", $VerifyPack,
        "--reliability-renewal-receipt", $Receipt
    )
}
elseif ($CreateRenewal) {
    $Arguments += @(
        "--create-reliability-renewal",
        "--reliability-renewal-outcome", $Outcome,
        "--reliability-renewal-owner", $Owner,
        "--reliability-renewal-statement", $Statement,
        "--reliability-renewal-follow-up-owner", $FollowUpOwner,
        "--reliability-renewal-next-review", $NextReviewDate
    )
}
else {
    $Arguments += "--reliability-renewal-snapshot"
}

foreach ($Path in $Attestation) {
    $Arguments += @("--reliability-renewal-attestation", $Path)
}
foreach ($Path in $AuditPack) {
    $Arguments += @("--reliability-renewal-audit-pack", $Path)
}
foreach ($Path in $SourceReceipt) {
    $Arguments += @("--reliability-renewal-source-receipt", $Path)
}
$Arguments += @(
    "--reliability-renewal-validity-days", $ValidityDays,
    "--reliability-renewal-due-soon-days", $DueSoonDays
)
if ($Acknowledge) {
    $Arguments += "--acknowledge-reliability-renewal"
}

Push-Location $ProjectRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
