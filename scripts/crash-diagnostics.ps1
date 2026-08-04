[CmdletBinding()]
param(
    [switch]$Snapshot,
    [switch]$Export,
    [string]$AcknowledgeCrash = "",
    [string]$VerifyBundle = "",
    [switch]$LaunchSafeMode,
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not $Python) {
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
        $Python = $venvPython
    }
    else {
        $Python = "python"
    }
}

if ($LaunchSafeMode) {
    Write-Host "Starting S Talking in safe mode..." -ForegroundColor Cyan
    Start-Process -FilePath $Python -ArgumentList @("-m", "app.frozen_main", "--safe-mode") -WorkingDirectory $ProjectRoot
    exit 0
}

$arguments = @("-m", "app.frozen_main")
if ($Snapshot -or (-not $Export -and -not $AcknowledgeCrash -and -not $VerifyBundle)) {
    $arguments += "--crash-recovery-snapshot"
}
if ($Export) {
    $arguments += "--export-crash-diagnostics"
}
if ($AcknowledgeCrash) {
    $arguments += @("--acknowledge-crash", $AcknowledgeCrash)
}
if ($VerifyBundle) {
    $arguments += @("--verify-crash-bundle", $VerifyBundle)
}

& $Python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Crash diagnostics command failed with exit code $LASTEXITCODE."
}
