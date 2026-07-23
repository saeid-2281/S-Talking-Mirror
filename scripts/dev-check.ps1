$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Temp = Join-Path $Root ".pytest-tmp"
$ArtifactRoot = Join-Path $Root "artifacts\dev-check"
$RunId = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$RunDir = Join-Path $ArtifactRoot $RunId
$Latest = Join-Path $ArtifactRoot "latest"
$Summary = Join-Path $RunDir "summary.txt"

function Publish-Latest() {
    if (Test-Path $Latest) {
        Remove-Item $Latest -Recurse -Force
    }
    Copy-Item $RunDir $Latest -Recurse
}

function Step($Name, $ArgsList) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    $OutputPath = Join-Path $RunDir "$Name.txt"
    & $Python @ArgsList *> $OutputPath
    Get-Content $OutputPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        Add-Content $Summary "FAILED: $Name"
        Add-Content $Summary "Artifacts: $RunDir"
        Publish-Latest
        Invoke-Item $RunDir
        exit $LASTEXITCODE
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
Publish-Latest
Write-Host "All checks passed." -ForegroundColor Green
Write-Host "Artifacts: $RunDir" -ForegroundColor Green
