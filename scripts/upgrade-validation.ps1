param(
    [string]$Python = ".\.venv\Scripts\python.exe",
    [string]$SourceVersion = "",
    [ValidateSet("auto", "in_place", "portable_to_installed", "installed_to_portable", "rollback")]
    [string]$Mode = "auto",
    [string]$SourceRoot = "",
    [switch]$CreateBackup,
    [switch]$ValidateMigration,
    [string]$VerifyBackup = "",
    [string]$RestoreBackup = "",
    [switch]$AcknowledgeRestore
)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path ".").Path
$pythonPath = Join-Path $repo $Python
if (!(Test-Path $pythonPath)) { $pythonPath = $Python }

if ($RestoreBackup) {
    $running = Get-Process -Name "S-Talking" -ErrorAction SilentlyContinue
    if ($running) {
        throw "Close every running S-Talking.exe process before restoring user data."
    }
    if (!$AcknowledgeRestore) {
        throw "Actual restore requires -AcknowledgeRestore. Run without it only after reviewing the dry-run plan in the application."
    }
}

$env:S_TALKING_UPGRADE_SOURCE_VERSION = $SourceVersion
$env:S_TALKING_UPGRADE_MODE = $Mode
$env:S_TALKING_UPGRADE_SOURCE_ROOT = $SourceRoot
$env:S_TALKING_UPGRADE_CREATE_BACKUP = if ($CreateBackup) { "1" } else { "0" }
$env:S_TALKING_UPGRADE_VALIDATE_MIGRATION = if ($ValidateMigration) { "1" } else { "0" }
$env:S_TALKING_UPGRADE_VERIFY_BACKUP = $VerifyBackup
$env:S_TALKING_UPGRADE_RESTORE_BACKUP = $RestoreBackup
$env:S_TALKING_UPGRADE_ACKNOWLEDGE = if ($AcknowledgeRestore) { "1" } else { "0" }
$tempScript = Join-Path ([System.IO.Path]::GetTempPath()) ("s-talking-upgrade-{0}.py" -f ([guid]::NewGuid().ToString("N")))
$code = @'
import os
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.database.connection import Database
from app.services.upgrade_recovery_service import UpgradeRecoveryService

runtime = RuntimeConfig.from_root()
runtime.ensure_directories()
service = UpgradeRecoveryService(runtime, Database(runtime.database_path))
source_version = os.environ.get("S_TALKING_UPGRADE_SOURCE_VERSION") or None
mode = os.environ.get("S_TALKING_UPGRADE_MODE") or "auto"
source_value = os.environ.get("S_TALKING_UPGRADE_SOURCE_ROOT") or ""
source_root = Path(source_value) if source_value else None
verify_value = os.environ.get("S_TALKING_UPGRADE_VERIFY_BACKUP") or ""
restore_value = os.environ.get("S_TALKING_UPGRADE_RESTORE_BACKUP") or ""

snapshot = service.snapshot(source_version=source_version, mode=mode, source_root=source_root)
print(f"Status:       {snapshot.status}")
print(f"Versions:     {snapshot.source_version} -> {snapshot.target_version}")
print(f"Mode:         {snapshot.mode}")
print(f"Schema:       {snapshot.current_schema}/{snapshot.target_schema}")
for gate in snapshot.gates:
    if not gate.passed:
        print(f" - {gate.label} [{gate.severity}]: {gate.detail}")
if snapshot.blocker_count and not (verify_value or restore_value):
    raise SystemExit(1)

if os.environ.get("S_TALKING_UPGRADE_CREATE_BACKUP") == "1":
    backup = service.create_backup(source_version=source_version, mode=mode, source_root=source_root)
    print(f"Backup:       {backup.backup_dir}")
    print("Backup status: verified")

if os.environ.get("S_TALKING_UPGRADE_VALIDATE_MIGRATION") == "1":
    result = service.validate_migration(source_root=source_root, source_version=source_version)
    print(f"Migration:    {result['status']}")
    print(f"Migration log:{result.get('result_path', '')}")
    print(f"Detail:       {result.get('detail', '')}")
    if result.get("status") != "ready":
        raise SystemExit(1)

if verify_value:
    ok, detail = service.verify_backup(Path(verify_value))
    print(f"Verification: {'passed' if ok else 'failed'}")
    print(f"Detail:       {detail}")
    if not ok:
        raise SystemExit(1)

if restore_value:
    result = service.restore_backup(
        Path(restore_value),
        dry_run=False,
        acknowledge=os.environ.get("S_TALKING_UPGRADE_ACKNOWLEDGE") == "1",
    )
    print(f"Restore:      {result['status']}")
    print(f"Safety backup:{result.get('safety_backup', '')}")
    print(f"Detail:       {result.get('detail', '')}")
'@
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($tempScript, $code, $utf8NoBom)
try {
    Write-Host "==> validate upgrade, rollback and recovery" -ForegroundColor Cyan
    & $pythonPath $tempScript
    if ($LASTEXITCODE -ne 0) { throw "Upgrade or recovery validation failed." }
    Write-Host "Upgrade and recovery validation completed." -ForegroundColor Green
} finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
    Get-ChildItem Env:S_TALKING_UPGRADE_* | Remove-Item -ErrorAction SilentlyContinue
}
