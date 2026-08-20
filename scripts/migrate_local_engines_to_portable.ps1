param(
    [string]$SourcePortableRoot = "",
    [string]$DestinationPortableRoot = ""
)

& {
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$OutputRoot = "C:\zip-for-GPT"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogRoot = Join-Path $OutputRoot "S-Talking-runner-logs"
$Log = Join-Path $LogRoot "S-Talking-Local-State-Migration-$Stamp.txt"
$LastLog = Join-Path $OutputRoot "S-Talking-Local-State-Migration-last-run.txt"
$TranscriptStarted = $false

function Resolve-Destination([string]$Value) {
    if (-not [string]::IsNullOrWhiteSpace($Value)) { return [System.IO.Path]::GetFullPath($Value.Trim('"')) }
    if ((Test-Path -LiteralPath (Join-Path $PSScriptRoot "S-Talking.exe")) -and
        (Test-Path -LiteralPath (Join-Path $PSScriptRoot "portable.mode"))) {
        return [System.IO.Path]::GetFullPath($PSScriptRoot)
    }
    $Entered = Read-Host "Paste the NEW Portable folder containing S-Talking.exe and portable.mode"
    if ([string]::IsNullOrWhiteSpace($Entered)) { throw "Destination Portable folder was not provided." }
    return [System.IO.Path]::GetFullPath($Entered.Trim('"'))
}

function Resolve-Source([string]$Value) {
    if (-not [string]::IsNullOrWhiteSpace($Value)) { return [System.IO.Path]::GetFullPath($Value.Trim('"')) }
    $Entered = Read-Host "Paste the OLD Portable folder that already contains the working local engines"
    if ([string]::IsNullOrWhiteSpace($Entered)) { throw "Source Portable folder was not provided." }
    return [System.IO.Path]::GetFullPath($Entered.Trim('"'))
}

function Copy-Tree([string]$Source, [string]$Destination, [string]$Label) {
    if (-not (Test-Path -LiteralPath $Source -PathType Container)) {
        Write-Host "${Label}: source not present; skipped." -ForegroundColor Yellow
        return
    }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    & robocopy.exe $Source $Destination /E /COPY:DAT /DCOPY:T /R:2 /W:1 /NFL /NDL /NP
    $Code = $LASTEXITCODE
    if ($Code -gt 7) { throw "$Label copy failed with robocopy exit code $Code." }
    Write-Host "${Label}: COPIED" -ForegroundColor Green
}

try {
    New-Item -ItemType Directory -Path $OutputRoot,$LogRoot -Force | Out-Null
    Start-Transcript -LiteralPath $Log -Force | Out-Null
    $TranscriptStarted = $true

    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "S-Talking Local Engine / Portable State Migration" -ForegroundColor Cyan
    Write-Host "=============================================" -ForegroundColor Cyan

    $DestinationPortableRoot = Resolve-Destination $DestinationPortableRoot
    $SourcePortableRoot = Resolve-Source $SourcePortableRoot
    if ($SourcePortableRoot -eq $DestinationPortableRoot) { throw "Source and destination Portable folders must be different." }

    foreach ($Root in @($SourcePortableRoot,$DestinationPortableRoot)) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root "S-Talking.exe") -PathType Leaf)) { throw "S-Talking.exe not found under: $Root" }
        if (-not (Test-Path -LiteralPath (Join-Path $Root "portable.mode") -PathType Leaf)) { throw "portable.mode not found under: $Root" }
    }
    $Running = @(Get-Process -Name "S-Talking" -ErrorAction SilentlyContinue)
    if ($Running.Count -gt 0) { throw "Close every running S-Talking window before migrating local state." }

    $SourceData = Join-Path $SourcePortableRoot "S-Talking-Data"
    $DestinationData = Join-Path $DestinationPortableRoot "S-Talking-Data"
    New-Item -ItemType Directory -Path $DestinationData -Force | Out-Null

    Copy-Tree (Join-Path $SourceData "local-engines") (Join-Path $DestinationData "local-engines") "Local engines"
    Copy-Tree (Join-Path $SourceData "offline-voices") (Join-Path $DestinationData "offline-voices") "Managed offline voices"

    # Preserve the user's selected Piper model/settings, but rebase absolute paths
    # from the old Portable root to the new Portable root.
    $SourceSettings = Join-Path $SourceData "settings\settings.json"
    $DestinationSettingsDir = Join-Path $DestinationData "settings"
    $DestinationSettings = Join-Path $DestinationSettingsDir "settings.json"
    New-Item -ItemType Directory -Path $DestinationSettingsDir -Force | Out-Null
    if (Test-Path -LiteralPath $SourceSettings -PathType Leaf) {
        if (Test-Path -LiteralPath $DestinationSettings -PathType Leaf) {
            Copy-Item -LiteralPath $DestinationSettings -Destination "$DestinationSettings.before-local-state-$Stamp.bak" -Force
        }
        $SettingsText = Get-Content -LiteralPath $SourceSettings -Raw -Encoding UTF8
        $SettingsText = $SettingsText.Replace($SourcePortableRoot, $DestinationPortableRoot)
        [System.IO.File]::WriteAllText(
            $DestinationSettings,
            $SettingsText,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "Portable settings (rebased): COPIED" -ForegroundColor Green
    }

    $SourceWorkspaceProfiles = Join-Path $SourceData "settings\workspace-profiles.json"
    $DestinationWorkspaceProfiles = Join-Path $DestinationSettingsDir "workspace-profiles.json"
    if (Test-Path -LiteralPath $SourceWorkspaceProfiles -PathType Leaf) {
        $WorkspaceText = Get-Content -LiteralPath $SourceWorkspaceProfiles -Raw -Encoding UTF8
        $WorkspaceText = $WorkspaceText.Replace($SourcePortableRoot, $DestinationPortableRoot)
        [System.IO.File]::WriteAllText(
            $DestinationWorkspaceProfiles,
            $WorkspaceText,
            [System.Text.UTF8Encoding]::new($false)
        )
        Write-Host "Workspace profile metadata (rebased): COPIED" -ForegroundColor Green
    }

    $SourceLauncher = Join-Path $SourcePortableRoot "RUN-S-Talking-With-Local-Engines.cmd"
    $DestinationLauncher = Join-Path $DestinationPortableRoot "RUN-S-Talking-With-Local-Engines.cmd"
    if (Test-Path -LiteralPath $SourceLauncher -PathType Leaf) {
        $LauncherText = Get-Content -LiteralPath $SourceLauncher -Raw
        $LauncherText = $LauncherText.Replace($SourcePortableRoot, $DestinationPortableRoot)
        $LauncherText | Set-Content -LiteralPath $DestinationLauncher -Encoding ASCII
        Write-Host "Local Engines launcher (rebased): CREATED" -ForegroundColor Green
    } else {
        $EngineRoot = Join-Path $DestinationData "local-engines"
        $PiperScripts = Join-Path $EngineRoot "piper\.venv\Scripts"
        $PiperVoices = Join-Path $EngineRoot "piper\voices"
        $PiperModel = Join-Path $PiperVoices "da_DK-talesyntese-medium.onnx"
        @(
            '@echo off',
            'setlocal',
            ('set "ENGINE_ROOT={0}"' -f $EngineRoot),
            ('set "PATH={0};%PATH%"' -f $PiperScripts),
            ('set "PIPER_DATA_DIR={0}"' -f $PiperVoices),
            ('set "PIPER_MODEL_PATH={0}"' -f $PiperModel),
            ('set "S_TALKING_PIPER_DATA_DIR={0}"' -f $PiperVoices),
            ('set "S_TALKING_PIPER_MODEL_PATH={0}"' -f $PiperModel),
            'if not exist "%~dp0S-Talking.exe" exit /b 2',
            'start "" "%~dp0S-Talking.exe"',
            'exit /b 0'
        ) | Set-Content -LiteralPath $DestinationLauncher -Encoding ASCII
        Write-Host "Local Engines launcher (Piper fallback): CREATED" -ForegroundColor Yellow
    }

    $PiperExe = Join-Path $DestinationData "local-engines\piper\.venv\Scripts\piper.exe"
    $PiperPython = Join-Path $DestinationData "local-engines\piper\.venv\Scripts\python.exe"
    $PiperModule = Join-Path $DestinationData "local-engines\piper\.venv\Lib\site-packages\piper\__main__.py"
    $PiperModel = Join-Path $DestinationData "local-engines\piper\voices\da_DK-talesyntese-medium.onnx"
    $ManagedModel = Join-Path $DestinationData "offline-voices\piper\da_DK-talesyntese-medium\da_DK-talesyntese-medium.onnx"
    $WrapperPresent = Test-Path -LiteralPath $PiperExe -PathType Leaf
    $PythonModuleFallbackPresent = (
        (Test-Path -LiteralPath $PiperPython -PathType Leaf) -and
        (Test-Path -LiteralPath $PiperModule -PathType Leaf)
    )
    if (-not $WrapperPresent -and -not $PythonModuleFallbackPresent) {
        throw "Migrated Piper has neither the console wrapper nor the managed Python-module fallback."
    }
    if (-not (Test-Path -LiteralPath $PiperModel -PathType Leaf)) { throw "Migrated Piper model not found: $PiperModel" }
    if (-not (Test-Path -LiteralPath $ManagedModel -PathType Leaf)) { throw "Migrated managed Piper voice not found: $ManagedModel" }
    Write-Host ("Piper console wrapper: " + $(if ($WrapperPresent) { "FOUND" } else { "MISSING; Python-module fallback will be used" })) -ForegroundColor $(if ($WrapperPresent) { "Green" } else { "Yellow" })
    Write-Host ("Piper Python-module fallback: " + $(if ($PythonModuleFallbackPresent) { "FOUND" } else { "NOT REQUIRED" })) -ForegroundColor Green

    Write-Host ""
    Write-Host "==> verifying migrated Piper through the actual frozen runtime" -ForegroundColor Yellow
    $PortableExe = Join-Path $DestinationPortableRoot "S-Talking.exe"
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $RuntimeVerifyOutput = @(
        & $PortableExe --local-engines-runtime-verify --local-engines-require-piper --local-engines-expected-piper-voices 1 2>&1 |
            ForEach-Object { $_.ToString() }
    )
    $RuntimeVerifyExit = $LASTEXITCODE
    $ErrorActionPreference = $PreviousPreference
    foreach ($Line in $RuntimeVerifyOutput) { Write-Host $Line }
    if ($RuntimeVerifyExit -ne 0) {
        throw "Frozen local-engine runtime verification failed with exit code $RuntimeVerifyExit."
    }
    if (-not ($RuntimeVerifyOutput -contains "LOCAL_ENGINES_RUNTIME_VERIFY=PASS")) {
        throw "Frozen local-engine runtime verification did not report PASS."
    }
    if (-not ($RuntimeVerifyOutput -contains "LOCAL_ENGINES_PIPER_INSTALLED=1")) {
        throw "Frozen runtime still does not detect migrated Piper as installed."
    }
    if (-not ($RuntimeVerifyOutput -contains "LOCAL_ENGINES_PIPER_EXECUTABLE_PRESENT=1")) {
        throw "Frozen runtime still cannot resolve a runnable Piper executable/managed Python fallback."
    }
    if (-not ($RuntimeVerifyOutput -contains "LOCAL_ENGINES_PIPER_CLI_PROBE=1")) {
        throw "Frozen runtime resolved Piper but its CLI probe did not execute successfully."
    }

    Write-Host ""
    Write-Host "LOCAL ENGINE / PORTABLE STATE MIGRATION + FROZEN RUNTIME VERIFICATION: PASSED" -ForegroundColor Green
    Write-Host "Launcher: $DestinationLauncher" -ForegroundColor Green
    Write-Host "Piper runnable CLI: FOUND" -ForegroundColor Green
    Write-Host "Piper model: FOUND" -ForegroundColor Green
    Write-Host "Managed Piper voice: FOUND" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "LOCAL ENGINE / PORTABLE STATE MIGRATION FAILED" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    throw
}
finally {
    if ($TranscriptStarted) { try { Stop-Transcript | Out-Null } catch {} }
    if (Test-Path -LiteralPath $Log -PathType Leaf) { try { Copy-Item -LiteralPath $Log -Destination $LastLog -Force } catch {} }
    Write-Host ""
    Write-Host "Terminal log (timestamped): $Log" -ForegroundColor Cyan
    Write-Host "Terminal log (last run):    $LastLog" -ForegroundColor Cyan
}
}
