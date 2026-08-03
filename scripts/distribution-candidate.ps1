param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$RequireInstaller,
    [switch]$BuildPackages
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }
if ($BuildPackages) {
    Write-Host "==> build frozen portable package and installer evidence" -ForegroundColor Cyan
    & (Join-Path $repo "scripts\build.ps1") -Python $Python
    if ($LASTEXITCODE -ne 0) { throw "Package build failed." }
}

$tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("s-talking-distribution-{0}.py" -f ([guid]::NewGuid().ToString("N")))
$require = if ($RequireInstaller) { "True" } else { "False" }
$code = @"
from app.config.runtime import RuntimeConfig
from app.container import create_service_container

container = create_service_container(RuntimeConfig.from_root())
snapshot = container.distribution_readiness_service.build_distribution(require_installer=$require)
print(f"Status:    {snapshot.status}")
print(f"Version:   {snapshot.version}")
print(f"Installer: {'included' if snapshot.installer_distributable else 'portable only'}")
print(f"Bundle:    {snapshot.bundle_dir}")
print(f"Artifacts: {len(snapshot.artifacts)}")
if not snapshot.ready:
    raise SystemExit(1)
"@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($tempScript, $code, $utf8NoBom)
try {
    Write-Host "==> build and verify distribution bundle" -ForegroundColor Cyan
    & $pythonPath $tempScript
    if ($LASTEXITCODE -ne 0) { throw "Distribution bundle build or verification failed." }
    Write-Host "Distribution bundle created and verified." -ForegroundColor Green
} finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}
