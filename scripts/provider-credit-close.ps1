param(
    [string]$AccountingPeriod = (Get-Date -Format "yyyy-MM"),
    [switch]$CreateClose,
    [string]$Owner = "",
    [string]$Statement = "",
    [switch]$LedgerExportVerified,
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
    "--provider-credit-close-snapshot",
    "--provider-credit-period",
    $AccountingPeriod
)

if ($CreateClose) {
    $Arguments += "--create-provider-credit-close"
    $Arguments += @("--provider-credit-owner", $Owner)
    $Arguments += @("--provider-credit-statement", $Statement)
}
if ($LedgerExportVerified) {
    $Arguments += "--provider-credit-ledger-verified"
}
if ($Acknowledge) {
    $Arguments += "--acknowledge-provider-credit-close"
}

& $Python @Arguments
exit $LASTEXITCODE
