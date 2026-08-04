param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [ValidateSet("preview", "beta", "stable")]
    [string]$Channel = "preview",
    [ValidateRange(1, 100)]
    [int]$RolloutPercentage = 100,
    [switch]$BuildPackages,
    [switch]$RequireInstaller,
    [switch]$RequireSigning
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }

if ($BuildPackages) {
    Write-Host "==> build frozen packages and signing evidence" -ForegroundColor Cyan
    & (Join-Path $repo "scripts\build.ps1") -Python $Python -RequireSigning:$RequireSigning
    if ($LASTEXITCODE -ne 0) { throw "Package build or signing failed." }

    Write-Host "==> rebuild verified distribution candidate" -ForegroundColor Cyan
    & (Join-Path $repo "scripts\distribution-candidate.ps1") -Python $Python -RequireInstaller:$RequireInstaller
    if ($LASTEXITCODE -ne 0) { throw "Distribution candidate build failed." }
}

$tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("s-talking-final-release-{0}.py" -f ([guid]::NewGuid().ToString("N")))
$env:S_TALKING_FINAL_CHANNEL = $Channel
$env:S_TALKING_FINAL_ROLLOUT = [string]$RolloutPercentage
$env:S_TALKING_FINAL_REQUIRE_INSTALLER = if ($RequireInstaller) { "1" } else { "0" }
$env:S_TALKING_FINAL_REQUIRE_SIGNING = if ($RequireSigning) { "1" } else { "0" }
$code = @'
import os
from app.config.runtime import RuntimeConfig
from app.container import create_service_container

container = create_service_container(RuntimeConfig.from_root())
service = container.final_release_service
channel = os.environ["S_TALKING_FINAL_CHANNEL"]
rollout = int(os.environ["S_TALKING_FINAL_ROLLOUT"])
require_installer = os.environ["S_TALKING_FINAL_REQUIRE_INSTALLER"] == "1"
require_signing = os.environ["S_TALKING_FINAL_REQUIRE_SIGNING"] == "1"
preview = service.snapshot(channel=channel, rollout_percentage=rollout)
print(f"Readiness: {preview.status}")
for gate in preview.gates:
    if not gate.passed:
        print(f" - {gate.label} [{gate.severity}]: {gate.detail}")
snapshot = service.build_final_release(
    channel=channel,
    rollout_percentage=rollout,
    require_installer=require_installer,
    require_signatures=require_signing,
)
print(f"Status:     {snapshot.status}")
print(f"Version:    {snapshot.version}")
print(f"Channel:    {snapshot.channel}")
print(f"Rollout:    {snapshot.rollout_percentage}%")
print(f"Signatures: app={'verified' if snapshot.executable_signed else 'unsigned'}; installer={'verified' if snapshot.installer_signed else 'unsigned/unavailable'}")
print(f"Bundle:     {snapshot.bundle_dir}")
print(f"Update feed:{snapshot.update_feed}")
print(f"Artifacts:  {len(snapshot.artifacts)}")
if not snapshot.ready:
    raise SystemExit(1)
'@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($tempScript, $code, $utf8NoBom)
try {
    Write-Host "==> build and verify final release package" -ForegroundColor Cyan
    & $pythonPath $tempScript
    if ($LASTEXITCODE -ne 0) { throw "Final release build or verification failed." }
    Write-Host "Final release package and update channel created and verified." -ForegroundColor Green
} finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_FINAL_CHANNEL -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_FINAL_ROLLOUT -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_FINAL_REQUIRE_INSTALLER -ErrorAction SilentlyContinue
    Remove-Item Env:S_TALKING_FINAL_REQUIRE_SIGNING -ErrorAction SilentlyContinue
}
