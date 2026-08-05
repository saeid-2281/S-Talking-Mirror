param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$ProductionAttestation = ".\artifacts\production-certification\production-release-attestation.json",
    [ValidateRange(1, 100)]
    [int]$RolloutPercentage = 100,
    [switch]$BuildPackages,
    [switch]$RequireInstaller,
    [switch]$RequireSigning,
    [switch]$SkipReleaseCheck,
    [switch]$AcknowledgePromotion
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }
$attestationPath = (Resolve-Path $ProductionAttestation).Path
$resultRoot = Join-Path $repo "artifacts\stable-promotion"
$resultPath = Join-Path $resultRoot "stable-release-command-result.json"
New-Item -ItemType Directory -Force -Path $resultRoot | Out-Null

function Write-JsonUtf8NoBom {
    param([object]$Value, [string]$Path)
    $json = $Value | ConvertTo-Json -Depth 12
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json, $encoding)
}

if (-not $SkipReleaseCheck) {
    Write-Host "==> stable source release check" -ForegroundColor Cyan
    powershell -ExecutionPolicy Bypass `
        -File .\scripts\release-check.ps1 `
        -Python $Python
    if ($LASTEXITCODE -ne 0) {
        throw "Release check failed; stable promotion was not attempted."
    }
}

Write-Host "==> stable promotion preflight" -ForegroundColor Cyan
& $pythonPath -m app.frozen_main `
    --stable-promotion-snapshot `
    --production-attestation $attestationPath `
    --stable-rollout $RolloutPercentage
if ($LASTEXITCODE -ne 0) {
    throw "Stable promotion preflight failed."
}

if (-not $AcknowledgePromotion) {
    Write-Host "Preflight passed. Rerun with -AcknowledgePromotion to prepare the rollback point, build or verify artifacts, and write the local promotion receipt." -ForegroundColor Yellow
    Write-Host "No Git tag, push, upload, stable-channel network publication, install or restart was performed." -ForegroundColor Yellow
    exit 0
}

$tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("s-talking-stable-promotion-{0}.py" -f ([guid]::NewGuid().ToString("N")))
$env:S_TALKING_STABLE_ATTESTATION = $attestationPath
$env:S_TALKING_STABLE_ROLLOUT = [string]$RolloutPercentage
$env:S_TALKING_STABLE_RESULT = $resultPath
$prepareCode = @'
import json
import os
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.production_release_certification_service import ProductionReleaseCertificationService
from app.services.stable_release_promotion_service import StableReleasePromotionService

runtime = RuntimeConfig.from_root()
production = ProductionReleaseCertificationService(runtime)
service = StableReleasePromotionService(runtime, production)
attestation = Path(os.environ["S_TALKING_STABLE_ATTESTATION"])
rollout = int(os.environ["S_TALKING_STABLE_ROLLOUT"])
snapshot = service.snapshot(attestation_path=attestation, rollout_percentage=rollout)
if snapshot.blocker_count:
    raise SystemExit(snapshot.summary)
result = service.create_rollback_point(
    snapshot,
    attestation_path=attestation,
    acknowledge=True,
)
if result.get("status") != "prepared":
    raise SystemExit(str(result.get("detail") or "Rollback point preparation failed."))
Path(os.environ["S_TALKING_STABLE_RESULT"]).write_text(
    json.dumps(
        {
            "status": "rollback_prepared",
            "rollback_manifest": result["path"],
            "source_commit": snapshot.source_commit,
            "attested_commit": snapshot.attested_commit,
            "version": snapshot.version,
            "channel": snapshot.channel,
            "rollout_percentage": snapshot.rollout_percentage,
        },
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
print(f"Rollback:     {result['path']}")
'@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($tempScript, $prepareCode, $utf8NoBom)
try {
    Write-Host "==> prepare verified rollback point" -ForegroundColor Cyan
    & $pythonPath $tempScript
    if ($LASTEXITCODE -ne 0) { throw "Rollback point preparation failed." }
} finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}

if (!(Test-Path $resultPath)) { throw "Stable promotion command result is missing." }
$commandResult = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
$rollbackManifest = [string]$commandResult.rollback_manifest
if (!(Test-Path $rollbackManifest)) { throw "Verified rollback manifest is missing: $rollbackManifest" }

if ($BuildPackages) {
    Write-Host "==> build stable packages, distribution bundle and stable update feed" -ForegroundColor Cyan
    & (Join-Path $repo "scripts\final-release.ps1") `
        -Python $Python `
        -Channel stable `
        -RolloutPercentage $RolloutPercentage `
        -BuildPackages `
        -RequireInstaller:$RequireInstaller `
        -RequireSigning:$RequireSigning
    if ($LASTEXITCODE -ne 0) { throw "Stable package build or final-release verification failed." }
} else {
    Write-Host "==> verify existing stable artifacts" -ForegroundColor Cyan
}

$receiptScript = Join-Path ([System.IO.Path]::GetTempPath()) ("s-talking-stable-receipt-{0}.py" -f ([guid]::NewGuid().ToString("N")))
$env:S_TALKING_STABLE_ROLLBACK = $rollbackManifest
$env:S_TALKING_STABLE_REQUIRE_INSTALLER = if ($RequireInstaller) { "1" } else { "0" }
$env:S_TALKING_STABLE_REQUIRE_SIGNING = if ($RequireSigning) { "1" } else { "0" }
$receiptCode = @'
import json
import os
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.production_release_certification_service import ProductionReleaseCertificationService
from app.services.stable_release_promotion_service import StableReleasePromotionService

runtime = RuntimeConfig.from_root()
production = ProductionReleaseCertificationService(runtime)
service = StableReleasePromotionService(runtime, production)
attestation = Path(os.environ["S_TALKING_STABLE_ATTESTATION"])
rollback = Path(os.environ["S_TALKING_STABLE_ROLLBACK"])
rollout = int(os.environ["S_TALKING_STABLE_ROLLOUT"])
require_installer = os.environ["S_TALKING_STABLE_REQUIRE_INSTALLER"] == "1"
require_signing = os.environ["S_TALKING_STABLE_REQUIRE_SIGNING"] == "1"
snapshot = service.snapshot(
    attestation_path=attestation,
    rollout_percentage=rollout,
    include_artifact_gates=True,
    require_installer=require_installer,
    require_signatures=require_signing,
)
print(f"Status:       {snapshot.status}")
print(f"Blockers:     {snapshot.blocker_count}")
print(f"Warnings:     {snapshot.warning_count}")
for gate in snapshot.gates:
    if gate.status in {"warn", "block"}:
        print(f" - {gate.label} [{gate.status}]: {gate.detail}")
if snapshot.blocker_count:
    raise SystemExit(snapshot.summary)
result = service.write_promotion_receipt(
    snapshot,
    rollback_manifest=rollback,
    attestation_path=attestation,
    acknowledge=True,
    require_installer=require_installer,
    require_signatures=require_signing,
)
if result.get("status") != "verified":
    raise SystemExit(str(result.get("detail") or "Promotion receipt verification failed."))
receipt = Path(str(result["path"]))
ok, detail = service.verify_promotion_receipt(receipt)
if not ok:
    raise SystemExit(detail)
Path(os.environ["S_TALKING_STABLE_RESULT"]).write_text(
    json.dumps(
        {
            "status": "verified",
            "version": snapshot.version,
            "channel": snapshot.channel,
            "source_commit": snapshot.source_commit,
            "attested_commit": snapshot.attested_commit,
            "rollout_percentage": snapshot.rollout_percentage,
            "warning_count": snapshot.warning_count,
            "rollback_manifest": str(rollback),
            "promotion_receipt": str(receipt),
            "manual_publish_required": True,
            "automatic_tag": False,
            "automatic_push": False,
            "automatic_publish": False,
        },
        indent=2,
    ) + "\n",
    encoding="utf-8",
)
print(f"Receipt:      {receipt}")
print(f"Verification: {detail}")
'@
[System.IO.File]::WriteAllText($receiptScript, $receiptCode, $utf8NoBom)
try {
    Write-Host "==> verify stable artifacts and write promotion receipt" -ForegroundColor Cyan
    & $pythonPath $receiptScript
    if ($LASTEXITCODE -ne 0) { throw "Stable artifact certification or receipt verification failed." }
} finally {
    Remove-Item -LiteralPath $receiptScript -Force -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_STABLE_ATTESTATION -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_STABLE_ROLLOUT -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_STABLE_RESULT -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_STABLE_ROLLBACK -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_STABLE_REQUIRE_INSTALLER -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_STABLE_REQUIRE_SIGNING -ErrorAction SilentlyContinue
}

$finalResult = Get-Content -Raw -LiteralPath $resultPath | ConvertFrom-Json
Write-Host "Stable release artifacts are locally verified and promotion-eligible." -ForegroundColor Green
Write-Host "Version:      $($finalResult.version)" -ForegroundColor Green
Write-Host "Channel:      $($finalResult.channel)" -ForegroundColor Green
Write-Host "Receipt:      $($finalResult.promotion_receipt)" -ForegroundColor Green
Write-Host "Rollback:     $($finalResult.rollback_manifest)" -ForegroundColor Green
Write-Host "Publication remains manual: no Git tag, push, upload, install or restart was performed." -ForegroundColor Yellow
