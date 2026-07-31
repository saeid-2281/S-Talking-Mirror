$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

git config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Git hooks enabled from .githooks"
Write-Host "Pre-commit now runs scripts\quality-gate.ps1"
