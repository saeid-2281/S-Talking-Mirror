param(
    [string[]]$ClosurePath = @(),

    [ValidateRange(7, 3650)]
    [int]$LookbackDays = 90,

    [ValidateRange(2, 20)]
    [int]$RecurrenceThreshold = 2,

    [ValidateRange(50, 100)]
    [int]$HighRiskThreshold = 70,

    [switch]$CreateBaseline,

    [switch]$Acknowledge,

    [string]$VerifyBaseline = "",

    [string]$VerifyRegister = ""
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

if ($VerifyBaseline) {
    $Arguments += @("--verify-incident-prevention-baseline", $VerifyBaseline)
}
elseIf ($VerifyRegister) {
    $Arguments += @("--verify-preventive-action-register", $VerifyRegister)
}
else {
    $Arguments += if ($CreateBaseline) {
        "--create-incident-prevention-baseline"
    }
    else {
        "--incident-prevention-snapshot"
    }
    foreach ($Path in $ClosurePath) {
        $Arguments += @("--incident-prevention-closure", $Path)
    }
    $Arguments += @(
        "--incident-prevention-lookback-days", $LookbackDays,
        "--incident-prevention-recurrence-threshold", $RecurrenceThreshold,
        "--incident-prevention-high-risk-threshold", $HighRiskThreshold
    )
    if ($Acknowledge) {
        $Arguments += "--acknowledge-incident-prevention"
    }
}

& $Python @Arguments

if ($LASTEXITCODE -ne 0) {
    throw "Incident prevention command failed with exit code $LASTEXITCODE."
}
