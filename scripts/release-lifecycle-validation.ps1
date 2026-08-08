param(
    [switch]$Export,
    [string]$Manifest = "",
    [string]$Feed = "",
    [string]$Backup = "",
    [string]$SourceVersion = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python was not found: $python"
}

$argsList = @("-m", "app.frozen_main", "--release-lifecycle-validation")
if ($Export) { $argsList += "--export-release-lifecycle-validation" }
if ($Manifest) { $argsList += @("--release-lifecycle-manifest", $Manifest) }
if ($Feed) { $argsList += @("--release-lifecycle-feed", $Feed) }
if ($Backup) { $argsList += @("--release-lifecycle-backup", $Backup) }
if ($SourceVersion) { $argsList += @("--release-lifecycle-source-version", $SourceVersion) }

& $python @argsList
exit $LASTEXITCODE
