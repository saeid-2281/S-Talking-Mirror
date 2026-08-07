param(
    [string]$AccountingPeriod = (Get-Date -Format "yyyy-MM"),
    [double]$ToleranceAmount = 0.01,
    [switch]$CreateAudit,
    [string]$Owner = "",
    [string]$Statement = "",
    [switch]$Acknowledge
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Project Python was not found: $Python"
}

Set-Location $ProjectRoot

$Arguments = @(
    "-m",
    "app.frozen_main",
    "--financial-audit-snapshot",
    "--financial-audit-period",
    $AccountingPeriod,
    "--financial-audit-tolerance",
    $ToleranceAmount
)

if ($CreateAudit) {
    $Arguments += "--create-financial-audit"
    $Arguments += @("--financial-audit-owner", $Owner)
    $Arguments += @("--financial-audit-statement", $Statement)
}
if ($Acknowledge) {
    $Arguments += "--acknowledge-financial-audit"
}

& $Python @Arguments
exit $LASTEXITCODE
