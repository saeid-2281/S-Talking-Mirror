param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$PromotionReceipt = ".\artifacts\stable-promotion\stable-release-promotion-receipt.json",
    [string]$StableFeed = ".\artifacts\update-channel\stable\latest.json",
    [string]$RollbackManifest = "",
    [ValidateRange(1, 365)]
    [int]$MaxEvidenceAgeDays = 30,
    [ValidateRange(64, 1000000)]
    [int]$MinimumFreeSpaceMB = 512,
    [ValidateRange(1, 100)]
    [int]$ExpectedStableRollout = 100,
    [switch]$RunQualityGate,
    [switch]$PreparePlan,
    [switch]$AcknowledgeMaintenance
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }

function Resolve-OptionalPath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return "" }
    if (!(Test-Path -LiteralPath $Value)) {
        throw "Required evidence path does not exist: $Value"
    }
    return (Resolve-Path -LiteralPath $Value).Path
}

$receiptPath = Resolve-OptionalPath $PromotionReceipt
$feedPath = Resolve-OptionalPath $StableFeed
$rollbackPath = Resolve-OptionalPath $RollbackManifest

$commonArgs = @(
    "-m", "app.frozen_main",
    "--post-ga-maintenance-snapshot",
    "--promotion-receipt", $receiptPath,
    "--stable-feed", $feedPath,
    "--max-evidence-age-days", [string]$MaxEvidenceAgeDays,
    "--minimum-free-space-mb", [string]$MinimumFreeSpaceMB,
    "--expected-stable-rollout", [string]$ExpectedStableRollout
)
if ($rollbackPath) {
    $commonArgs += @("--rollback-manifest", $rollbackPath)
}

Write-Host "==> post-GA maintenance preflight" -ForegroundColor Cyan
& $pythonPath @commonArgs
if ($LASTEXITCODE -ne 0) {
    throw "Post-GA maintenance preflight failed. No baseline or plan was written."
}

if ($RunQualityGate) {
    Write-Host "==> full quality gate" -ForegroundColor Cyan
    powershell -ExecutionPolicy Bypass `
        -File .\scripts\quality-gate.ps1 `
        -Full
    if ($LASTEXITCODE -ne 0) {
        throw "Quality gate failed. Post-GA baseline was not written."
    }
}

if (-not $AcknowledgeMaintenance) {
    Write-Host "Preflight passed. Rerun with -AcknowledgeMaintenance to write the verified baseline." -ForegroundColor Yellow
    Write-Host "No cleanup, publication, update, restart, Git action or artifact deletion was performed." -ForegroundColor Yellow
    exit 0
}

$writeArgs = $commonArgs + @(
    "--write-post-ga-baseline",
    "--acknowledge-post-ga-maintenance"
)
if ($PreparePlan) {
    $writeArgs += "--prepare-post-ga-maintenance-plan"
}

Write-Host "==> write and verify post-GA maintenance baseline" -ForegroundColor Cyan
& $pythonPath @writeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Post-GA maintenance baseline or plan verification failed."
}

Write-Host "Post-GA maintenance evidence is verified." -ForegroundColor Green
Write-Host "Baseline: .\artifacts\post-ga-maintenance\post-ga-maintenance-baseline.json" -ForegroundColor Green
if ($PreparePlan) {
    Write-Host "Plan:     .\artifacts\post-ga-maintenance\post-ga-maintenance-plan.json" -ForegroundColor Green
}
Write-Host "All operational changes remain manual; no cleanup, update, publication or restart was performed." -ForegroundColor Yellow
