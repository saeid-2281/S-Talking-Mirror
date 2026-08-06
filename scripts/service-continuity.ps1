param(
    [string[]]$Renewal = @(),
    [string[]]$FollowUp = @(),
    [string[]]$AuditPack = @(),
    [string[]]$SourceReceipt = @(),
    [string[]]$Backup = @(),
    [ValidateRange(1, 10080)]
    [int]$RtoMinutes = 60,
    [ValidateRange(0, 43200)]
    [int]$RpoMinutes = 1440,
    [ValidateRange(1, 3650)]
    [int]$DrillWindowDays = 90,
    [switch]$CreatePlan,
    [ValidateSet("isolated_sandbox", "staging_clone", "offline_validation")]
    [string]$Environment = "isolated_sandbox",
    [string]$Owner = "",
    [string]$Notes = "",
    [switch]$RecordResult,
    [string]$Plan = "",
    [ValidateRange(0, 10080)]
    [int]$ActualRestoreMinutes = 0,
    [ValidateRange(0, 43200)]
    [int]$ObservedDataLossMinutes = 0,
    [ValidateSet("ok", "not_applicable", "failed")]
    [string]$DatabaseCheck = "not_applicable",
    [switch]$ManifestVerified,
    [ValidateRange(1, 100000)]
    [int]$RegressionTests = 1,
    [ValidateRange(0, 100000)]
    [int]$FailedTests = 0,
    [string]$Conclusion = "",
    [string]$VerifyPlan = "",
    [string]$VerifyResult = "",
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

if ($VerifyPlan) {
    $Arguments += @("--verify-service-continuity-plan", $VerifyPlan)
}
elseif ($VerifyResult) {
    $Arguments += @("--verify-service-continuity-result", $VerifyResult)
}
elseif ($VerifyAttestation) {
    $Arguments += @("--verify-service-continuity-attestation", $VerifyAttestation)
}
elseif ($VerifyPack) {
    if (-not $Receipt) {
        throw "-Receipt is required when verifying a continuity audit pack."
    }
    $Arguments += @(
        "--verify-service-continuity-pack", $VerifyPack,
        "--service-continuity-receipt", $Receipt
    )
}
elseif ($RecordResult) {
    if (-not $Plan) {
        throw "-Plan is required when recording a continuity drill result."
    }
    $Arguments += @(
        "--record-service-continuity-result",
        "--service-continuity-plan", $Plan,
        "--service-continuity-actual-restore-minutes", $ActualRestoreMinutes,
        "--service-continuity-observed-data-loss-minutes", $ObservedDataLossMinutes,
        "--service-continuity-database-check", $DatabaseCheck,
        "--service-continuity-regression-tests", $RegressionTests,
        "--service-continuity-failed-tests", $FailedTests,
        "--service-continuity-owner", $Owner,
        "--service-continuity-conclusion", $Conclusion
    )
    if ($ManifestVerified) {
        $Arguments += "--service-continuity-manifest-verified"
    }
}
elseif ($CreatePlan) {
    $Arguments += @(
        "--create-service-continuity-plan",
        "--service-continuity-environment", $Environment,
        "--service-continuity-owner", $Owner,
        "--service-continuity-notes", $Notes
    )
}
else {
    $Arguments += "--service-continuity-snapshot"
}

foreach ($Path in $Renewal) {
    $Arguments += @("--service-continuity-renewal", $Path)
}
foreach ($Path in $FollowUp) {
    $Arguments += @("--service-continuity-follow-up", $Path)
}
foreach ($Path in $AuditPack) {
    $Arguments += @("--service-continuity-audit-pack", $Path)
}
foreach ($Path in $SourceReceipt) {
    $Arguments += @("--service-continuity-source-receipt", $Path)
}
foreach ($Path in $Backup) {
    $Arguments += @("--service-continuity-backup", $Path)
}
$Arguments += @(
    "--service-continuity-rto-minutes", $RtoMinutes,
    "--service-continuity-rpo-minutes", $RpoMinutes,
    "--service-continuity-window-days", $DrillWindowDays
)
if ($Acknowledge) {
    $Arguments += "--acknowledge-service-continuity"
}

Push-Location $ProjectRoot
try {
    & $Python @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
