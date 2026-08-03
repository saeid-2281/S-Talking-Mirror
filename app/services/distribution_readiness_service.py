from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import app
from app.config.runtime import RuntimeConfig
from app.models.distribution_readiness import (
    DistributionArtifact,
    DistributionGate,
    DistributionSnapshot,
)
from app.release import RELEASE_CHANNEL, SCHEMA_VERSION
from app.services.release_candidate_service import ReleaseCandidateService


class DistributionReadinessService:
    """Validate installer/upgrade contracts and stage an auditable distribution bundle."""

    MANIFEST_NAME = "distribution-manifest.json"
    CHECKSUM_NAME = "SHA256SUMS.txt"
    RESULT_NAME = "distribution-result.json"
    UPGRADE_PLAN_NAME = "upgrade-plan.json"
    ROLLBACK_NAME = "ROLLBACK.md"
    INSTALL_NAME = "INSTALL.md"
    STABLE_APP_ID = "BD8A7352-0C93-4C2E-ACD7-7F3F5C8AA221"

    def __init__(
        self,
        runtime: RuntimeConfig,
        release_candidate_service: ReleaseCandidateService,
        *,
        version: str | None = None,
        release_channel: str = RELEASE_CHANNEL,
        schema_version: int = SCHEMA_VERSION,
    ) -> None:
        self.runtime = runtime
        self.release_candidate_service = release_candidate_service
        self.version = version or app.__version__
        self.release_channel = release_channel
        self.schema_version = int(schema_version)
        self.root = runtime.artifacts_dir / "distribution"

    def latest_distribution_dir(self) -> Path:
        return self.root / "latest"

    def snapshot(self, candidate_dir: Path | None = None) -> DistributionSnapshot:
        source = Path(candidate_dir or self.release_candidate_service.latest_candidate_dir())
        manifest_path = source / self.release_candidate_service.MANIFEST_NAME
        installer_result = self._installer_result()
        installer_path = self._installer_path(installer_result)
        installer_available = bool(installer_result.get("available")) and bool(
            installer_path and installer_path.exists()
        )
        installer_distributable = self._is_real_installer(installer_path)

        gates: list[DistributionGate] = []
        artifacts: list[DistributionArtifact] = []

        manifest_ok = False
        manifest_detail = "No verified release-candidate manifest is available."
        if manifest_path.exists():
            manifest_ok, manifest_detail = self.release_candidate_service.verify_manifest(manifest_path)
            artifacts.append(self._artifact("release_candidate_manifest", manifest_path))
        gates.append(
            self._gate(
                "release_candidate",
                "Verified release candidate",
                manifest_ok,
                "blocker",
                manifest_detail,
                "Build and verify Phase 50 release candidate before staging distribution.",
            )
        )

        build_result = self._build_result()
        build_ok = bool(build_result.get("success")) and str(build_result.get("version") or "") == self.version
        build_detail = (
            f"Frozen build result is successful for version {self.version}."
            if build_ok
            else "A successful frozen build result for the current version is missing."
        )
        gates.append(
            self._gate(
                "frozen_build",
                "Frozen application build",
                build_ok,
                "blocker",
                build_detail,
                "Run scripts/build.ps1 successfully before staging distribution.",
            )
        )

        package = self._compiled_portable_path(build_result)
        package_ok, package_detail = self._audit_compiled_portable(package)
        if package and package.exists():
            artifacts.append(
                self._artifact(
                    "portable_package",
                    package,
                    "verified" if package_ok else "failed",
                    package_detail,
                )
            )
        gates.append(
            self._gate(
                "compiled_portable",
                "Compiled portable package",
                package_ok,
                "blocker",
                package_detail,
                "Build the frozen portable ZIP and verify S-Talking.exe, portable.mode, RUN.cmd, and package privacy.",
            )
        )

        contract_ok, contract_detail = self._installer_contract()
        gates.append(
            self._gate(
                "installer_contract",
                "Installer definition",
                contract_ok,
                "blocker",
                contract_detail,
                "Use the hardened per-user Inno Setup definition from Phase 52.",
            )
        )

        per_user_ok, per_user_detail = self._per_user_install_contract()
        gates.append(
            self._gate(
                "per_user_install",
                "Per-user install scope",
                per_user_ok,
                "blocker",
                per_user_detail,
                "Install under LocalAppData with lowest privileges and keep writable data outside the program directory.",
            )
        )

        upgrade_ok, upgrade_detail = self._upgrade_contract()
        gates.append(
            self._gate(
                "upgrade_contract",
                "In-place upgrade safety",
                upgrade_ok,
                "blocker",
                upgrade_detail,
                "Keep the stable AppId, previous install directory, close-running-app behavior, and non-destructive uninstall policy.",
            )
        )

        installer_detail = self._installer_detail(installer_result, installer_path)
        gates.append(
            self._gate(
                "installer_artifact",
                "Compiled Windows installer",
                installer_distributable,
                "warning",
                installer_detail,
                "Install Inno Setup and run scripts/build.ps1 to compile a real unsigned installer.",
            )
        )
        if installer_path and installer_path.exists():
            artifacts.append(
                self._artifact(
                    "windows_installer",
                    installer_path,
                    "verified" if installer_distributable else "failed",
                    installer_detail,
                )
            )

        version_ok = not installer_distributable or self.version in installer_path.name
        gates.append(
            self._gate(
                "installer_version",
                "Installer version identity",
                version_ok,
                "blocker",
                (
                    f"Installer filename matches {self.version}."
                    if version_ok
                    else f"Installer filename does not contain version {self.version}."
                ),
                "Rebuild the installer from the current release candidate.",
            )
        )

        data_ok = "S-Talking" in str(self.runtime.data_dir) or not getattr(__import__("sys"), "frozen", False)
        gates.append(
            self._gate(
                "data_isolation",
                "Application data isolation",
                data_ok,
                "blocker",
                "Installed builds use %LOCALAPPDATA%\\S-Talking; portable builds use S-Talking-Data beside the executable.",
                "Do not store settings, credentials, databases, logs, or outputs under the installed program directory.",
            )
        )

        status = self._status(gates)
        summary = self._summary(status, gates, installer_distributable)
        return DistributionSnapshot(
            distribution_id=self._distribution_id(source),
            version=self.version,
            release_channel=self.release_channel,
            captured_at=self._now(),
            status=status,
            summary=summary,
            source_candidate=source if source.exists() else None,
            installer_available=installer_available,
            installer_distributable=installer_distributable,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )

    def build_distribution(
        self,
        candidate_dir: Path | None = None,
        *,
        require_installer: bool = False,
    ) -> DistributionSnapshot:
        initial = self.snapshot(candidate_dir)
        if initial.blocker_count:
            raise RuntimeError(initial.summary)
        if require_installer and not initial.installer_distributable:
            raise RuntimeError("A real compiled Windows installer is required for this distribution bundle.")
        if initial.source_candidate is None:
            raise FileNotFoundError("Release-candidate directory is missing.")

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        bundle = self.root / f"S-Talking-{self.version}-distribution-{stamp}"
        bundle.mkdir(parents=True, exist_ok=False)

        package = self._compiled_portable_path(self._build_result())
        package_ok, package_detail = self._audit_compiled_portable(package)
        if package is None or not package.exists() or not package_ok:
            raise FileNotFoundError(f"Compiled portable package is unavailable: {package_detail}")

        copied: list[DistributionArtifact] = []
        copied.append(self._copy_artifact("portable_package", package, bundle))
        for name, role, target_name in (
            (self.release_candidate_service.MANIFEST_NAME, "release_candidate_manifest", None),
            (self.release_candidate_service.CHECKSUM_NAME, "release_candidate_checksums", "release-candidate-SHA256SUMS.txt"),
            (self.release_candidate_service.NOTES_NAME, "release_notes", None),
        ):
            source_path = initial.source_candidate / name
            if source_path.exists():
                copied.append(self._copy_artifact(role, source_path, bundle, target_name=target_name))

        installer_result = self._installer_result()
        installer_path = self._installer_path(installer_result)
        if self._is_real_installer(installer_path):
            copied.append(self._copy_artifact("windows_installer", installer_path, bundle))

        upgrade = bundle / self.UPGRADE_PLAN_NAME
        upgrade.write_text(json.dumps(self._upgrade_plan(), indent=2, ensure_ascii=False), encoding="utf-8")
        rollback = bundle / self.ROLLBACK_NAME
        rollback.write_text(self._rollback_text(), encoding="utf-8")
        install = bundle / self.INSTALL_NAME
        install.write_text(self._install_text(bool(installer_path and self._is_real_installer(installer_path))), encoding="utf-8")
        copied.extend(
            (
                self._artifact("upgrade_plan", upgrade),
                self._artifact("rollback_guide", rollback),
                self._artifact("installation_guide", install),
            )
        )

        manifest = bundle / self.MANIFEST_NAME
        payload = {
            "schema_version": 1,
            "distribution_id": initial.distribution_id,
            "version": self.version,
            "release_channel": self.release_channel,
            "database_schema": self.schema_version,
            "generated_at": self._now(),
            "source_candidate": str(initial.source_candidate),
            "installer_included": any(item.role == "windows_installer" for item in copied),
            "artifacts": [item.to_dict() | {"path": item.path.name} for item in copied],
        }
        manifest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        manifest_artifact = self._artifact("distribution_manifest", manifest)

        checksums = bundle / self.CHECKSUM_NAME
        checksum_artifacts = copied + [manifest_artifact]
        checksums.write_text(
            "".join(f"{item.sha256}  {item.path.name}\n" for item in checksum_artifacts),
            encoding="ascii",
        )
        checksum_artifact = self._artifact("distribution_checksums", checksums)
        final_artifacts = tuple(checksum_artifacts + [checksum_artifact])

        verified, detail = self.verify_distribution_manifest(manifest)
        if not verified:
            raise RuntimeError(detail)

        final = replace(
            initial,
            bundle_dir=bundle,
            status="ready" if initial.installer_distributable else "ready_with_warnings",
            summary=(
                "Portable package and Windows installer are staged and verified for distribution."
                if initial.installer_distributable
                else "Portable distribution is verified; compiled Windows installer remains optional and unavailable."
            ),
            artifacts=final_artifacts,
        )
        result = bundle / self.RESULT_NAME
        result.write_text(json.dumps(final.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        self._publish_latest(bundle)
        return final

    def verify_distribution_manifest(self, manifest_path: Path) -> tuple[bool, str]:
        path = Path(manifest_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            artifacts = payload.get("artifacts", [])
            if not isinstance(artifacts, list) or not artifacts:
                return False, "Distribution manifest contains no artifacts."
            for item in artifacts:
                artifact = path.parent / Path(str(item["path"])).name
                if not artifact.exists():
                    return False, f"Distribution artifact is missing: {artifact.name}"
                if self._sha256(artifact) != str(item["sha256"]):
                    return False, f"SHA-256 mismatch for distribution artifact: {artifact.name}"
            return True, f"Distribution manifest verified with {len(artifacts)} artifact(s)."
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return False, f"Distribution verification failed: {exc}"

    def export_snapshot(self, snapshot: DistributionSnapshot | None = None) -> Path:
        current = snapshot or self.snapshot()
        folder = self.runtime.artifacts_dir / "distribution-readiness"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "distribution-readiness.json"
        path.write_text(json.dumps(current.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def _candidate_package(self, manifest_path: Path) -> Path | None:
        try:
            payload = json.loads(Path(manifest_path).read_text(encoding="utf-8-sig"))
            package_data = payload["package"]
            local = Path(manifest_path).parent / Path(str(package_data["path"])).name
            if local.exists():
                return local
            original = Path(str(package_data["path"]))
            return original if original.exists() else local
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def _build_result(self) -> dict[str, Any]:
        path = self.runtime.artifacts_dir / "package" / "build-result.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _compiled_portable_path(payload: dict[str, Any]) -> Path | None:
        raw = payload.get("zip_path")
        return Path(str(raw)) if raw else None

    def _audit_compiled_portable(self, path: Path | None) -> tuple[bool, str]:
        if path is None or not path.exists():
            return False, "Compiled portable ZIP is missing."
        if path.name != f"S-Talking-{self.version}-portable.zip":
            return False, f"Portable ZIP filename does not match version {self.version}."
        try:
            with zipfile.ZipFile(path) as archive:
                names = [name.replace("\\", "/").lstrip("./") for name in archive.namelist() if not name.endswith("/")]
                normalized = {name.casefold(): name for name in names}
                required = {"s-talking.exe", "portable.mode", "run.cmd"}
                missing = sorted(required - set(normalized))
                if missing:
                    return False, "Portable ZIP is missing: " + ", ".join(missing)
                for name in names:
                    parts = Path(name).parts
                    if name.startswith("/") or ".." in parts:
                        return False, f"Unsafe portable ZIP path: {name}"
                    folded = {part.casefold() for part in parts}
                    if folded & {
                        "s-talking-data",
                        "credentials",
                        "logs",
                        "reports",
                        "output",
                        "data",
                    }:
                        return False, f"Portable ZIP contains writable user data: {name}"
                    if Path(name).name.casefold() in {
                        "settings.json",
                        "api-profiles.json",
                        "workspace-profiles.json",
                    }:
                        return False, f"Portable ZIP contains local settings: {name}"
                with archive.open(normalized["s-talking.exe"]) as executable:
                    if executable.read(2) != b"MZ":
                        return False, "S-Talking.exe in the portable ZIP is not a Windows PE executable."
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            return False, f"Portable ZIP audit failed: {exc}"
        return True, f"Compiled portable ZIP verified: {self._sha256(path)[:16]}…"

    def _installer_result(self) -> dict[str, Any]:
        path = self.runtime.artifacts_dir / "package" / "installer-result.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _installer_path(payload: dict[str, Any]) -> Path | None:
        raw = payload.get("installer_path") or payload.get("artifact_path")
        return Path(str(raw)) if raw else None

    @staticmethod
    def _is_real_installer(path: Path | None) -> bool:
        if path is None or not path.exists() or path.suffix.casefold() != ".exe":
            return False
        try:
            return path.stat().st_size >= 4096 and path.read_bytes()[:2] == b"MZ"
        except OSError:
            return False

    def _installer_detail(self, payload: dict[str, Any], path: Path | None) -> str:
        if self._is_real_installer(path):
            unsigned = bool(payload.get("unsigned", True))
            return f"Compiled installer verified ({'unsigned' if unsigned else 'signed'}): {path.name}"
        if payload.get("artifact_kind") == "placeholder" or payload.get("available") is False:
            return "Inno Setup was unavailable; no fake .exe is treated as a distributable installer."
        if path and path.exists():
            return f"Installer artifact is not a valid Windows PE executable: {path.name}"
        return "No compiled installer is available; portable distribution remains supported."

    def _installer_contract(self) -> tuple[bool, str]:
        path = self.runtime.app_root / "packaging" / "windows" / "S-Talking.iss"
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            return False, f"Installer definition is unreadable: {exc}"
        required = (
            f"AppId={{{{{self.STABLE_APP_ID}}}",
            "DefaultDirName={localappdata}\\Programs\\S Talking",
            "PrivilegesRequired=lowest",
            "CloseApplications=yes",
            "RestartApplications=no",
            "UsePreviousAppDir=yes",
        )
        missing = [item for item in required if item not in text]
        if "[UninstallDelete]" in text:
            missing.append("non-destructive uninstall contract")
        if missing:
            return False, "Missing or unsafe installer contract: " + ", ".join(missing)
        return True, "Stable AppId, per-user path, upgrade reuse, app shutdown, and non-destructive uninstall are configured."

    def _per_user_install_contract(self) -> tuple[bool, str]:
        path = self.runtime.app_root / "packaging" / "windows" / "S-Talking.iss"
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            return False, str(exc)
        ok = (
            "DefaultDirName={localappdata}\\Programs\\S Talking" in text
            and "PrivilegesRequired=lowest" in text
            and "DefaultDirName={autopf}" not in text
        )
        return (
            ok,
            "Installer writes program files per-user; application settings and databases remain under %LOCALAPPDATA%\\S-Talking."
            if ok
            else "Installer requests an unsafe or inconsistent installation scope.",
        )

    def _upgrade_contract(self) -> tuple[bool, str]:
        path = self.runtime.app_root / "packaging" / "windows" / "S-Talking.iss"
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            return False, str(exc)
        checks = (
            f"AppId={{{{{self.STABLE_APP_ID}}}" in text,
            "UsePreviousAppDir=yes" in text,
            "CloseApplications=yes" in text,
            "RestartApplications=no" in text,
            "[UninstallDelete]" not in text,
        )
        ok = all(checks)
        return (
            ok,
            "Upgrade keeps the stable product identity, reuses the install directory, closes the running app, and preserves user data."
            if ok
            else "One or more in-place upgrade safeguards are missing.",
        )

    def _upgrade_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "application_version": self.version,
            "database_schema": self.schema_version,
            "install_scope": "per-user",
            "install_root": "%LOCALAPPDATA%\\Programs\\S Talking",
            "data_root": "%LOCALAPPDATA%\\S-Talking",
            "portable_data_root": "<portable-dir>\\S-Talking-Data",
            "preserved_paths": [
                "data",
                "settings",
                "credentials",
                "logs",
                "cache",
                "output",
                "reports",
                "diagnostics",
            ],
            "pre_upgrade": [
                "Close S Talking and wait for audio playback/generation to stop.",
                "Back up %LOCALAPPDATA%\\S-Talking before changing installed binaries.",
                "Verify the installer or portable ZIP against SHA256SUMS.txt.",
            ],
            "upgrade": [
                "Run the installer as the current user or replace only portable program files.",
                "Do not copy portable.mode into an installed build.",
                "Launch once and allow database migrations to complete.",
            ],
            "validation": [
                "Confirm version and release channel in About.",
                "Open the existing project and verify provider profiles, queue state, and output paths.",
                "Run a mock-provider preflight and generate one test file.",
            ],
            "rollback": [
                "Close S Talking.",
                "Restore the previous program package.",
                "Restore the application-data backup only when schema compatibility requires it.",
            ],
        }

    def _rollback_text(self) -> str:
        return (
            f"# S-Talking {self.version} rollback\n\n"
            "1. Close S Talking and confirm no `S-Talking.exe` process remains.\n"
            "2. Preserve the failed installation and `%LOCALAPPDATA%\\S-Talking\\logs` for diagnostics.\n"
            "3. Reinstall the previous verified package or restore the previous portable directory.\n"
            "4. Restore the pre-upgrade `%LOCALAPPDATA%\\S-Talking` backup only if the previous build cannot open the current schema.\n"
            "5. Launch with the mock provider, open an existing project, and verify one output before reconnecting paid providers.\n\n"
            "Credentials, settings, projects, databases, reports, and generated audio are user data and must not be removed by uninstall.\n"
        )

    def _install_text(self, installer_included: bool) -> str:
        installer = (
            f"Run `S-Talking-{self.version}-setup.exe` as the current user. Administrator elevation is not required."
            if installer_included
            else "No compiled installer is included. Extract the portable ZIP to a writable folder and run `RUN.cmd`."
        )
        return (
            f"# Install S-Talking {self.version}\n\n"
            f"{installer}\n\n"
            "Verify every artifact against `SHA256SUMS.txt` before use. Installed data is stored under "
            "`%LOCALAPPDATA%\\S-Talking`; portable data is stored in `S-Talking-Data` beside the executable.\n"
        )

    def _copy_artifact(
        self,
        role: str,
        source: Path,
        destination: Path,
        *,
        target_name: str | None = None,
    ) -> DistributionArtifact:
        target = destination / (target_name or source.name)
        shutil.copy2(source, target)
        return self._artifact(role, target)

    def _artifact(
        self,
        role: str,
        path: Path,
        status: str = "verified",
        detail: str = "",
    ) -> DistributionArtifact:
        target = Path(path)
        return DistributionArtifact(
            role=role,
            path=target,
            size_bytes=target.stat().st_size if target.exists() else 0,
            sha256=self._sha256(target) if target.exists() else "",
            status=status,
            detail=detail,
        )

    @staticmethod
    def _gate(
        code: str,
        label: str,
        passed: bool,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> DistributionGate:
        return DistributionGate(
            code=code,
            label=label,
            status="passed" if passed else "failed",
            severity=severity,
            detail=detail,
            remediation=remediation,
        )

    @staticmethod
    def _status(gates: list[DistributionGate]) -> str:
        if any(item.severity == "blocker" and not item.passed for item in gates):
            return "blocked"
        if any(not item.passed for item in gates):
            return "ready_with_warnings"
        return "ready"

    @staticmethod
    def _summary(status: str, gates: list[DistributionGate], installer: bool) -> str:
        blockers = sum(item.severity == "blocker" and not item.passed for item in gates)
        warnings = sum(item.severity == "warning" and not item.passed for item in gates)
        if status == "ready":
            return "Installer and portable channels are verified for distribution."
        if status == "ready_with_warnings":
            channel = "Portable channel is ready" if not installer else "Distribution is ready"
            return f"{channel} with {warnings} warning(s)."
        return f"Distribution is blocked by {blockers} mandatory gate(s)."

    def _distribution_id(self, source: Path) -> str:
        seed = f"{self.version}|{self.release_channel}|{source}|{self.schema_version}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:16]

    def _publish_latest(self, bundle: Path) -> None:
        latest = self.latest_distribution_dir()
        if latest.exists():
            shutil.rmtree(latest)
        shutil.copytree(bundle, latest)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
