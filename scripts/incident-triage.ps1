param(
    [string]$BundlePath = "",

    [string]$ReceiptPath = "",

    [switch]$CreateCase,

    [switch]$Acknowledge,

    [string]$VerifyCase = "",

    [string]$VerifyPlan = ""
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

if ($VerifyCase) {
    $Arguments += @("--verify-incident-triage-case", $VerifyCase)
}
elseIf ($VerifyPlan) {
    $Arguments += @("--verify-incident-remediation-plan", $VerifyPlan)
}
else {
    $Arguments += if ($CreateCase) {
        "--create-incident-triage-case"
    }
    else {
        "--incident-triage-snapshot"
    }

    if ($BundlePath) {
        $Arguments += @("--incident-triage-bundle", $BundlePath)
    }
    if ($ReceiptPath) {
        $Arguments += @("--incident-triage-receipt", $ReceiptPath)
    }
    if ($Acknowledge) {
        $Arguments += "--acknowledge-incident-triage"
    }
}

& $Python @Arguments

if ($LASTEXITCODE -ne 0) {
    throw "Incident triage command failed with exit code $LASTEXITCODE."
}
