param(
    [switch]$Snapshot,
    [switch]$GenerateSbom,
    [switch]$ScanVulnerabilities,
    [switch]$Export,
    [string]$AuditPackage,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo
$venvPython = Join-Path $repo ".venv\Scripts\python.exe"
if (Test-Path $venvPython) { $Python = $venvPython }

$arguments = @("-m", "app.frozen_main")
if ($GenerateSbom) { $arguments += "--generate-sbom" }
if ($ScanVulnerabilities) { $arguments += "--security-vulnerability-scan" }
if ($AuditPackage) {
    $resolvedPackage = (Resolve-Path -LiteralPath $AuditPackage).Path
    $arguments += @("--security-audit-package", $resolvedPackage)
}
if ($Export) { $arguments += "--security-export" }
if ($Snapshot -or $arguments.Count -eq 2) { $arguments += "--security-snapshot" }

& $Python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Security and supply-chain audit failed."
}
