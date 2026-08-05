param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$TargetVersion = "1.0.0",
    [int]$ExpectedTests = 850,
    [string]$SourceCommit = "",
    [switch]$SkipReleaseCheck,
    [switch]$PreparePromotionPlan,
    [switch]$AcknowledgePromotionPlan,
    [string]$VerifyAttestation = ""
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path

if ($VerifyAttestation) {
    & $Python -m app.frozen_main `
        --verify-production-attestation $VerifyAttestation
    exit $LASTEXITCODE
}

if (-not $SkipReleaseCheck) {
    Write-Host "==> Full release check" -ForegroundColor Cyan
    powershell -ExecutionPolicy Bypass `
        -File .\scripts\release-check.ps1 `
        -Python $Python
    if ($LASTEXITCODE -ne 0) {
        throw "Release check failed; production certification was not attempted."
    }
}

$argsList = @(
    "-m", "app.frozen_main",
    "--production-certification",
    "--production-certification-export",
    "--refresh-production-evidence",
    "--target-version", $TargetVersion,
    "--expected-tests", "$ExpectedTests"
)
if ($SourceCommit) {
    $argsList += @("--source-commit", $SourceCommit)
}
if ($PreparePromotionPlan) {
    $argsList += "--prepare-production-promotion-plan"
}
if ($AcknowledgePromotionPlan) {
    $argsList += "--acknowledge-production-plan"
}

Write-Host "==> Production release certification" -ForegroundColor Cyan
& $Python @argsList
$exitCode = $LASTEXITCODE

$latest = Join-Path $repo "artifacts\production-certification\production-release-attestation.json"
if (Test-Path $latest) {
    Write-Host "Attestation: $latest" -ForegroundColor Green
}
exit $exitCode
