param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [switch]$RequireSigning
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }
$packageRoot = Join-Path $repo "artifacts\package"
$resultPath = Join-Path $packageRoot "build-result.json"
$installerResultPath = Join-Path $packageRoot "installer-result.json"
$signingResultPath = Join-Path $packageRoot "signing-result.json"
New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
$started = Get-Date
$result = [ordered]@{
    schema_version = 3
    started_at = $started.ToString("o")
    finished_at = $null
    elapsed_seconds = 0
    success = $false
    stage = "starting"
    version = $null
    exe_path = $null
    zip_path = $null
    installer_result_path = $installerResultPath
    signing_result_path = $signingResultPath
    signing_required = [bool]$RequireSigning
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

function Resolve-SignTool {
    if ($env:S_TALKING_SIGNTOOL_PATH -and (Test-Path $env:S_TALKING_SIGNTOOL_PATH)) {
        return (Resolve-Path $env:S_TALKING_SIGNTOOL_PATH).Path
    }
    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path $kits) {
        $candidate = Get-ChildItem -Path $kits -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }
    return $null
}

function Get-SignatureEvidence {
    param([string]$Role, [string]$Path, [string]$FallbackStatus = "unavailable", [string]$Detail = "")
    $record = [ordered]@{
        role = $Role
        path = $Path
        status = $FallbackStatus
        sha256 = Get-Sha256 $Path
        subject = ""
        thumbprint = ""
        timestamped = $false
        detail = $Detail
    }
    if (!(Test-Path $Path)) { return $record }
    try {
        $signature = Get-AuthenticodeSignature -FilePath $Path
        if ($signature.Status -eq [System.Management.Automation.SignatureStatus]::Valid) {
            $record.status = "verified"
            $record.subject = [string]$signature.SignerCertificate.Subject
            $record.thumbprint = [string]$signature.SignerCertificate.Thumbprint
            $record.timestamped = ($null -ne $signature.TimeStamperCertificate)
            $record.detail = "Authenticode signature verified."
        } elseif ($signature.Status -eq [System.Management.Automation.SignatureStatus]::NotSigned) {
            $record.status = "unsigned"
            $record.detail = "Artifact is not Authenticode signed."
        } else {
            $record.status = "failed"
            $record.detail = "Authenticode status: $($signature.Status) - $($signature.StatusMessage)"
        }
    } catch {
        $record.status = "failed"
        $record.detail = "Signature inspection failed: $($_.Exception.Message)"
    }
    return $record
}

function Invoke-CodeSigning {
    param([string]$Role, [string]$Path)
    $signTool = Resolve-SignTool
    $thumbprint = ([string]$env:S_TALKING_SIGN_CERT_THUMBPRINT).Replace(" ", "")
    if ($RequireSigning -and !$env:S_TALKING_TIMESTAMP_URL) {
        throw "Code signing requires S_TALKING_TIMESTAMP_URL for durable timestamp evidence."
    }
    if (!$signTool -or !$thumbprint) {
        $missing = if (!$signTool) { "SignTool was not found." } else { "S_TALKING_SIGN_CERT_THUMBPRINT is not configured." }
        if ($RequireSigning) { throw "Code signing is required: $missing" }
        return Get-SignatureEvidence $Role $Path "unsigned" $missing
    }
    $arguments = @("sign", "/sha1", $thumbprint, "/fd", "sha256")
    if ($env:S_TALKING_TIMESTAMP_URL) {
        $arguments += @("/tr", $env:S_TALKING_TIMESTAMP_URL, "/td", "sha256")
    }
    $arguments += $Path
    & $signTool @arguments
    if ($LASTEXITCODE -ne 0) { throw "SignTool failed for $Role." }
    & $signTool verify /pa /v $Path
    if ($LASTEXITCODE -ne 0) { throw "SignTool verification failed for $Role." }
    $evidence = Get-SignatureEvidence $Role $Path
    if ($evidence.status -ne "verified") { throw "PowerShell could not verify the signed $Role artifact." }
    if ($RequireSigning -and $env:S_TALKING_TIMESTAMP_URL -and !$evidence.timestamped) {
        throw "A timestamped signature is required for $Role."
    }
    return $evidence
}

$signingResult = [ordered]@{
    schema_version = 1
    started_at = $started.ToString("o")
    finished_at = $null
    required = [bool]$RequireSigning
    tool = "Microsoft SignTool"
    certificate_thumbprint = ([string]$env:S_TALKING_SIGN_CERT_THUMBPRINT).Replace(" ", "")
    timestamp_url_configured = [bool]$env:S_TALKING_TIMESTAMP_URL
    artifacts = @()
    errors = @()
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

    $result.stage = "application_signing"
    $applicationEvidence = Invoke-CodeSigning "application_executable" $exe
    $signingResult.artifacts += $applicationEvidence
    if ($applicationEvidence.status -ne "verified") {
        $result.warnings += "Application executable is not signed and timestamped."
    }

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

    $result.stage = "security_supply_chain"
    & $pythonPath -m app.frozen_main --generate-sbom --security-audit-package $zip --security-export
    if ($LASTEXITCODE -ne 0) { throw "Security and supply-chain verification failed." }

    $result.stage = "installer"
    $installerDir = Join-Path $packageRoot "installer"
    New-Item -ItemType Directory -Force -Path $installerDir | Out-Null
    $iss = Join-Path $repo "packaging\windows\S-Talking.iss"
    $installerExe = Join-Path $installerDir "S-Talking-$version-setup.exe"
    $placeholder = Join-Path $installerDir "S-Talking-$version-installer-unavailable.txt"
    Remove-Item -Force $installerExe, $placeholder -ErrorAction SilentlyContinue
    $installerResult = [ordered]@{
        schema_version = 3
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
        signature_status = "unavailable"
        signature_subject = ""
        signature_thumbprint = ""
        timestamped = $false
        signing_result_path = $signingResultPath
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
        $installerResult.stage = "signing"
        $installerEvidence = Invoke-CodeSigning "windows_installer" $installerExe
        $signingResult.artifacts += $installerEvidence
        $installerResult.success = $true
        $installerResult.available = $true
        $installerResult.distributable = $true
        $installerResult.installer_path = $installerExe
        $installerResult.artifact_path = $installerExe
        $installerResult.artifact_kind = "installer"
        $installerResult.sha256 = Get-Sha256 $installerExe
        $installerResult.size_bytes = (Get-Item -LiteralPath $installerExe).Length
        $installerResult.unsigned = ($installerEvidence.status -ne "verified")
        $installerResult.signature_status = $installerEvidence.status
        $installerResult.signature_subject = $installerEvidence.subject
        $installerResult.signature_thumbprint = $installerEvidence.thumbprint
        $installerResult.timestamped = $installerEvidence.timestamped
        if ($installerEvidence.status -ne "verified") {
            $result.warnings += "Compiled installer is not signed and timestamped."
        }
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
        $signingResult.artifacts += [ordered]@{
            role = "windows_installer"
            path = ""
            status = "unavailable"
            sha256 = ""
            subject = ""
            thumbprint = ""
            timestamped = $false
            detail = "Installer was not compiled because Inno Setup is unavailable."
        }
        if ($RequireSigning) { throw "Signed installer is required but Inno Setup is unavailable." }
    }
    $installerResult.finished_at = (Get-Date).ToString("o")
    Write-JsonUtf8NoBom $installerResult $installerResultPath
    $signingResult.finished_at = (Get-Date).ToString("o")
    Write-JsonUtf8NoBom $signingResult $signingResultPath

    Finish-Build $true "complete"
    Write-Output $zip
} catch {
    $message = [string]$_
    $result.errors += $message
    $signingResult.errors += $message
    $signingResult.finished_at = (Get-Date).ToString("o")
    Write-JsonUtf8NoBom $signingResult $signingResultPath
    Finish-Build $false $result.stage
    Write-Error $_
    exit 1
}
