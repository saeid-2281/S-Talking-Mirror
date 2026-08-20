param(
    [string]$SourceProjectRoot = "D:\Projects\S-Talking",
    [string]$DestinationPortableRoot = ""
)

& {
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$OutputRoot = "C:\zip-for-GPT"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$LogRoot = Join-Path $OutputRoot "S-Talking-runner-logs"
$Log = Join-Path $LogRoot "S-Talking-Provider-Accounts-Migration-$Stamp.txt"
$LastLog = Join-Path $OutputRoot "S-Talking-Provider-Accounts-Migration-last-run.txt"
$TranscriptStarted = $false

function Resolve-PortableRoot([string]$Value) {
    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        return [System.IO.Path]::GetFullPath($Value.Trim('"'))
    }
    if ((Test-Path -LiteralPath (Join-Path $PSScriptRoot "S-Talking.exe")) -and
        (Test-Path -LiteralPath (Join-Path $PSScriptRoot "portable.mode"))) {
        return [System.IO.Path]::GetFullPath($PSScriptRoot)
    }
    $Entered = Read-Host "Paste the Portable folder containing S-Talking.exe and portable.mode"
    if ([string]::IsNullOrWhiteSpace($Entered)) { throw "Portable folder was not provided." }
    return [System.IO.Path]::GetFullPath($Entered.Trim('"'))
}

function Read-Json([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $Raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($Raw)) { return $null }
    return $Raw | ConvertFrom-Json
}

function Merge-ProfileMetadata($SourcePayload, $DestinationPayload) {
    if ($null -eq $SourcePayload) { throw "Source api-profiles.json could not be read." }

    $SourceProfilesProperty = $SourcePayload.PSObject.Properties["profiles"]
    $SourceProfiles = if ($null -ne $SourceProfilesProperty) { @($SourceProfilesProperty.Value) } else { @() }
    $DestinationProfiles = @()
    if ($null -ne $DestinationPayload) {
        $DestinationProfilesProperty = $DestinationPayload.PSObject.Properties["profiles"]
        if ($null -ne $DestinationProfilesProperty) { $DestinationProfiles = @($DestinationProfilesProperty.Value) }
    }

    $Seen = @{}
    $Merged = New-Object System.Collections.ArrayList
    foreach ($Profile in $SourceProfiles) {
        $Id = [string]$Profile.profile_id
        if ([string]::IsNullOrWhiteSpace($Id)) { continue }
        [void]$Merged.Add($Profile)
        $Seen[$Id] = $true
    }
    foreach ($Profile in $DestinationProfiles) {
        $Id = [string]$Profile.profile_id
        if ([string]::IsNullOrWhiteSpace($Id) -or $Seen.ContainsKey($Id)) { continue }
        [void]$Merged.Add($Profile)
        $Seen[$Id] = $true
    }
    $SourcePayload.profiles = @($Merged)

    if ($null -ne $DestinationPayload) {
        foreach ($Property in $DestinationPayload.PSObject.Properties) {
            if ($Property.Name -eq "profiles") { continue }
            if (-not ($SourcePayload.PSObject.Properties.Name -contains $Property.Name)) {
                $SourcePayload | Add-Member -NotePropertyName $Property.Name -NotePropertyValue $Property.Value
            }
        }
    }
    return $SourcePayload
}

try {
    New-Item -ItemType Directory -Path $OutputRoot,$LogRoot -Force | Out-Null
    Start-Transcript -LiteralPath $Log -Force | Out-Null
    $TranscriptStarted = $true

    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "S-Talking Provider Account Migration" -ForegroundColor Cyan
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "Provider credential contents are never printed." -ForegroundColor DarkGray

    $PortableRoot = Resolve-PortableRoot $DestinationPortableRoot
    $PortableExe = Join-Path $PortableRoot "S-Talking.exe"
    $PortableMarker = Join-Path $PortableRoot "portable.mode"
    if (-not (Test-Path -LiteralPath $PortableExe -PathType Leaf)) { throw "S-Talking.exe not found: $PortableExe" }
    if (-not (Test-Path -LiteralPath $PortableMarker -PathType Leaf)) { throw "portable.mode not found: $PortableMarker" }
    if (-not (Test-Path -LiteralPath $SourceProjectRoot -PathType Container)) { throw "Source project root not found: $SourceProjectRoot" }

    $Running = @(Get-Process -Name "S-Talking" -ErrorAction SilentlyContinue)
    if ($Running.Count -gt 0) { throw "Close every running S-Talking window before migrating accounts." }

    $SourceMetadata = Join-Path $SourceProjectRoot "api-profiles.json"
    $SourceCredentials = Join-Path $SourceProjectRoot "credentials"
    if (-not (Test-Path -LiteralPath $SourceMetadata -PathType Leaf)) {
        throw "Source api-profiles.json not found: $SourceMetadata"
    }

    # Frozen RuntimeConfig uses <Portable>\S-Talking-Data\settings.
    $DestinationSettings = Join-Path $PortableRoot "S-Talking-Data\settings"
    $DestinationMetadata = Join-Path $DestinationSettings "api-profiles.json"
    $DestinationCredentials = Join-Path $DestinationSettings "credentials"
    New-Item -ItemType Directory -Path $DestinationSettings,$DestinationCredentials -Force | Out-Null

    $SourcePayload = Read-Json $SourceMetadata
    $DestinationPayload = Read-Json $DestinationMetadata
    $MergedPayload = Merge-ProfileMetadata $SourcePayload $DestinationPayload

    if (Test-Path -LiteralPath $DestinationMetadata -PathType Leaf) {
        $Backup = "$DestinationMetadata.before-migration-$Stamp.bak"
        Copy-Item -LiteralPath $DestinationMetadata -Destination $Backup -Force
        Write-Host "Metadata backup: $Backup"
    }

    $TempMetadata = "$DestinationMetadata.$PID.tmp"
    $MetadataJson = $MergedPayload | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText(
        $TempMetadata,
        $MetadataJson,
        [System.Text.UTF8Encoding]::new($false)
    )
    Move-Item -LiteralPath $TempMetadata -Destination $DestinationMetadata -Force

    $CredentialFiles = @()
    if (Test-Path -LiteralPath $SourceCredentials -PathType Container) {
        $CredentialFiles = @(Get-ChildItem -LiteralPath $SourceCredentials -Filter "*.cred" -File -ErrorAction Stop)
        foreach ($Credential in $CredentialFiles) {
            Copy-Item -LiteralPath $Credential.FullName -Destination (Join-Path $DestinationCredentials $Credential.Name) -Force
        }
    }

    # Prefer an immediate DPAPI -> Windows Credential Manager migration when the
    # development Python is available. The helper never prints or writes raw secrets.
    $SourcePython = Join-Path $SourceProjectRoot ".venv\Scripts\python.exe"
    $NativeMigrationSummary = "not attempted"
    if (Test-Path -LiteralPath $SourcePython -PathType Leaf) {
        $Helper = Join-Path $env:TEMP "s-talking-credential-migrate-$PID-$Stamp.py"
        @'
from __future__ import annotations

import json
import sys
from pathlib import Path

source_root = Path(sys.argv[1])
destination_credentials = Path(sys.argv[2])
sys.path.insert(0, str(source_root))

from app.services.secure_credentials import SecureCredentialStore  # noqa: E402

payload = json.loads((source_root / "api-profiles.json").read_text(encoding="utf-8-sig"))
source_store = SecureCredentialStore(source_root / "credentials", platform="win32", use_native=False)
target_store = SecureCredentialStore(destination_credentials, platform="win32", use_native=True)

migrated = 0
missing = 0
for profile in payload.get("profiles", []):
    profile_id = str(profile.get("profile_id") or "").strip()
    if not profile_id:
        continue
    secret = source_store.get_password(profile_id)
    if secret:
        target_store.set_password(profile_id, secret)
        migrated += 1
    elif profile.get("has_saved_key"):
        missing += 1

print(f"native_migrated={migrated};saved_key_missing={missing};backend={target_store.backend_name}")
'@ | Set-Content -LiteralPath $Helper -Encoding UTF8
        try {
            $Previous = $ErrorActionPreference
            $ErrorActionPreference = "Continue"
            $NativeOutput = @(& $SourcePython $Helper $SourceProjectRoot $DestinationCredentials 2>&1 | ForEach-Object { $_.ToString() })
            $NativeExit = $LASTEXITCODE
            $ErrorActionPreference = $Previous
            if ($NativeExit -eq 0 -and $NativeOutput.Count -gt 0) {
                $NativeMigrationSummary = $NativeOutput[-1]
            } else {
                $NativeMigrationSummary = "native migration unavailable; legacy DPAPI fallback retained"
            }
        }
        finally {
            Remove-Item -LiteralPath $Helper -Force -ErrorAction SilentlyContinue
        }
    }

    $VerifyPayload = Read-Json $DestinationMetadata
    $Profiles = @($VerifyPayload.profiles)
    $SavedProfiles = @($Profiles | Where-Object { $_.has_saved_key -eq $true })
    $CopiedCredentialCount = @(Get-ChildItem -LiteralPath $DestinationCredentials -Filter "*.cred" -File -ErrorAction SilentlyContinue).Count

    Write-Host ""
    Write-Host "PROVIDER ACCOUNT MIGRATION: PASSED" -ForegroundColor Green
    Write-Host "Profiles in portable metadata: $($Profiles.Count)" -ForegroundColor Green
    Write-Host "Profiles marked with saved credentials: $($SavedProfiles.Count)" -ForegroundColor Green
    Write-Host "Legacy DPAPI credential files available for fallback: $CopiedCredentialCount" -ForegroundColor Green
    Write-Host "Credential migration: $NativeMigrationSummary" -ForegroundColor Green
    Write-Host "Portable metadata: $DestinationMetadata"
    Write-Host "Portable credentials: $DestinationCredentials"

    Write-Host ""
    Write-Host "==> verifying migrated accounts through the actual frozen runtime" -ForegroundColor Yellow
    $PreviousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $RuntimeVerifyOutput = @(
        & $PortableExe --provider-accounts-runtime-verify --provider-accounts-expected-count $Profiles.Count --provider-accounts-expected-saved-count $SavedProfiles.Count 2>&1 |
            ForEach-Object { $_.ToString() }
    )
    $RuntimeVerifyExit = $LASTEXITCODE
    $ErrorActionPreference = $PreviousPreference
    foreach ($Line in $RuntimeVerifyOutput) { Write-Host $Line }
    if ($RuntimeVerifyExit -ne 0) {
        throw "Frozen Provider Accounts runtime verification failed with exit code $RuntimeVerifyExit."
    }
    if (-not ($RuntimeVerifyOutput -contains "PROVIDER_ACCOUNTS_RUNTIME_VERIFY=PASS")) {
        throw "Frozen Provider Accounts runtime verification did not report PASS."
    }

    Write-Host ""
    Write-Host "PROVIDER ACCOUNT MIGRATION + FROZEN RUNTIME VERIFICATION: PASSED" -ForegroundColor Green
    Write-Host "Restart S-Talking and open Provider Accounts. The frozen runtime has verified that migrated profiles and saved credentials are visible without printing secret contents." -ForegroundColor Cyan
}
catch {
    Write-Host ""
    Write-Host "PROVIDER ACCOUNT MIGRATION FAILED" -ForegroundColor Red
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
