param(
    [Parameter(Mandatory = $false)]
    [string]$Summary = "",

    [ValidateSet("low", "medium", "high", "critical")]
    [string]$Severity = "medium",

    [string]$BaselinePath = "",

    [int]$MaxLogAgeDays = 14,

    [int]$MaxBundleMB = 16,

    [switch]$ExcludeLogs,

    [switch]$CreateBundle,

    [switch]$Acknowledge,

    [string]$VerifyBundle = "",

    [string]$VerifyReceipt = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python was not found: $Python"
}

Set-Location $ProjectRoot

$Arguments = @("-m", "app.frozen_main")

if ($VerifyBundle) {
    $Arguments += @("--verify-incident-support-bundle", $VerifyBundle)
}
elseIf ($VerifyReceipt) {
    $Arguments += @("--verify-incident-support-receipt", $VerifyReceipt)
}
else {
    if ([string]::IsNullOrWhiteSpace($Summary)) {
        throw "Summary is required for an incident support snapshot or bundle."
    }

    $Arguments += if ($CreateBundle) {
        "--create-incident-support-bundle"
    }
    else {
        "--incident-support-snapshot"
    }

    $Arguments += @(
        "--incident-summary", $Summary,
        "--incident-severity", $Severity,
        "--max-support-log-age-days", [string]$MaxLogAgeDays,
        "--max-support-bundle-mb", [string]$MaxBundleMB
    )

    if ($BaselinePath) {
        $Arguments += @("--post-ga-baseline", $BaselinePath)
    }
    if ($ExcludeLogs) {
        $Arguments += "--exclude-support-logs"
    }
    if ($Acknowledge) {
        $Arguments += "--acknowledge-incident-support"
    }
}

& $Python @Arguments

if ($LASTEXITCODE -ne 0) {
    throw "Incident support command failed with exit code $LASTEXITCODE."
}
