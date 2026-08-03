param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$SkipChecks
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment Python not found: $Python"
}

if (-not $SkipChecks) {
    Write-Host "==> release checks"
    powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "release-check.ps1") -Python $Python
    if ($LASTEXITCODE -ne 0) {
        throw "Release checks failed. Candidate packaging was not started."
    }
}

Write-Host "==> build and verify release candidate"
$code = @'
from app.container import create_service_container

container = create_service_container()
snapshot = container.release_candidate_service.build_candidate()
print(f"Status:   {snapshot.status}")
print(f"Version:  {snapshot.version}")
print(f"Commit:   {snapshot.commit}")
print(f"Package:  {snapshot.package_path}")
print(f"Manifest: {snapshot.manifest_path}")
print(f"SHA file: {snapshot.checksum_path}")
if snapshot.status != "ready":
    raise SystemExit(2)
'@

$tempScript = Join-Path `
    ([System.IO.Path]::GetTempPath()) `
    ("s-talking-release-candidate-" + [guid]::NewGuid().ToString("N") + ".py")
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

try {
    # Windows PowerShell 5.1 can rewrite embedded quotes when a multiline
    # string is passed to a native executable through `python -c`. Writing
    # the payload to a UTF-8 file avoids that argument-quoting corruption.
    [System.IO.File]::WriteAllText($tempScript, $code, $utf8NoBom)

    & $Python $tempScript
    if ($LASTEXITCODE -ne 0) {
        throw "Release candidate build or verification failed."
    }
}
finally {
    Remove-Item `
        -LiteralPath $tempScript `
        -Force `
        -ErrorAction SilentlyContinue
}

Write-Host "Release candidate created and verified." -ForegroundColor Green
