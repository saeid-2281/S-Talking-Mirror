param(
    [switch]$CreateCertification,
    [switch]$Acknowledge,
    [string]$Reviewer = "",
    [string]$Statement = "",
    [int]$ProjectId = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Project Python was not found: $python"
}

$argsList = @("-m", "app.frozen_main", "--operational-readiness-certification")
if ($ProjectId -gt 0) {
    $argsList += @("--operational-readiness-project-id", "$ProjectId")
}
if ($CreateCertification) {
    $argsList += "--create-operational-readiness-certification"
    if ($Acknowledge) {
        $argsList += "--acknowledge-operational-readiness"
    }
    if ($Reviewer) {
        $argsList += @("--operational-readiness-reviewer", $Reviewer)
    }
    if ($Statement) {
        $argsList += @("--operational-readiness-statement", $Statement)
    }
}

& $python @argsList
exit $LASTEXITCODE
