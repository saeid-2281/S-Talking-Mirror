$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Temp = Join-Path $Root ".pytest-tmp"
$ArtifactRoot = Join-Path $Root "artifacts\dev-check"
$RunId = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$RunDir = Join-Path $ArtifactRoot $RunId
$Latest = Join-Path $ArtifactRoot "latest"
$Summary = Join-Path $RunDir "summary.txt"
$Started = Get-Date
$Steps = [ordered]@{
    compileall = [ordered]@{ success = $false; exit_code = $null }
    pytest = [ordered]@{ success = $false; exit_code = $null; passed = 0; failed = 0; errors = 0 }
    ruff = [ordered]@{ success = $false; exit_code = $null }
}

function Publish-Latest() {
    if (Test-Path $Latest) {
        Remove-Item $Latest -Recurse -Force
    }
    Copy-Item $RunDir $Latest -Recurse
}

function Get-PytestCounts($Text) {
    $passed = 0
    $failed = 0
    $errors = 0
    $passedMatch = [regex]::Match($Text, "(\d+)\s+passed")
    $failedMatch = [regex]::Match($Text, "(\d+)\s+failed")
    $errorMatch = [regex]::Match($Text, "(\d+)\s+errors?")
    if ($passedMatch.Success) { $passed = [int]$passedMatch.Groups[1].Value }
    if ($failedMatch.Success) { $failed = [int]$failedMatch.Groups[1].Value }
    if ($errorMatch.Success) { $errors = [int]$errorMatch.Groups[1].Value }
    return @{ passed = $passed; failed = $failed; errors = $errors }
}

function Write-Result($Success, $ExitCode, $Stage, $SummaryText) {
    $finished = Get-Date
    $result = [ordered]@{
        schema_version = 1
        started_at = $Started.ToString("o")
        finished_at = $finished.ToString("o")
        elapsed_seconds = [Math]::Round(($finished - $Started).TotalSeconds, 3)
        success = [bool]$Success
        exit_code = [int]$ExitCode
        stage = $Stage
        summary = $SummaryText
        artifact_directory = "$RunDir"
        steps = $Steps
    }
    $result | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $RunDir "result.json")
}

function Step($Name, $ArgsList) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    $OutputPath = Join-Path $RunDir "$Name.txt"
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $Python @ArgsList *> $OutputPath
    $exit = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorPreference
    $Steps[$Name].exit_code = $exit
    $Steps[$Name].success = ($exit -eq 0)
    if ($Name -eq "pytest") {
        $counts = Get-PytestCounts (Get-Content $OutputPath -Raw)
        $Steps.pytest.passed = $counts.passed
        $Steps.pytest.failed = $counts.failed
        $Steps.pytest.errors = $counts.errors
    }
    Get-Content $OutputPath
    if ($exit -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        Add-Content $Summary "FAILED: $Name"
        Add-Content $Summary "Artifacts: $RunDir"
        Write-Result $false $exit $Name "Checks failed at $Name"
        Publish-Latest
        Invoke-Item $RunDir
        exit $exit
    }
    Add-Content $Summary "PASSED: $Name"
}

if (-not (Test-Path $Python)) {
    Write-Host "Missing virtual environment: .venv" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force $Temp | Out-Null
New-Item -ItemType Directory -Force $RunDir | Out-Null
"S Talking development check" | Set-Content $Summary
"Started: $(Get-Date -Format o)" | Add-Content $Summary
"Python: $Python" | Add-Content $Summary
Step "compileall" @("-m", "compileall", "app")
Step "pytest" @("-m", "pytest", "--basetemp", $Temp)
Step "ruff" @("-m", "ruff", "check", "app", "tests")
"Finished: $(Get-Date -Format o)" | Add-Content $Summary
@{
    python = $Python
    root = "$Root"
    os = [System.Environment]::OSVersion.VersionString
    machine = [System.Environment]::MachineName
    user = [System.Environment]::UserName
} | ConvertTo-Json | Set-Content (Join-Path $RunDir "environment.json")
Write-Result $true 0 "complete" "All checks passed"
Publish-Latest
Write-Host "All checks passed." -ForegroundColor Green
Write-Host "Artifacts: $RunDir" -ForegroundColor Green
