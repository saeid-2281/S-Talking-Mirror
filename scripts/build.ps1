param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }
$packageRoot = Join-Path $repo "artifacts\package"
$resultPath = Join-Path $packageRoot "build-result.json"
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$started = Get-Date
$result = [ordered]@{
    schema_version = 1
    started_at = $started.ToString("o")
    finished_at = $null
    success = $false
    stage = "starting"
    version = $null
    exe_path = $null
    zip_path = $null
    smoke_test = [ordered]@{}
    errors = @()
}

function Finish-Build {
    param([bool]$Success, [string]$Stage)
    $finished = Get-Date
    $result.finished_at = $finished.ToString("o")
    $result.elapsed_seconds = [math]::Round(($finished - $started).TotalSeconds, 3)
    $result.success = $Success
    $result.stage = $Stage
    $result | ConvertTo-Json -Depth 8 | Set-Content -Path $resultPath -Encoding UTF8
}

try {
    $result.stage = "pyinstaller_check"
    $previousErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $pythonPath -c "import PyInstaller" *> $null
    $pyInstallerProbe = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorPreference
    if ($pyInstallerProbe -ne 0) {
        $ErrorActionPreference = "Continue"
        & $pythonPath -m pip install pyinstaller
        $pipCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorPreference
        if ($pipCode -ne 0) { throw "Failed to install PyInstaller into .venv." }
    }

    $version = (& $pythonPath -c "import app; print(app.__version__)").Trim()
    $result.version = $version
    $buildDir = Join-Path $repo "build"
    $distDir = Join-Path $repo "dist"
    foreach ($path in @($buildDir, $distDir)) {
        $resolvedParent = (Resolve-Path $repo).Path
        if (Test-Path $path) {
            $resolved = (Resolve-Path $path).Path
            if (!$resolved.StartsWith($resolvedParent)) { throw "Refusing to remove path outside repository: $resolved" }
            Remove-Item -Recurse -Force -LiteralPath $resolved
        }
    }

    $result.stage = "pyinstaller_build"
    & $pythonPath -m PyInstaller --noconfirm --clean "packaging\S-Talking.spec"
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    $exe = Join-Path $repo "dist\S-Talking\S-Talking.exe"
    if (!(Test-Path $exe)) { throw "Expected executable not found: $exe" }
    $result.exe_path = $exe

    $result.stage = "frozen_smoke"
    $env:S_TALKING_SMOKE_EXIT_MS = "5500"
    $process = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 5
    $aliveAfterFive = !$process.HasExited
    if (!$aliveAfterFive) {
        $result.smoke_test = [ordered]@{ success = $false; alive_after_five_seconds = $false; exit_code = $process.ExitCode }
        throw "Frozen executable exited before 5 seconds."
    }
    Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
    if (!$process.HasExited) {
        $process.CloseMainWindow() | Out-Null
        Start-Sleep -Milliseconds 800
    }
    if (!$process.HasExited) { $process.Kill() }
    $result.smoke_test = [ordered]@{ success = $true; alive_after_five_seconds = $true; exit_code = $process.ExitCode }
    Remove-Item Env:S_TALKING_SMOKE_EXIT_MS -ErrorAction SilentlyContinue

    $result.stage = "package"
    $portable = Join-Path $packageRoot "S-Talking-$version-portable"
    $zip = "$portable.zip"
    Remove-Item -Recurse -Force $portable -ErrorAction SilentlyContinue
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $portable | Out-Null
    Copy-Item -Recurse -Force (Join-Path $repo "dist\S-Talking\*") $portable
    New-Item -ItemType File -Force -Path (Join-Path $portable "portable.mode") | Out-Null
    @"
S Talking $version portable release candidate

Run S-Talking.exe directly, or double-click RUN.cmd.
Writable data is stored beside this executable in S-Talking-Data because portable.mode is present.
"@ | Set-Content -Path (Join-Path $portable "README.txt") -Encoding UTF8
    @"
@echo off
setlocal
set APPDIR=%~dp0
set EXE=%APPDIR%S-Talking.exe
set LOG=%APPDIR%launcher-error.log
if not exist "%EXE%" (
  echo S-Talking.exe was not found at "%EXE%" > "%LOG%"
  mshta "javascript:alert('S-Talking.exe was not found. See launcher-error.log beside RUN.cmd.');close()"
  exit /b 1
)
start "" "%EXE%"
if errorlevel 1 (
  echo Failed to start "%EXE%". Errorlevel %errorlevel%. > "%LOG%"
  mshta "javascript:alert('S Talking could not start. See launcher-error.log beside RUN.cmd.');close()"
  exit /b %errorlevel%
)
exit /b 0
"@ | Set-Content -Path (Join-Path $portable "RUN.cmd") -Encoding ASCII
    Compress-Archive -Path (Join-Path $portable "*") -DestinationPath $zip -Force
    $result.zip_path = $zip
    Finish-Build $true "complete"
    Write-Output $zip
} catch {
    $result.errors += [string]$_
    Finish-Build $false $result.stage
    Write-Error $_
    exit 1
}
