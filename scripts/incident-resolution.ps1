param(
    [string]$CasePath = "",

    [string]$PlanPath = "",

    [string]$ResolutionSummary = "",

    [string]$CustomerImpact = "",

    [ValidateSet(
        "code_fix",
        "configuration_change",
        "rollback",
        "workaround",
        "data_repair",
        "no_fault_found"
    )]
    [string]$ResolutionType = "code_fix",

    [string[]]$EvidencePath = @(),

    [switch]$CreateClosure,

    [switch]$Acknowledge,

    [string]$VerifyResolution = "",

    [string]$VerifyClosure = "",

    [string]$VerifyKnowledge = ""
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

if ($VerifyResolution) {
    $Arguments += @("--verify-incident-resolution", $VerifyResolution)
}
elseIf ($VerifyClosure) {
    $Arguments += @("--verify-incident-closure", $VerifyClosure)
}
elseIf ($VerifyKnowledge) {
    $Arguments += @("--verify-incident-knowledge", $VerifyKnowledge)
}
else {
    if ([string]::IsNullOrWhiteSpace($ResolutionSummary)) {
        throw "ResolutionSummary is required for a closure snapshot or record."
    }
    if ([string]::IsNullOrWhiteSpace($CustomerImpact)) {
        throw "CustomerImpact is required for a closure snapshot or record."
    }

    $Arguments += if ($CreateClosure) {
        "--create-incident-resolution"
    }
    else {
        "--incident-resolution-snapshot"
    }

    if ($CasePath) {
        $Arguments += @("--incident-resolution-case", $CasePath)
    }
    if ($PlanPath) {
        $Arguments += @("--incident-resolution-plan", $PlanPath)
    }
    $Arguments += @(
        "--incident-resolution-summary", $ResolutionSummary,
        "--incident-customer-impact", $CustomerImpact,
        "--incident-resolution-type", $ResolutionType
    )
    foreach ($Path in $EvidencePath) {
        $Arguments += @("--incident-resolution-evidence", $Path)
    }
    if ($Acknowledge) {
        $Arguments += "--acknowledge-incident-resolution"
    }
}

& $Python @Arguments

if ($LASTEXITCODE -ne 0) {
    throw "Incident resolution command failed with exit code $LASTEXITCODE."
}
