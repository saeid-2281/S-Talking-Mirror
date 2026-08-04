[CmdletBinding()]
param(
    [switch]$Snapshot,
    [switch]$Export,
    [switch]$Quick,
    [ValidateRange(0.01, 1440.0)]
    [double]$DurationMinutes = 30.0,
    [ValidateRange(0.05, 3600.0)]
    [double]$SampleIntervalSeconds = 15.0,
    [ValidateRange(1, 100000)]
    [int]$MaxSamples = 100000,
    [string]$Label = "command-line soak"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Project virtual environment was not found: $Python"
}

Push-Location $Root
try {
    $arguments = @("-m", "app.frozen_main")
    if ($Quick) {
        $DurationMinutes = 0.05
        $SampleIntervalSeconds = 0.5
        $MaxSamples = 6
    }
    if ($Snapshot -and -not $Quick) {
        $arguments += "--performance-snapshot"
    }
    if ($Export) {
        $arguments += "--performance-export"
    }
    if (-not $Snapshot -or $Quick) {
        $arguments += @(
            "--performance-soak-minutes", $DurationMinutes.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--performance-sample-interval", $SampleIntervalSeconds.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--performance-max-samples", $MaxSamples.ToString([Globalization.CultureInfo]::InvariantCulture),
            "--performance-label", $Label
        )
    }
    Write-Host "==> performance and long-run stability" -ForegroundColor Cyan
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Performance stability command failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}
