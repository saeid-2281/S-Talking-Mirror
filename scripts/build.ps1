param(
    [string]$Python = ".\.venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }
$packageRoot = Join-Path $repo "artifacts\package"
$resultPath = Join-Path $packageRoot "build-result.json"
$installerResultPath = Join-Path $packageRoot "installer-result.json"
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$started = Get-Date
$result = [ordered]@{
    schema_version = 2
    started_at = $started.ToString("o")
    finished_at = $null
    elapsed_seconds = 0
    success = $false
    stage = "starting"
    version = $null
    exe_path = $null
    zip_path = $null
    installer_result_path = $installerResultPath
    installer_available = $false
    smoke_test = [ordered]@{}
    warnings = @()
    errors = @()
}

function Write-JsonUtf8NoBom {
    param([object]$Value, [string]$Path)
    $json = $Value | ConvertTo-Json -Depth 10
    $encoding = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json, $encoding)
}

function Get-Sha256 {
    param([string]$Path)
    if (!(Test-Path $Path)) { return $null }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Test-PortableExecutable {
    param([string]$Path)
    if (!(Test-Path $Path)) { return $false }
    $info = Get-Item -LiteralPath $Path
    if ($info.Length -lt 4096) { return $false }
    $stream = [System.IO.File]::OpenRead($Path)
    try {
        return ($stream.ReadByte() -eq 0x4D -and $stream.ReadByte() -eq 0x5A)
    } finally {
        $stream.Dispose()
    }
}

function Finish-Build {
    param([bool]$Success, [string]$Stage)
    $finished = Get-Date
    $result.finished_at = $finished.ToString("o")
    $result.elapsed_seconds = [math]::Round(($finished - $started).TotalSeconds, 3)
    $result.success = $Success
    $result.stage = $Stage
    Write-JsonUtf8NoBom $result $resultPath
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
        if (Test-Path $path) {
            $resolved = (Resolve-Path $path).Path
            if (!$resolved.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove path outside repository: $resolved"
            }
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
    try {
        $env:S_TALKING_SMOKE_EXIT_MS = "5500"
        $process = Start-Process -FilePath $exe -PassThru -WindowStyle Hidden
        Start-Sleep -Seconds 5
        $aliveAfterFive = !$process.HasExited
        if (!$aliveAfterFive) {
            $result.smoke_test = [ordered]@{
                success = $false
                alive_after_five_seconds = $false
                exit_code = $process.ExitCode
            }
            throw "Frozen executable exited before 5 seconds."
        }
        Wait-Process -Id $process.Id -Timeout 10 -ErrorAction SilentlyContinue
        if (!$process.HasExited) {
            $process.CloseMainWindow() | Out-Null
            Start-Sleep -Milliseconds 800
        }
        if (!$process.HasExited) { $process.Kill() }
        $result.smoke_test = [ordered]@{
            success = $true
            alive_after_five_seconds = $true
            exit_code = $process.ExitCode
        }
    } finally {
        Remove-Item Env:S_TALKING_SMOKE_EXIT_MS -ErrorAction SilentlyContinue
    }

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

    $result.stage = "installer"
    $installerDir = Join-Path $packageRoot "installer"
    New-Item -ItemType Directory -Force -Path $installerDir | Out-Null
    $iss = Join-Path $repo "packaging\windows\S-Talking.iss"
    $installerExe = Join-Path $installerDir "S-Talking-$version-setup.exe"
    $placeholder = Join-Path $installerDir "S-Talking-$version-installer-unavailable.txt"
    Remove-Item -Force $installerExe, $placeholder -ErrorAction SilentlyContinue
    $installerResult = [ordered]@{
        schema_version = 2
        started_at = (Get-Date).ToString("o")
        finished_at = $null
        success = $false
        available = $false
        distributable = $false
        stage = "starting"
        version = $version
        installer_path = $null
        artifact_path = $null
        artifact_kind = "none"
        sha256 = $null
        size_bytes = 0
        tool = "Inno Setup"
        unsigned = $true
        errors = @()
    }
    $iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($iscc -and (Test-Path $iss)) {
        $installerResult.stage = "inno_setup"
        & $iscc.Source "/DAppVersion=$version" "/DSourceDir=$(Join-Path $repo 'dist\S-Talking')" "/DOutputDir=$installerDir" "/DOutputBaseFilename=S-Talking-$version-setup" $iss
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
        if (!(Test-PortableExecutable $installerExe)) {
            throw "Compiled installer is missing or is not a valid Windows PE executable: $installerExe"
        }
        $installerResult.success = $true
        $installerResult.available = $true
        $installerResult.distributable = $true
        $installerResult.installer_path = $installerExe
        $installerResult.artifact_path = $installerExe
        $installerResult.artifact_kind = "installer"
        $installerResult.sha256 = Get-Sha256 $installerExe
        $installerResult.size_bytes = (Get-Item -LiteralPath $installerExe).Length
        $result.installer_available = $true
    } else {
        $installerResult.stage = "unavailable"
        @"
S Talking $version installer was not compiled.

Inno Setup (ISCC.exe) was not found on this machine. No placeholder .exe was created.
Install Inno Setup and rerun scripts/build.ps1 to produce a distributable installer.

Verified portable package:
$zip
"@ | Set-Content -Path $placeholder -Encoding UTF8
        $installerResult.artifact_path = $placeholder
        $installerResult.artifact_kind = "placeholder"
        $installerResult.sha256 = Get-Sha256 $placeholder
        $installerResult.size_bytes = (Get-Item -LiteralPath $placeholder).Length
        $installerResult.errors += "Inno Setup not installed; portable package built successfully, installer unavailable."
        $result.warnings += "Compiled installer unavailable; portable package remains valid."
    }
    $installerResult.finished_at = (Get-Date).ToString("o")
    Write-JsonUtf8NoBom $installerResult $installerResultPath

    Finish-Build $true "complete"
    Write-Output $zip
} catch {
    $result.errors += [string]$_
    Finish-Build $false $result.stage
    Write-Error $_
    exit 1
}
