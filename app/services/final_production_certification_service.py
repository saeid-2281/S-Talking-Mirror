from __future__ import annotations

import hashlib
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.final_production_certification import (
    FinalProductionCertificationGate,
    FinalProductionCertificationSnapshot,
    FinalProductionCertificationSource,
)
from app.release import SCHEMA_VERSION
from app.services.evidence_integrity import EvidenceIntegrityMixin
from app.services.final_release_service import FinalReleaseService
from app.services.operational_persistence_service import OperationalPersistenceService
from app.services.operational_readiness_service import OperationalReadinessCertificationService
from app.services.release_lifecycle_validation_service import ReleaseLifecycleValidationService


class FinalProductionCertificationService(EvidenceIntegrityMixin):
    """Bind final 1.x production certification to a clean, tested source commit."""

    SCHEMA_VERSION = 1
    DEFAULT_MINIMUM_TEST_COUNT = 1100
    _COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
    _STABLE_1X_RE = re.compile(r"^1\.\d+\.\d+$")
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|cookie|private[_-]?key)"
    )
    _ABSOLUTE_PATH_RE = re.compile(
        r"(?i)(?:[A-Z]:[\\/]|/home/|/Users/|/tmp/|/var/tmp/|\\\\[^\\]+\\[^\\]+)"
    )
    _LOCAL_ONLY = {"api-profiles.json", "workspace-profiles.json"}

    def __init__(
        self,
        runtime: RuntimeConfig,
        final_release_service: FinalReleaseService,
        release_lifecycle_validation_service: ReleaseLifecycleValidationService,
        operational_readiness_service: OperationalReadinessCertificationService,
        operational_persistence_service: OperationalPersistenceService,
        *,
        version: str | None = None,
        channel: str | None = None,
        schema_version: int | None = None,
        now: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.final_release_service = final_release_service
        self.release_lifecycle_validation_service = release_lifecycle_validation_service
        self.operational_readiness_service = operational_readiness_service
        self.operational_persistence_service = operational_persistence_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.schema_version = int(schema_version if schema_version is not None else SCHEMA_VERSION)
        self.root = runtime.artifacts_dir / "final-production-certification"
        self.snapshots_dir = self.root / "snapshots"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._command_runner = command_runner or subprocess.run
        for folder in (
            self.root,
            self.snapshots_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            folder.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "automatic_publish": False,
            "automatic_tag": False,
            "automatic_install": False,
            "automatic_update": False,
            "automatic_restart": False,
            "automatic_restore": False,
            "automatic_rollback": False,
            "source_data_mutated": False,
            "private_data_included": False,
            "human_acknowledgement_required": True,
        }

    def default_source_paths(self) -> dict[str, Path]:
        return {
            "release_check": self.runtime.artifacts_dir / "release-check" / "latest" / "result.json",
            "final_manifest": self.final_release_service.latest_release_dir() / "final-release-manifest.json",
            "stable_feed": self.runtime.artifacts_dir / "update-channel" / "stable" / "latest.json",
            "release_lifecycle": self.release_lifecycle_validation_service.root
            / "latest-release-lifecycle-validation.json",
            "operational_readiness": self.operational_readiness_service.root
            / "latest-operational-readiness-attestation.json",
        }

    def assess(
        self,
        *,
        source_commit: str = "",
        minimum_test_count: int | None = None,
        source_paths: Mapping[str, Path] | None = None,
    ) -> FinalProductionCertificationSnapshot:
        commit = self._resolve_commit(source_commit)
        minimum_tests = max(
            1,
            int(
                self.DEFAULT_MINIMUM_TEST_COUNT
                if minimum_test_count is None
                else minimum_test_count
            ),
        )
        paths = self.default_source_paths()
        if source_paths:
            paths.update({str(role): Path(path) for role, path in source_paths.items()})

        gates: list[FinalProductionCertificationGate] = []
        sources: list[FinalProductionCertificationSource] = []

        identity_ok = (
            self._STABLE_1X_RE.fullmatch(self.version) is not None
            and self.channel == "stable"
            and self.schema_version == SCHEMA_VERSION
        )
        gates.append(
            self._gate(
                "stable_identity",
                "Stable S-Talking 1.x identity",
                "pass" if identity_ok else "block",
                "blocker",
                (
                    f"Application identity is {self.version}/{self.channel} with database schema {self.schema_version}."
                    if identity_ok
                    else "Final certification requires stable S-Talking 1.x and the current database schema contract."
                ),
                "Use the stable 1.x release identity and current schema before certification.",
            )
        )

        commit_ok = self._COMMIT_RE.fullmatch(commit) is not None
        clean, clean_detail = self._source_tree_clean()
        gates.append(
            self._gate(
                "source_identity",
                "Immutable clean source commit",
                "pass" if commit_ok and clean else "block",
                "blocker",
                (
                    f"Certification is bound to clean commit {commit}. {clean_detail}"
                    if commit_ok and clean
                    else f"Source identity is not certification-ready. {clean_detail}"
                ),
                "Commit reviewed source changes and keep only approved local-only profile overrides.",
            )
        )

        release_check_payload = self._read_json(paths["release_check"])
        release_ok, release_detail, observed_tests = self._verify_release_check(
            release_check_payload,
            commit=commit,
            minimum_test_count=minimum_tests,
        )
        gates.append(
            self._gate(
                "release_check",
                "Post-commit release check",
                "pass" if release_ok else "block",
                "blocker",
                release_detail,
                "Run scripts/release-check.ps1 from the committed clean Phase 88 source.",
            )
        )
        if release_check_payload is not None:
            self._append_source(
                sources,
                "release_check",
                "Post-commit release check",
                paths["release_check"],
                required=True,
            )

        self._append_verified_artifact_gate(
            gates,
            sources,
            code="final_manifest",
            label="Final release manifest",
            path=paths["final_manifest"],
            verifier=self.final_release_service.verify_final_manifest,
            required=False,
            remediation="Rebuild the verified final release bundle if release packaging changed.",
        )
        self._append_verified_artifact_gate(
            gates,
            sources,
            code="stable_feed",
            label="Stable update feed",
            path=paths["stable_feed"],
            verifier=self.final_release_service.verify_update_feed,
            required=False,
            remediation="Regenerate the stable update feed if release delivery changed.",
        )
        self._append_verified_artifact_gate(
            gates,
            sources,
            code="release_lifecycle",
            label="Installer / update / recovery lifecycle evidence",
            path=paths["release_lifecycle"],
            verifier=self.release_lifecycle_validation_service.verify_snapshot,
            required=False,
            remediation="Export a fresh Phase 87 lifecycle snapshot when runtime release evidence is available.",
        )
        self._append_verified_artifact_gate(
            gates,
            sources,
            code="operational_readiness",
            label="Operational readiness attestation",
            path=paths["operational_readiness"],
            verifier=self.operational_readiness_service.verify_attestation,
            required=False,
            remediation="Create a fresh human-acknowledged operational readiness attestation if operational evidence changed.",
        )

        persistence_ok, persistence_detail = self.operational_persistence_service.verify_database()
        gates.append(
            self._gate(
                "persistence_integrity",
                "Operational persistence integrity",
                "pass" if persistence_ok else "block",
                "blocker",
                persistence_detail,
                "Repair the operational persistence database before final certification.",
            )
        )
        gates.append(
            self._gate(
                "manual_control",
                "Human-controlled production boundary",
                "pass",
                "blocker",
                "Certification writes evidence only; publish, tag, install, update, restart, restore and rollback remain explicit operator actions.",
            )
        )

        blockers = sum(item.status == "block" for item in gates)
        warnings = sum(item.status == "warn" for item in gates)
        status = "blocked" if blockers else "certified_with_warnings" if warnings else "certified"
        summary = (
            f"Final S-Talking 1.x certification is blocked by {blockers} gate(s)."
            if blockers
            else f"Final S-Talking 1.x certification is eligible with {warnings} supplemental evidence warning(s)."
            if warnings
            else "Final S-Talking 1.x source, release and operational integrity gates are certified."
        )
        certification_id = hashlib.sha256(
            f"{self.version}|{self.channel}|{self.schema_version}|{commit}|{self._now().date().isoformat()}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        return FinalProductionCertificationSnapshot(
            certification_id=f"s-talking-1x-{certification_id}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            schema_version=self.schema_version,
            source_commit=commit,
            status=status,
            summary=summary,
            minimum_test_count=minimum_tests,
            observed_test_count=observed_tests,
            gates=tuple(gates),
            sources=tuple(sources),
        )

    def export_snapshot(self, snapshot: FinalProductionCertificationSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["document_schema_version"] = self.SCHEMA_VERSION
        payload["safety_contract"] = self._safety_contract()
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.certification_id}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-final-production-snapshot.json", payload)
        return path

    def create_certification(
        self,
        snapshot: FinalProductionCertificationSnapshot,
        *,
        reviewer: str,
        statement: str,
        acknowledge: bool = False,
    ) -> dict[str, object]:
        if snapshot.blocker_count:
            return {
                "status": "blocked",
                "detail": "Final certification cannot be written while blocker gates remain.",
                "path": "",
            }
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "Explicit human acknowledgement is required before writing final certification.",
                "path": "",
            }
        reviewer_text = str(reviewer or "").strip()
        statement_text = str(statement or "").strip()
        if not reviewer_text or not statement_text:
            return {
                "status": "blocked",
                "detail": "Reviewer and final certification statement are required.",
                "path": "",
            }
        if self._contains_private_text(reviewer_text) or self._contains_private_text(statement_text):
            return {
                "status": "blocked",
                "detail": "Reviewer or statement contains private material or a local path.",
                "path": "",
            }

        snapshot_path = self.export_snapshot(snapshot)
        ok, detail = self.verify_snapshot(snapshot_path)
        if not ok:
            return {"status": "blocked", "detail": detail, "path": ""}

        attestation: dict[str, object] = {
            "document_schema_version": self.SCHEMA_VERSION,
            "certification_id": snapshot.certification_id,
            "generated_at": self._now_iso(),
            "version": snapshot.version,
            "channel": snapshot.channel,
            "database_schema_version": snapshot.schema_version,
            "source_commit": snapshot.source_commit,
            "status": snapshot.status,
            "reviewer": reviewer_text,
            "statement": statement_text,
            "human_acknowledged": True,
            "blocker_count": snapshot.blocker_count,
            "warning_count": snapshot.warning_count,
            "observed_test_count": snapshot.observed_test_count,
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "sources": [item.to_dict() for item in snapshot.sources],
            "safety_contract": self._safety_contract(),
        }
        attestation["attestation_sha256"] = self._payload_digest(attestation)
        attestation_path = self.attestations_dir / f"{snapshot.certification_id}.json"
        self._write_json(attestation_path, attestation)
        self._write_json(self.root / "latest-final-production-attestation.json", attestation)

        pack_path, receipt_path = self._build_audit_pack(snapshot_path, attestation_path)
        ok, detail = self.verify_audit_pack(pack_path, receipt_path)
        if not ok:
            for path in (attestation_path, pack_path, receipt_path):
                path.unlink(missing_ok=True)
            return {"status": "blocked", "detail": detail, "path": ""}
        return {
            "status": snapshot.status,
            "detail": "Final S-Talking 1.x certification and audit pack verified. No production action was executed.",
            "path": str(attestation_path),
            "snapshot_path": str(snapshot_path),
            "audit_pack_path": str(pack_path),
            "receipt_path": str(receipt_path),
        }

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Final production certification snapshot is unreadable."
        expected = str(payload.get("snapshot_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("snapshot_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Final production certification snapshot SHA-256 changed."
        contract = payload.get("safety_contract")
        if not isinstance(contract, dict) or not self._verify_safety_contract(contract):
            return False, "Final production certification safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Final production certification snapshot contains private material."
        if str(payload.get("status") or "") not in {
            "certified",
            "certified_with_warnings",
            "blocked",
        }:
            return False, "Final production certification snapshot status is invalid."
        sources = payload.get("sources")
        if not isinstance(sources, list):
            return False, "Final production certification source custody is invalid."
        for item in sources:
            if not isinstance(item, Mapping):
                return False, "Final production certification source record is invalid."
            ok, detail = self._verify_source_record(item)
            if not ok:
                return False, detail
        return True, "Final production certification snapshot and source custody verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Final production certification attestation is unreadable."
        expected = str(payload.get("attestation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("attestation_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Final production certification attestation SHA-256 changed."
        contract = payload.get("safety_contract")
        if not isinstance(contract, dict) or not self._verify_safety_contract(contract):
            return False, "Final production certification attestation safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Final production certification attestation contains private material."
        if payload.get("human_acknowledged") is not True:
            return False, "Final production certification lacks human acknowledgement."
        if int(payload.get("blocker_count") or 0) != 0:
            return False, "Final production certification attestation contains blockers."
        if str(payload.get("status") or "") not in {"certified", "certified_with_warnings"}:
            return False, "Final production certification attestation is not eligible."
        snapshot = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot.is_file() or self._sha256(snapshot) != str(payload.get("snapshot_sha256") or ""):
            return False, "Final production certification snapshot custody changed."
        ok, detail = self.verify_snapshot(snapshot)
        if not ok:
            return False, detail
        return True, "Final S-Talking 1.x production attestation and source custody verified."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "Final production audit receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Final production audit receipt SHA-256 changed."
        contract = receipt.get("safety_contract")
        if not isinstance(contract, dict) or not self._verify_safety_contract(contract):
            return False, "Final production audit receipt safety contract changed."
        if self._contains_private_payload(receipt):
            return False, "Final production audit receipt contains private material."
        if not pack.is_file():
            return False, "Final production audit pack is missing."
        if pack.name != str(receipt.get("pack_filename") or ""):
            return False, "Final production audit pack filename changed."
        if pack.stat().st_size != int(receipt.get("pack_size_bytes") or -1):
            return False, "Final production audit pack size changed."
        if self._sha256(pack) != str(receipt.get("pack_sha256") or ""):
            return False, "Final production audit pack SHA-256 changed."
        try:
            with zipfile.ZipFile(pack, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Final production audit pack contains an unsafe path."
                if set(names) != {"snapshot.json", "attestation.json"}:
                    return False, "Final production audit pack contents are incomplete."
        except (OSError, zipfile.BadZipFile):
            return False, "Final production audit pack is unreadable."
        return True, "Final production certification audit pack and receipt verified."

    def _append_verified_artifact_gate(
        self,
        gates: list[FinalProductionCertificationGate],
        sources: list[FinalProductionCertificationSource],
        *,
        code: str,
        label: str,
        path: Path,
        verifier: Callable[[Path], tuple[bool, str]],
        required: bool,
        remediation: str,
    ) -> None:
        target = Path(path)
        if not target.is_file():
            gates.append(
                self._gate(
                    code,
                    label,
                    "block" if required else "pass",
                    "blocker" if required else "supplemental",
                    (
                        f"Required {label.casefold()} is missing."
                        if required
                        else f"Supplemental {label.casefold()} is not present; the post-commit full release check remains the authoritative Phase 88 source gate."
                    ),
                    remediation if required else "",
                )
            )
            return
        ok, detail = verifier(target)
        gates.append(
            self._gate(
                code,
                label,
                "pass" if ok else "block" if required else "warn",
                "blocker" if required else "warning",
                detail,
                remediation if not ok else "",
            )
        )
        self._append_source(sources, code, label, target, required=required)

    def _verify_release_check(
        self,
        payload: dict[str, object] | None,
        *,
        commit: str,
        minimum_test_count: int,
    ) -> tuple[bool, str, int]:
        if not isinstance(payload, dict):
            return False, "Post-commit release-check result is missing or unreadable.", 0
        steps = payload.get("steps")
        pytest_step = steps.get("pytest") if isinstance(steps, dict) else None
        passed = int(pytest_step.get("passed") or 0) if isinstance(pytest_step, dict) else 0
        success = bool(payload.get("success")) and int(payload.get("exit_code") or 0) == 0
        identity_ok = (
            str(payload.get("application_version") or "") == self.version
            and str(payload.get("release_channel") or "") == self.channel
        )
        provenance_ok = (
            bool(commit)
            and str(payload.get("source_commit") or "") == commit
            and payload.get("working_tree_clean") is True
        )
        count_ok = passed >= minimum_test_count
        ok = success and identity_ok and provenance_ok and count_ok
        detail = (
            f"Post-commit release check passed {passed} tests on clean commit {commit[:12]} for {self.version}/{self.channel}."
            if ok
            else (
                f"Release check reports success={success}, tests={passed}/{minimum_test_count}, "
                f"identity_match={identity_ok}, commit_match={provenance_ok}."
            )
        )
        return ok, detail, passed

    def _append_source(
        self,
        sources: list[FinalProductionCertificationSource],
        role: str,
        label: str,
        path: Path,
        *,
        required: bool,
    ) -> None:
        target = Path(path)
        if not target.is_file():
            return
        try:
            relative = target.resolve().relative_to(self.runtime.app_root.resolve())
        except ValueError:
            return
        relative_text = relative.as_posix()
        if not self._safe_archive_name(relative_text):
            return
        sources.append(
            FinalProductionCertificationSource(
                role=role,
                label=label,
                relative_path=relative_text,
                sha256=self._sha256(target),
                required=required,
            )
        )

    def _verify_source_record(self, item: Mapping[str, object]) -> tuple[bool, str]:
        relative = str(item.get("relative_path") or "")
        if not self._safe_archive_name(relative):
            return False, "Final production source path is unsafe."
        source = self.runtime.app_root / PurePosixPath(relative)
        try:
            source.resolve().relative_to(self.runtime.app_root.resolve())
        except ValueError:
            return False, "Final production source path escapes the application root."
        if not source.is_file():
            return False, f"Final production source is missing: {Path(relative).name}"
        if self._sha256(source) != str(item.get("sha256") or ""):
            return False, f"Final production source custody changed: {source.name}"
        return True, "Source custody verified."

    def _build_audit_pack(self, snapshot_path: Path, attestation_path: Path) -> tuple[Path, Path]:
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        pack = self.audit_packs_dir / f"final-production-certification-{stamp}.zip"
        with zipfile.ZipFile(pack, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, "snapshot.json")
            archive.write(attestation_path, "attestation.json")
        receipt: dict[str, object] = {
            "document_schema_version": self.SCHEMA_VERSION,
            "generated_at": self._now_iso(),
            "pack_filename": pack.name,
            "pack_size_bytes": pack.stat().st_size,
            "pack_sha256": self._sha256(pack),
            "safety_contract": self._safety_contract(),
        }
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"final-production-certification-{stamp}.json"
        self._write_json(receipt_path, receipt)
        self._write_json(self.root / "latest-final-production-receipt.json", receipt)
        return pack, receipt_path

    def _source_tree_clean(self) -> tuple[bool, str]:
        try:
            completed = self._command_runner(
                ["git", "status", "--porcelain"],
                cwd=self.runtime.app_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, TypeError) as exc:
            return False, f"Git status could not be evaluated: {exc}"
        if int(getattr(completed, "returncode", 1)) != 0:
            return False, "Git status could not be evaluated."
        source_changes: list[str] = []
        for line in str(getattr(completed, "stdout", "") or "").splitlines():
            if len(line) < 4:
                continue
            path = line[3:].strip().replace("\\", "/")
            if " -> " in path:
                path = path.split(" -> ")[-1].strip()
            if path not in self._LOCAL_ONLY:
                source_changes.append(path)
        if source_changes:
            return False, f"Source working tree has {len(source_changes)} non-local change(s)."
        return True, "Only approved local-only profile overrides may remain modified."

    def _resolve_commit(self, explicit: str) -> str:
        value = str(explicit or "").strip()
        if value:
            return value
        try:
            completed = self._command_runner(
                ["git", "rev-parse", "HEAD"],
                cwd=self.runtime.app_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, TypeError):
            return ""
        if int(getattr(completed, "returncode", 1)) != 0:
            return ""
        return str(getattr(completed, "stdout", "") or "").strip()

    def _gate(
        self,
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        action: str = "",
    ) -> FinalProductionCertificationGate:
        return FinalProductionCertificationGate(
            code=code,
            label=label,
            status=status,
            severity=severity,
            detail=str(detail or ""),
            action=str(action or ""),
        )
