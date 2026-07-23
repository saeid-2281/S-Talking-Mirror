$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Temp = Join-Path $Root ".pytest-tmp"
$ArtifactRoot = Join-Path $Root "artifacts\dev-check"
$Latest = Join-Path $ArtifactRoot "latest"
$Summary = Join-Path $Latest "summary.txt"

function Step($Name, $ArgsList) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    $OutputPath = Join-Path $Latest "$Name.txt"
    & $Python @ArgsList *> $OutputPath
    Get-Content $OutputPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Name" -ForegroundColor Red
        Add-Content $Summary "FAILED: $Name"
        Add-Content $Summary "Artifacts: $Latest"
        Invoke-Item $Latest
        exit $LASTEXITCODE
    }
    Add-Content $Summary "PASSED: $Name"
}

if (-not (Test-Path $Python)) {
    Write-Host "Missing virtual environment: .venv" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force $Temp | Out-Null
if (Test-Path $Latest) {
    Remove-Item $Latest -Recurse -Force
}
New-Item -ItemType Directory -Force $Latest | Out-Null
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
} | ConvertTo-Json | Set-Content (Join-Path $Latest "environment.json")
Write-Host "All checks passed." -ForegroundColor Green
Write-Host "Artifacts: $Latest" -ForegroundColor Green
