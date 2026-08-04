from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app
from app.config.runtime import RuntimeConfig
from app.database.connection import Database
from app.models.upgrade_recovery import UpgradeArtifact, UpgradeGate, UpgradeSnapshot


class UpgradeRecoveryService:
    """Validate upgrades and create restorable, integrity-checked user-state backups."""

    MANIFEST_NAME = "upgrade-backup-manifest.json"
    RESULT_NAME = "upgrade-backup-result.json"
    RESTORE_RESULT_NAME = "restore-result.json"
    INSTRUCTIONS_NAME = "RECOVERY.md"
    SCHEMA_VERSION = 1
    MODES = {"auto", "in_place", "portable_to_installed", "installed_to_portable", "rollback"}

    def __init__(
        self,
        runtime: RuntimeConfig,
        database: Database,
        *,
        version: str | None = None,
        target_schema: int = SCHEMA_VERSION,
    ) -> None:
        self.runtime = runtime
        self.database = database
        self.version = version or app.__version__
        self.target_schema = int(target_schema)
        self.root = runtime.artifacts_dir / "upgrade-recovery"
        self.root.mkdir(parents=True, exist_ok=True)

    def latest_backup_dir(self) -> Path:
        return self.root / "latest"

    def snapshot(
        self,
        *,
        source_version: str | None = None,
        mode: str = "auto",
        source_root: Path | None = None,
        backup_dir: Path | None = None,
    ) -> UpgradeSnapshot:
        source = Path(source_root).resolve() if source_root else None
        resolved_mode = self._mode(mode, source)
        source_layout = self._source_layout(source)
        version = str(source_version or self._version_from_root(source) or self.version)
        rollback = self._version_key(version) > self._version_key(self.version) or resolved_mode == "rollback"
        database_path = source_layout["database"]
        current_schema = self._database_schema(database_path)
        gates: list[UpgradeGate] = []
        artifacts: list[UpgradeArtifact] = []

        source_ok = source is None or source.exists()
        gates.append(
            self._gate(
                "source_root",
                "Upgrade source",
                source_ok,
                "blocker",
                (
                    f"Source data root is available: {source}"
                    if source is not None and source_ok
                    else "Current application data is the upgrade source."
                    if source is None
                    else f"Source data root does not exist: {source}"
                ),
                "Select the previous installed data root or extracted portable directory.",
            )
        )

        mode_ok, mode_detail = self._mode_contract(resolved_mode, source)
        gates.append(
            self._gate(
                "transition_mode",
                "Upgrade transition mode",
                mode_ok,
                "blocker",
                mode_detail,
                "Use in-place for installed upgrades or select a portable folder containing portable.mode or S-Talking-Data.",
            )
        )

        db_exists = database_path.exists()
        db_health = "ok"
        if db_exists:
            try:
                db_health = Database(database_path).quick_check()
            except Exception as exc:
                db_health = f"unreadable: {exc}"
        gates.append(
            self._gate(
                "database_health",
                "Database health",
                not db_exists or db_health == "ok",
                "blocker",
                "No existing database; this is a clean-data upgrade." if not db_exists else f"SQLite quick_check: {db_health}",
                "Repair or restore the database before upgrading.",
            )
        )

        schema_ok = current_schema <= self.target_schema
        gates.append(
            self._gate(
                "schema_compatibility",
                "Database schema compatibility",
                schema_ok,
                "blocker",
                (
                    f"Schema {current_schema} can be opened and migrated to schema {self.target_schema}."
                    if schema_ok
                    else f"Source schema {current_schema} is newer than supported schema {self.target_schema}."
                ),
                "Use an application build that supports this database schema or restore a compatible pre-upgrade backup.",
            )
        )

        metadata_ok, metadata_detail = self._metadata_health(source_layout)
        gates.append(
            self._gate(
                "settings_metadata",
                "Settings and profile metadata",
                metadata_ok,
                "warning",
                metadata_detail,
                "Repair malformed JSON metadata or preserve it separately before continuing.",
            )
        )

        rollback_detail = (
            f"Controlled rollback from {version} to {self.version} requires a compatible schema backup."
            if rollback
            else f"Upgrade path {version} → {self.version} is supported."
        )
        gates.append(
            self._gate(
                "version_direction",
                "Version direction",
                not rollback or schema_ok,
                "warning" if rollback else "blocker",
                rollback_detail,
                "Create and verify a backup before rollback; never downgrade a newer schema in place.",
            )
        )

        backup = Path(backup_dir).resolve() if backup_dir else None
        backup_ok = bool(backup and self.verify_backup(backup)[0])
        gates.append(
            self._gate(
                "pre_upgrade_backup",
                "Verified pre-upgrade backup",
                backup_ok,
                "warning",
                f"Verified backup is available: {backup}" if backup_ok else "A verified pre-upgrade backup has not been attached yet.",
                "Create a backup before installing, migrating, moving from portable mode, or rolling back.",
            )
        )
        if backup_ok and backup:
            manifest = backup / self.MANIFEST_NAME
            artifacts.append(self._artifact("backup_manifest", manifest))
            database_backup = backup / "payload" / "database" / "s_talking.db"
            if database_backup.exists():
                artifacts.append(self._artifact("database_backup", database_backup))

        backup_root_ok = self._writable(self.root)
        gates.append(
            self._gate(
                "recovery_location",
                "Recovery workspace",
                backup_root_ok,
                "blocker",
                f"Recovery workspace is writable: {self.root}" if backup_root_ok else f"Recovery workspace is not writable: {self.root}",
                "Choose a writable local location outside the program installation directory.",
            )
        )

        gates.append(
            self._gate(
                "user_data_preservation",
                "User-data preservation contract",
                True,
                "blocker",
                "Projects, settings, provider metadata, encrypted credentials and the database remain outside the program directory; source files and generated audio are never moved or deleted.",
            )
        )

        status = self._status(gates)
        migration_required = db_exists and 0 <= current_schema < self.target_schema
        return UpgradeSnapshot(
            operation_id=self._operation_id(version, resolved_mode, source),
            captured_at=self._now(),
            source_version=version,
            target_version=self.version,
            mode=resolved_mode,
            status=status,
            summary=self._summary(status, gates, migration_required, rollback),
            source_root=source,
            target_root=self.runtime.settings_path.parent,
            backup_dir=backup if backup_ok else None,
            current_schema=max(0, current_schema),
            target_schema=self.target_schema,
            migration_required=migration_required,
            rollback=rollback,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )

    def create_backup(
        self,
        *,
        source_version: str | None = None,
        mode: str = "auto",
        source_root: Path | None = None,
        label: str = "pre-upgrade",
    ) -> UpgradeSnapshot:
        initial = self.snapshot(source_version=source_version, mode=mode, source_root=source_root)
        if initial.blocker_count:
            raise RuntimeError(initial.summary)
        source_layout = self._source_layout(initial.source_root)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_label = re.sub(r"[^a-z0-9-]+", "-", label.casefold()).strip("-") or "backup"
        backup = self.root / f"S-Talking-{self.version}-{safe_label}-{stamp}"
        payload = backup / "payload"
        backup.mkdir(parents=True, exist_ok=False)
        copied: list[dict[str, object]] = []

        try:
            database_path = source_layout["database"]
            if database_path.exists():
                target = payload / "database" / "s_talking.db"
                Database(database_path).backup_to(target)
                copied.append(self._file_record("database", target, backup, secret=False))

            legacy = source_layout["legacy_database"]
            if legacy.exists() and legacy.resolve() != database_path.resolve():
                target = payload / "database" / "s-talking.db"
                self._atomic_copy(legacy, target)
                copied.append(self._file_record("legacy_database", target, backup, secret=False))

            for role, source_path, target_relative, secret in self._critical_files(source_layout):
                if not source_path.exists():
                    continue
                if source_path.is_dir():
                    for child in sorted(source_path.rglob("*")):
                        if not child.is_file() or child.is_symlink():
                            continue
                        relative = child.relative_to(source_path)
                        target = payload / target_relative / relative
                        self._atomic_copy(child, target)
                        copied.append(self._file_record(role, target, backup, secret=secret))
                else:
                    target = payload / target_relative
                    self._atomic_copy(source_path, target)
                    copied.append(self._file_record(role, target, backup, secret=secret))

            manifest = {
                "schema_version": self.SCHEMA_VERSION,
                "backup_id": initial.operation_id,
                "created_at": self._now(),
                "source_version": initial.source_version,
                "target_version": self.version,
                "mode": initial.mode,
                "source_root": str(initial.source_root or self.runtime.settings_path.parent),
                "target_schema": self.target_schema,
                "database_schema": initial.current_schema,
                "files": copied,
            }
            self._write_json(backup / self.MANIFEST_NAME, manifest)
            (backup / self.INSTRUCTIONS_NAME).write_text(self._recovery_text(backup), encoding="utf-8")
            ok, detail = self.verify_backup(backup)
            result = {
                "schema_version": 1,
                "status": "verified" if ok else "failed",
                "detail": detail,
                "backup_dir": str(backup),
                "file_count": len(copied),
                "created_at": self._now(),
            }
            self._write_json(backup / self.RESULT_NAME, result)
            if not ok:
                raise RuntimeError(detail)
            self._publish_latest(backup)
            return self.snapshot(
                source_version=initial.source_version,
                mode=initial.mode,
                source_root=initial.source_root,
                backup_dir=backup,
            )
        except Exception:
            shutil.rmtree(backup, ignore_errors=True)
            raise

    def verify_backup(self, backup_dir: Path) -> tuple[bool, str]:
        backup = Path(backup_dir)
        manifest_path = backup / self.MANIFEST_NAME
        payload = self._json(manifest_path)
        if int(payload.get("schema_version", 0) or 0) != self.SCHEMA_VERSION:
            return False, "Backup manifest is missing or uses an unsupported schema."
        files = payload.get("files")
        if not isinstance(files, list):
            return False, "Backup manifest file list is missing."
        for item in files:
            if not isinstance(item, dict):
                return False, "Backup manifest contains an invalid file entry."
            relative = str(item.get("relative_path") or "")
            if not self._safe_relative(relative):
                return False, f"Unsafe backup path: {relative}"
            path = backup / relative
            try:
                resolved = path.resolve()
                backup_root = backup.resolve()
            except OSError:
                return False, f"Backup path cannot be resolved: {relative}"
            if path.is_symlink() or backup_root not in resolved.parents:
                return False, f"Backup path escapes the verified backup root: {relative}"
            if not path.exists() or not path.is_file():
                return False, f"Backup file is missing: {relative}"
            if int(item.get("size_bytes", -1)) != path.stat().st_size:
                return False, f"Backup size mismatch: {relative}"
            if str(item.get("sha256") or "") != self._sha256(path):
                return False, f"Backup integrity mismatch: {relative}"
        database_path = backup / "payload" / "database" / "s_talking.db"
        if database_path.exists():
            try:
                if Database(database_path).quick_check() != "ok":
                    return False, "Backup database quick_check failed."
            except Exception as exc:
                return False, f"Backup database is unreadable: {exc}"
        return True, f"Verified {len(files)} backup file(s)."

    def validate_migration(
        self,
        *,
        source_root: Path | None = None,
        source_version: str | None = None,
    ) -> dict[str, object]:
        layout = self._source_layout(Path(source_root).resolve() if source_root else None)
        source_database = layout["database"]
        result: dict[str, object] = {
            "schema_version": 1,
            "captured_at": self._now(),
            "source_version": str(source_version or self._version_from_root(source_root) or self.version),
            "target_version": self.version,
            "target_schema": self.target_schema,
            "source_database": str(source_database),
        }
        if not source_database.exists():
            result.update(status="ready", detail="No database exists; no migration is required.", before_schema=0, after_schema=0)
            return self._write_validation_result(result)

        before = self._database_schema(source_database)
        result["before_schema"] = before
        if before > self.target_schema:
            result.update(status="blocked", detail=f"Source schema {before} is newer than supported schema {self.target_schema}.", after_schema=before)
            return self._write_validation_result(result)

        validation_dir = Path(tempfile.mkdtemp(prefix="migration-", dir=self.root))
        staged = validation_dir / "s_talking.db"
        try:
            Database(source_database).backup_to(staged)
            candidate = Database(staged)
            candidate.initialize()
            after = max(candidate.applied_schema_versions(), default=0)
            quick_check = candidate.quick_check()
            violations = candidate.foreign_key_violations()
            ready = after == self.target_schema and quick_check == "ok" and not violations
            result.update(
                status="ready" if ready else "blocked",
                detail=(
                    f"Disposable migration reached schema {after}; quick_check={quick_check}; foreign_keys={len(violations)}."
                ),
                after_schema=after,
                quick_check=quick_check,
                foreign_key_violations=len(violations),
                migration_required=before < after,
            )
            return self._write_validation_result(result)
        except Exception as exc:
            result.update(status="blocked", detail=f"Disposable migration failed: {exc}", after_schema=before)
            return self._write_validation_result(result)
        finally:
            shutil.rmtree(validation_dir, ignore_errors=True)

    def restore_backup(
        self,
        backup_dir: Path,
        *,
        dry_run: bool = True,
        acknowledge: bool = False,
    ) -> dict[str, object]:
        backup = Path(backup_dir).resolve()
        ok, detail = self.verify_backup(backup)
        if not ok:
            raise RuntimeError(detail)
        manifest = self._json(backup / self.MANIFEST_NAME)
        backup_schema = int(manifest.get("database_schema", 0) or 0)
        if backup_schema > self.target_schema:
            raise RuntimeError(
                f"Backup schema {backup_schema} is newer than supported schema {self.target_schema}."
            )
        plan = self._restore_plan(backup, manifest)
        if dry_run:
            result = {
                "schema_version": 1,
                "status": "dry_run",
                "detail": f"Restore plan validated for {len(plan)} file(s); no files were changed.",
                "backup_dir": str(backup),
                "operations": plan,
                "captured_at": self._now(),
            }
            self._write_json(backup / self.RESTORE_RESULT_NAME, result)
            return result
        if not acknowledge:
            raise PermissionError("Actual restore requires explicit acknowledgement.")

        safety_dir: Path | None = None
        safety_verified = False
        safety_warning = ""
        try:
            safety = self.create_backup(label="pre-restore-safety")
            safety_dir = safety.backup_dir
            safety_verified = bool(safety_dir)
        except Exception as safety_exc:
            safety_dir = self._create_emergency_safety_snapshot(safety_exc)
            safety_warning = f" Verified safety backup was unavailable; raw forensic state saved to {safety_dir}."
        try:
            self._apply_restore(backup, manifest)
            result = {
                "schema_version": 1,
                "status": "restored",
                "detail": "Backup restored and active database verified." + safety_warning,
                "backup_dir": str(backup),
                "safety_backup": str(safety_dir or ""),
                "operations": plan,
                "captured_at": self._now(),
            }
            self._write_json(backup / self.RESTORE_RESULT_NAME, result)
            return result
        except Exception as exc:
            rollback_detail = "Safety backup unavailable."
            if safety_dir and safety_verified:
                try:
                    safety_manifest = self._json(safety_dir / self.MANIFEST_NAME)
                    self._apply_restore(safety_dir, safety_manifest)
                    rollback_detail = f"Current state was recovered from {safety_dir}."
                except Exception as rollback_exc:
                    rollback_detail = f"Automatic recovery failed: {rollback_exc}"
            elif safety_dir:
                rollback_detail = f"Raw forensic state is available at {safety_dir}; automatic rollback was not possible."
            result = {
                "schema_version": 1,
                "status": "failed",
                "detail": f"Restore failed: {exc}. {rollback_detail}",
                "backup_dir": str(backup),
                "safety_backup": str(safety_dir or ""),
                "captured_at": self._now(),
            }
            self._write_json(backup / self.RESTORE_RESULT_NAME, result)
            raise RuntimeError(result["detail"]) from exc

    def export_snapshot(self, snapshot: UpgradeSnapshot | None = None) -> Path:
        current = snapshot or self.snapshot()
        target = self.runtime.reports_dir / "upgrade-recovery" / f"upgrade-{current.operation_id}.json"
        self._write_json(target, current.to_dict())
        return target

    def _create_emergency_safety_snapshot(self, reason: Exception) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        target = self.root / f"emergency-pre-restore-{stamp}"
        target.mkdir(parents=True, exist_ok=False)
        records: list[dict[str, object]] = []
        candidates = [
            ("database_raw", self.runtime.database_path),
            ("legacy_database_raw", self.runtime.legacy_database_path),
            ("settings_raw", self.runtime.settings_path),
            ("api_profiles_raw", self.runtime.settings_path.parent / "api-profiles.json"),
            ("workspace_profiles_raw", self.runtime.settings_path.parent / "workspace-profiles.json"),
        ]
        for role, source in candidates:
            if not source.exists() or not source.is_file():
                continue
            destination = target / "raw" / source.name
            try:
                self._atomic_copy(source, destination)
            except OSError:
                continue
            records.append(self._file_record(role, destination, target, secret=False))
        credentials = self.runtime.settings_path.parent / "credentials"
        if credentials.exists():
            for source in sorted(credentials.rglob("*")):
                if not source.is_file() or source.is_symlink():
                    continue
                destination = target / "raw" / "credentials" / source.relative_to(credentials)
                try:
                    self._atomic_copy(source, destination)
                except OSError:
                    continue
                records.append(self._file_record("credentials_raw", destination, target, secret=True))
        self._write_json(
            target / "emergency-snapshot.json",
            {
                "schema_version": 1,
                "created_at": self._now(),
                "status": "forensic_only",
                "reason": str(reason),
                "files": records,
            },
        )
        return target

    def _apply_restore(self, backup: Path, manifest: dict[str, Any]) -> None:
        files = manifest.get("files", [])
        database_entry = next((item for item in files if item.get("role") == "database"), None)
        if database_entry:
            source = backup / str(database_entry["relative_path"])
            self.database.restore_from(source)
        for item in files:
            role = str(item.get("role") or "")
            if role == "database":
                continue
            source = backup / str(item["relative_path"])
            target = self._restore_target(role, source, backup)
            self._atomic_copy(source, target)
        if self.runtime.database_path.exists():
            active = Database(self.runtime.database_path)
            if active.quick_check() != "ok":
                raise sqlite3.DatabaseError("Restored database quick_check failed")
            schema = max(active.applied_schema_versions(), default=0)
            if schema > self.target_schema:
                raise sqlite3.DatabaseError("Restored database schema is unsupported")

    def _restore_plan(self, backup: Path, manifest: dict[str, Any]) -> list[dict[str, str]]:
        operations: list[dict[str, str]] = []
        for item in manifest.get("files", []):
            role = str(item.get("role") or "")
            source = backup / str(item.get("relative_path") or "")
            target = self.runtime.database_path if role == "database" else self._restore_target(role, source, backup)
            operations.append({"role": role, "source": str(source), "target": str(target)})
        return operations

    def _restore_target(self, role: str, source: Path, backup: Path) -> Path:
        payload = backup / "payload"
        relative = source.relative_to(payload)
        if role == "legacy_database":
            return self.runtime.legacy_database_path
        if role == "settings":
            return self.runtime.settings_path
        if role == "api_profiles":
            return self.runtime.settings_path.parent / "api-profiles.json"
        if role == "workspace_profiles":
            return self.runtime.settings_path.parent / "workspace-profiles.json"
        if role == "credentials":
            suffix = relative.relative_to(Path("settings") / "credentials")
            return self.runtime.settings_path.parent / "credentials" / suffix
        if role == "pronunciation_dictionaries":
            suffix = relative.relative_to(Path("settings") / "pronunciation-dictionaries")
            return self.runtime.settings_path.parent / "pronunciation-dictionaries" / suffix
        if role == "data_file":
            suffix = relative.relative_to("data")
            return self.runtime.data_dir / suffix
        raise ValueError(f"Unsupported restore role: {role}")

    def _critical_files(self, layout: dict[str, Path]) -> tuple[tuple[str, Path, Path, bool], ...]:
        items: list[tuple[str, Path, Path, bool]] = [
            ("settings", layout["settings"], Path("settings/settings.json"), False),
            ("api_profiles", layout["settings_dir"] / "api-profiles.json", Path("settings/api-profiles.json"), False),
            ("workspace_profiles", layout["settings_dir"] / "workspace-profiles.json", Path("settings/workspace-profiles.json"), False),
            ("credentials", layout["settings_dir"] / "credentials", Path("settings/credentials"), True),
            ("pronunciation_dictionaries", layout["settings_dir"] / "pronunciation-dictionaries", Path("settings/pronunciation-dictionaries"), False),
        ]
        data_dir = layout["data_dir"]
        if data_dir.exists():
            excluded = {
                layout["database"].resolve(),
                layout["legacy_database"].resolve(),
            }
            for child in sorted(data_dir.rglob("*")):
                if not child.is_file() or child.is_symlink() or child.resolve() in excluded:
                    continue
                if child.suffix.casefold() in {".wal", ".shm", ".bak"}:
                    continue
                relative = child.relative_to(data_dir)
                items.append(("data_file", child, Path("data") / relative, False))
        return tuple(items)

    def _source_layout(self, source_root: Path | None) -> dict[str, Path]:
        if source_root is None:
            return {
                "data_root": self.runtime.settings_path.parent,
                "data_dir": self.runtime.data_dir,
                "database": self.runtime.database_path,
                "legacy_database": self.runtime.legacy_database_path,
                "settings_dir": self.runtime.settings_path.parent,
                "settings": self.runtime.settings_path,
            }
        root = Path(source_root)
        if (root / "portable.mode").exists():
            data_root = root / "S-Talking-Data"
        elif (root / "S-Talking-Data").exists():
            data_root = root / "S-Talking-Data"
        else:
            data_root = root
        settings_dir = data_root / "settings" if (data_root / "settings").exists() else data_root
        data_dir = data_root / "data"
        return {
            "data_root": data_root,
            "data_dir": data_dir,
            "database": data_dir / "s_talking.db",
            "legacy_database": data_dir / "s-talking.db",
            "settings_dir": settings_dir,
            "settings": settings_dir / "settings.json",
        }

    def _metadata_health(self, layout: dict[str, Path]) -> tuple[bool, str]:
        checked = 0
        malformed: list[str] = []
        for path in (
            layout["settings"],
            layout["settings_dir"] / "api-profiles.json",
            layout["settings_dir"] / "workspace-profiles.json",
        ):
            if not path.exists():
                continue
            checked += 1
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
                if not isinstance(value, dict):
                    malformed.append(path.name)
            except (OSError, json.JSONDecodeError):
                malformed.append(path.name)
        if malformed:
            return False, f"Malformed metadata: {', '.join(malformed)}"
        return True, f"Validated {checked} settings/profile metadata file(s)."

    def _mode(self, mode: str, source: Path | None) -> str:
        value = str(mode or "auto").strip().casefold()
        if value not in self.MODES:
            raise ValueError(f"Unsupported upgrade mode: {mode}")
        if value != "auto":
            return value
        if source and ((source / "portable.mode").exists() or (source / "S-Talking-Data").exists()):
            return "portable_to_installed"
        return "in_place"

    def _mode_contract(self, mode: str, source: Path | None) -> tuple[bool, str]:
        if mode == "portable_to_installed":
            valid = bool(source and ((source / "portable.mode").exists() or (source / "S-Talking-Data").exists()))
            return valid, "Portable user data will be copied into the installed user-data root without modifying the portable source." if valid else "Portable transition requires a directory containing portable.mode or S-Talking-Data."
        if mode == "installed_to_portable":
            return True, "Installed user data will be backed up before a portable data root is prepared."
        if mode == "rollback":
            return True, "Rollback mode requires a verified schema-compatible backup and never downgrades the active database in place."
        return True, "In-place upgrade preserves the stable user-data root and installation identity."

    def _file_record(self, role: str, path: Path, backup: Path, *, secret: bool) -> dict[str, object]:
        return {
            "role": role,
            "relative_path": path.relative_to(backup).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": self._sha256(path),
            "secret_material": bool(secret),
        }

    def _artifact(self, role: str, path: Path) -> UpgradeArtifact:
        return UpgradeArtifact(
            role=role,
            path=path,
            size_bytes=path.stat().st_size if path.exists() else 0,
            sha256=self._sha256(path) if path.exists() else "",
        )

    def _write_validation_result(self, result: dict[str, object]) -> dict[str, object]:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        target = self.root / f"migration-validation-{stamp}.json"
        result["result_path"] = str(target)
        self._write_json(target, result)
        return result

    def _publish_latest(self, backup: Path) -> None:
        latest = self.latest_backup_dir()
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(backup, latest)

    def _recovery_text(self, backup: Path) -> str:
        return (
            f"# S-Talking recovery backup\n\n"
            f"Backup: `{backup}`\n\n"
            "1. Close S Talking and confirm no S-Talking.exe or python process is using the database.\n"
            "2. Verify the backup manifest before restoring.\n"
            "3. Run `S-Talking.exe --restore-backup <path> --acknowledge-restore` from the installed or portable package.\n"
            "   Source checkouts may instead use `scripts\\upgrade-validation.ps1 -RestoreBackup <path> -AcknowledgeRestore`.\n"
            "4. The recovery tool creates a second safety backup before changing active data.\n"
            "5. Launch with the mock provider and verify an existing project before reconnecting paid providers.\n\n"
            "Generated audio and external project source files are never deleted or moved by recovery.\n"
        )

    def _version_from_root(self, source_root: Path | None) -> str:
        if source_root is None:
            return ""
        root = Path(source_root)
        for path in (root / "build-metadata.json", root / "release-candidate-manifest.json"):
            payload = self._json(path)
            value = str(payload.get("version") or "")
            if value:
                return value
        return ""

    @staticmethod
    def _database_schema(path: Path) -> int:
        if not path.exists():
            return 0
        connection = sqlite3.connect(path)
        try:
            try:
                rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
            except sqlite3.Error:
                return 0
            return max((int(row[0]) for row in rows), default=0)
        finally:
            connection.close()

    @staticmethod
    def _version_key(value: str) -> tuple[int, int, int, int, int]:
        match = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-.]?(rc|beta|alpha)(\d+)?)?", str(value), re.I)
        if not match:
            return (0, 0, 0, 0, 0)
        major, minor, patch = (int(match.group(i) or 0) for i in (1, 2, 3))
        tag = (match.group(4) or "").casefold()
        rank = {"alpha": 0, "beta": 1, "rc": 2, "": 3}[tag]
        return (major, minor, patch, rank, int(match.group(5) or 0))

    def _operation_id(self, version: str, mode: str, source: Path | None) -> str:
        seed = f"{version}|{self.version}|{mode}|{source or self.runtime.settings_path.parent}|{self.target_schema}".encode()
        return hashlib.sha256(seed).hexdigest()[:16]

    @staticmethod
    def _safe_relative(value: str) -> bool:
        path = Path(value)
        return bool(value) and not path.is_absolute() and ".." not in path.parts

    @staticmethod
    def _writable(path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            handle, name = tempfile.mkstemp(prefix=".write-test-", dir=path)
            os.close(handle)
            Path(name).unlink(missing_ok=True)
            return True
        except OSError:
            return False

    @staticmethod
    def _atomic_copy(source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
        os.close(handle)
        temporary = Path(name)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _gate(code: str, label: str, passed: bool, severity: str, detail: str, remediation: str = "") -> UpgradeGate:
        return UpgradeGate(code, label, "passed" if passed else "failed", severity, detail, remediation)

    @staticmethod
    def _status(gates: list[UpgradeGate]) -> str:
        if any(item.severity == "blocker" and not item.passed for item in gates):
            return "blocked"
        if any(not item.passed for item in gates):
            return "ready_with_warnings"
        return "ready"

    @staticmethod
    def _summary(status: str, gates: list[UpgradeGate], migration: bool, rollback: bool) -> str:
        blockers = sum(item.severity == "blocker" and not item.passed for item in gates)
        warnings = sum(item.severity == "warning" and not item.passed for item in gates)
        if status == "blocked":
            return f"Upgrade or recovery is blocked by {blockers} mandatory gate(s)."
        action = "Rollback" if rollback else "Upgrade"
        migration_text = " with a disposable migration required" if migration else ""
        if status == "ready_with_warnings":
            return f"{action} is compatible{migration_text}, with {warnings} warning(s)."
        return f"{action} and recovery path are verified{migration_text}."

    @staticmethod
    def _json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
