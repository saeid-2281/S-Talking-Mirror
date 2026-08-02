$ErrorActionPreference = "Stop"

$Root = git rev-parse --show-toplevel
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Set-Location -LiteralPath $Root

& (Join-Path $Root "scripts\quality-gate.ps1")
exit $LASTEXITCODE