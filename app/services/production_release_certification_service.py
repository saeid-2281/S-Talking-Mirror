from __future__ import annotations

import hashlib
import json
import re
import subprocess
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.production_release import (
    ProductionCertificationGate,
    ProductionCertificationSnapshot,
    ProductionEvidenceArtifact,
)


class ProductionReleaseCertificationService:
    """Aggregate tamper-evident release evidence without publishing anything.

    Production certification is a promotion guard, not a deployment engine. It
    never changes app.release, signs binaries, uploads a feed, installs an update,
    or publishes a Git tag. It only reads structured release evidence and writes
    a privacy-safe attestation or an explicitly acknowledged promotion plan.
    """

    SCHEMA_VERSION = 1
    ATTESTATION_NAME = "production-release-attestation.json"
    PROMOTION_PLAN_NAME = "production-promotion-plan.json"
    REQUIRED_ROLES = (
        "quality_gate",
        "ux_certification",
        "security_snapshot",
        "performance_snapshot",
        "crash_recovery",
        "final_release",
        "update_channel",
        "upgrade_backup",
    )
    _STABLE_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
    _COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
    _SECRET_KEY_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|cookie|private[_-]?key)"
    )
    _TOKEN_RE = re.compile(r"\b(?:sk|xi|pk|rk)[-_][A-Za-z0-9_-]{12,}\b")

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        now: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.root = runtime.artifacts_dir / "production-certification"
        self.attestation_dir = self.root / "attestations"
        self.plan_dir = self.root / "promotion-plans"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._command_runner = command_runner or subprocess.run
        self.root.mkdir(parents=True, exist_ok=True)
        self.attestation_dir.mkdir(parents=True, exist_ok=True)
        self.plan_dir.mkdir(parents=True, exist_ok=True)

    def default_evidence_paths(self) -> dict[str, Path]:
        return {
            "quality_gate": self.runtime.artifacts_dir / "release-check" / "latest" / "result.json",
            "ux_certification": self.runtime.reports_dir / "ux-accessibility-certification" / "latest.json",
            "security_snapshot": self.runtime.artifacts_dir / "security-supply-chain" / "latest-security-snapshot.json",
            "performance_snapshot": self.runtime.artifacts_dir / "performance-stability" / "latest-snapshot.json",
            "crash_recovery": self.runtime.artifacts_dir / "crash-recovery" / "latest-production-snapshot.json",
            "final_release": self.runtime.artifacts_dir / "final-release" / "latest" / "final-release-manifest.json",
            "update_channel": self.runtime.artifacts_dir / "update-channel" / "preview" / "latest.json",
            "upgrade_backup": self.runtime.artifacts_dir / "upgrade-recovery" / "latest" / "upgrade-backup-manifest.json",
        }

    def refresh_runtime_evidence(self) -> tuple[Path, ...]:
        """Refresh privacy-safe runtime evidence without touching user projects."""
        from app.gui.theme import DARK_TOKENS, GRAPHITE_TOKENS, LIGHT_TOKENS
        from app.services.crash_recovery_service import CrashRecoveryService
        from app.services.performance_stability_service import PerformanceStabilityService
        from app.services.secure_credentials import SecureCredentialStore
        from app.services.security_supply_chain_service import SecuritySupplyChainService
        from app.services.ux_accessibility_certification_service import (
            UxAccessibilityCertificationService,
        )

        written: list[Path] = []
        crash_service = CrashRecoveryService(self.runtime)
        crash_path = self.default_evidence_paths()["crash_recovery"]
        self._write_json(crash_path, crash_service.snapshot().to_dict())
        written.append(crash_path)

        performance = PerformanceStabilityService(self.runtime)
        performance.snapshot()
        written.append(performance.latest_snapshot_path)

        credential_store = SecureCredentialStore(self.runtime.settings_path.parent / "credentials")
        security = SecuritySupplyChainService(self.runtime, credential_store)
        security.snapshot()
        written.append(security.latest_snapshot_path)

        ux = UxAccessibilityCertificationService(self.runtime)
        ux_snapshot = ux.certification_snapshot(
            themes={"Dark": DARK_TOKENS, "Graphite": GRAPHITE_TOKENS, "Light": LIGHT_TOKENS},
            active_theme="certification-all-themes",
            preference_summary="High contrast · Text 110% · Enhanced focus · Reduced motion · Status announcements on",
            focus_regions=ux.CORE_REGIONS,
        )
        ux_json, _ = ux.export_snapshot(ux_snapshot)
        written.append(ux_json)
        return tuple(written)

    def certification_snapshot(
        self,
        *,
        target_version: str = "1.0.0",
        source_commit: str = "",
        expected_test_count: int = 841,
        evidence_paths: Mapping[str, Path] | None = None,
        max_evidence_age_days: int = 30,
    ) -> ProductionCertificationSnapshot:
        paths = self.default_evidence_paths()
        if evidence_paths:
            paths.update({str(role): Path(path) for role, path in evidence_paths.items()})
        target = str(target_version or "").strip()
        commit = self._resolve_commit(source_commit)
        expected = max(1, int(expected_test_count))
        gates: list[ProductionCertificationGate] = []
        artifacts: list[ProductionEvidenceArtifact] = []
        observed_tests = 0

        gates.append(
            self._gate(
                "target_version",
                "Stable target version",
                "identity",
                "pass" if self._STABLE_VERSION_RE.fullmatch(target) else "block",
                "blocker",
                (
                    f"Target {target} is a stable semantic version."
                    if self._STABLE_VERSION_RE.fullmatch(target)
                    else "Target version must use X.Y.Z without a prerelease suffix."
                ),
                "Choose the intended stable production version, for example 1.0.0.",
            )
        )
        gates.append(
            self._gate(
                "source_commit",
                "Immutable source commit",
                "identity",
                "pass" if self._COMMIT_RE.fullmatch(commit) else "block",
                "blocker",
                f"Certification is bound to commit {commit}." if commit else "No valid Git commit identity is available.",
                "Run certification from a committed working tree or pass --source-commit.",
            )
        )

        for role in self.REQUIRED_ROLES:
            path = paths.get(role)
            artifact, gate, role_tests = self._inspect_evidence(
                role,
                path,
                expected_test_count=expected,
                max_age_days=max_evidence_age_days,
                source_commit=commit,
            )
            artifacts.append(artifact)
            gates.append(gate)
            observed_tests = max(observed_tests, role_tests)

        blockers = sum(gate.status == "block" for gate in gates)
        warnings = sum(gate.status == "warn" for gate in gates)
        status = "blocked" if blockers else "ready_with_warnings" if warnings else "certified"
        promotion_allowed = blockers == 0
        summary = (
            f"Production promotion is blocked by {blockers} certification gate(s)."
            if blockers
            else f"Production promotion is eligible with {warnings} acknowledged warning(s)."
            if warnings
            else "Production release evidence is complete and certified for explicit promotion."
        )
        certification_id = hashlib.sha256(
            f"{app.__version__}|{target}|{commit}|{self._now().date().isoformat()}".encode("utf-8")
        ).hexdigest()[:20]
        return ProductionCertificationSnapshot(
            certification_id=certification_id,
            generated_at=self._now_iso(),
            source_version=app.__version__,
            target_version=target,
            source_commit=commit,
            release_channel=str(getattr(app, "__release_channel__", "")),
            status=status,
            summary=summary,
            expected_test_count=expected,
            observed_test_count=observed_tests,
            promotion_allowed=promotion_allowed,
            gates=tuple(gates),
            evidence=tuple(artifacts),
        )

    def write_attestation(self, snapshot: ProductionCertificationSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload["attestation_path"] = ""
        payload["automatic_publish"] = False
        payload["automatic_version_change"] = False
        digest = self._payload_digest(payload)
        document = {"payload": payload, "payload_sha256": digest}
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        path = self.attestation_dir / f"production-release-attestation-{stamp}.json"
        self._write_json(path, document)
        latest = self.root / self.ATTESTATION_NAME
        self._write_json(latest, document)
        return path

    def certify_and_write(self, **kwargs: Any) -> ProductionCertificationSnapshot:
        snapshot = self.certification_snapshot(**kwargs)
        path = self.write_attestation(snapshot)
        return replace(snapshot, attestation_path=path)

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        document = self._read_json(Path(path))
        if not isinstance(document, dict):
            return False, "Attestation is unreadable or is not a JSON object."
        payload = document.get("payload")
        expected = str(document.get("payload_sha256") or "")
        if not isinstance(payload, dict) or not expected:
            return False, "Attestation payload or digest is missing."
        actual = self._payload_digest(payload)
        if actual != expected:
            return False, "Attestation payload SHA-256 does not match."
        if int(payload.get("schema_version") or 0) != self.SCHEMA_VERSION:
            return False, "Unsupported production attestation schema."
        if not self._STABLE_VERSION_RE.fullmatch(str(payload.get("target_version") or "")):
            return False, "Attestation target version is not stable semantic versioning."
        if int(payload.get("blocker_count") or 0) > 0 or not bool(payload.get("promotion_allowed")):
            return False, "Attestation is intact but does not authorize promotion."
        return True, "Production release attestation is intact and promotion-eligible."

    def create_promotion_plan(
        self,
        snapshot: ProductionCertificationSnapshot,
        *,
        acknowledge: bool = False,
    ) -> dict[str, object]:
        if not snapshot.promotion_allowed:
            return {
                "status": "blocked",
                "detail": "Promotion plan cannot be created while certification blockers remain.",
                "path": "",
            }
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "No file was changed. Acknowledgement is required to write the promotion plan.",
                "path": "",
            }
        attestation = snapshot.attestation_path or self.write_attestation(snapshot)
        ok, detail = self.verify_attestation(attestation)
        if not ok:
            return {"status": "blocked", "detail": detail, "path": ""}
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "plan_id": uuid.uuid4().hex,
            "created_at": self._now_iso(),
            "source_version": snapshot.source_version,
            "target_version": snapshot.target_version,
            "source_commit": snapshot.source_commit,
            "attestation_file": attestation.name,
            "attestation_sha256": self._sha256(attestation),
            "requires_human_publish": True,
            "automatic_publish": False,
            "automatic_tag": False,
            "automatic_version_change": False,
            "steps": [
                "Review and approve the production attestation.",
                "Update version and release channel in a dedicated reviewed commit.",
                "Rebuild signed artifacts from the approved commit.",
                "Verify package, installer, SBOM and update feed hashes.",
                "Publish to the stable channel with an explicit rollout percentage.",
            ],
        }
        digest = self._payload_digest(payload)
        document = {"payload": payload, "payload_sha256": digest}
        path = self.plan_dir / f"production-promotion-plan-{self._now().strftime('%Y%m%d-%H%M%S')}.json"
        self._write_json(path, document)
        self._write_json(self.root / self.PROMOTION_PLAN_NAME, document)
        return {
            "status": "prepared",
            "detail": "Promotion plan written. No version, tag, artifact or update channel was changed.",
            "path": str(path),
        }

    def export_snapshot(self, snapshot: ProductionCertificationSnapshot) -> tuple[Path, Path]:
        path = snapshot.attestation_path or self.write_attestation(snapshot)
        summary = self.root / "production-certification-summary.json"
        payload = snapshot.to_dict()
        payload["attestation_file"] = path.name
        payload["attestation_sha256"] = self._sha256(path)
        payload["private_data_included"] = False
        self._write_json(summary, payload)
        return path, summary

    def _inspect_evidence(
        self,
        role: str,
        path: Path | None,
        *,
        expected_test_count: int,
        max_age_days: int,
        source_commit: str,
    ) -> tuple[ProductionEvidenceArtifact, ProductionCertificationGate, int]:
        resolved = Path(path) if path else Path(f"missing-{role}.json")
        label = role.replace("_", " ").title()
        if not resolved.exists() or not resolved.is_file():
            artifact = ProductionEvidenceArtifact(role, resolved, "missing", 0, "", detail="Evidence file is missing.")
            return artifact, self._gate(
                f"evidence_{role}", label, "evidence", "block", "blocker",
                f"Required {label.casefold()} evidence is missing.",
                f"Generate and export {label.casefold()} evidence before production promotion.",
            ), 0
        payload = self._read_json(resolved)
        if not isinstance(payload, dict):
            artifact = self._artifact(role, resolved, "invalid", "Evidence is not valid JSON.")
            return artifact, self._gate(
                f"evidence_{role}", label, "evidence", "block", "blocker",
                f"{label} evidence is unreadable or invalid.",
                "Regenerate the evidence from the current clean commit.",
            ), 0
        if self._contains_secret(payload):
            artifact = self._artifact(role, resolved, "private-data", "Potential secret-bearing field detected.")
            return artifact, self._gate(
                f"evidence_{role}", label, "privacy", "block", "blocker",
                f"{label} evidence contains a secret-bearing field or token-like value.",
                "Regenerate privacy-safe structured evidence; never include credentials or project content.",
            ), 0

        passed, warning, detail, tests = self._evaluate_role(
            role, payload, expected_test_count, source_commit
        )
        captured_at = self._captured_at(payload)
        stale = self._is_stale(captured_at, max_age_days)
        status = "block" if not passed else "warn" if warning or stale else "pass"
        severity = "blocker" if not passed else "warning"
        if stale:
            detail = f"{detail} Evidence is older than {max_age_days} day(s)."
        artifact_status = "verified" if status == "pass" else "attention" if status == "warn" else "failed"
        artifact = self._artifact(role, resolved, artifact_status, detail, captured_at=captured_at)
        remediation = (
            "Regenerate this evidence from the exact commit being promoted."
            if stale
            else "Resolve the reported gate and regenerate its structured evidence."
            if not passed
            else "Review and explicitly acknowledge this warning before promotion."
            if warning
            else ""
        )
        return artifact, self._gate(
            f"evidence_{role}", label, "evidence", status, severity, detail, remediation
        ), tests

    def _evaluate_role(
        self,
        role: str,
        payload: Mapping[str, Any],
        expected: int,
        source_commit: str,
    ) -> tuple[bool, bool, str, int]:
        if role == "quality_gate":
            steps = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
            pytest_step = steps.get("pytest") if isinstance(steps, dict) and isinstance(steps.get("pytest"), dict) else {}
            passed_count = int((pytest_step or {}).get("passed") or 0)
            success = bool(payload.get("success")) and int(payload.get("exit_code") or 0) == 0
            count_ok = passed_count >= expected
            evidence_commit = str(payload.get("source_commit") or "").strip()
            clean = payload.get("working_tree_clean") is True
            provenance_ok = bool(evidence_commit) and evidence_commit == source_commit and clean
            passed = success and count_ok and provenance_ok
            detail = (
                f"Quality gate passed with {passed_count} test(s) on clean commit {evidence_commit[:12]}."
                if passed
                else (
                    f"Quality gate evidence reports success={success}, {passed_count}/{expected} tests, "
                    f"commit_match={evidence_commit == source_commit}, clean={clean}."
                )
            )
            return passed, False, detail, passed_count
        if role == "ux_certification":
            blockers = int(payload.get("blocker_count") or 0)
            warnings = int(payload.get("warning_count") or 0)
            passed = str(payload.get("status") or "") == "certified" and blockers == 0
            return passed, warnings > 0, f"UX certification reports {blockers} blocker(s) and {warnings} warning(s).", 0
        if role in {"security_snapshot", "performance_snapshot", "crash_recovery"}:
            blockers = int(payload.get("blocker_count") or payload.get("integrity_failure_count") or 0)
            warnings = int(payload.get("warning_count") or payload.get("unacknowledged_count") or 0)
            state = str(payload.get("status") or "").casefold()
            passed = blockers == 0 and state not in {"blocked", "failed", "error"}
            return passed, warnings > 0 or state in {"attention", "warning"}, f"{role.replace('_', ' ').title()} status is {state or 'unknown'} with {blockers} blocker(s).", 0
        if role == "final_release":
            blockers = int(payload.get("blocker_count") or 0)
            version = str(payload.get("version") or payload.get("release_version") or "")
            artifacts = payload.get("artifacts")
            passed = blockers == 0 and bool(version) and isinstance(artifacts, (list, dict))
            warning = int(payload.get("warning_count") or 0) > 0 or str(payload.get("status") or "") in {"ready_with_warnings", "attention"}
            return passed, warning, f"Final release manifest identifies {version or 'no version'} with {blockers} blocker(s).", 0
        if role == "update_channel":
            channel = str(payload.get("channel") or "").casefold()
            version = str(payload.get("version") or "")
            artifacts = payload.get("artifacts")
            passed = channel in {"preview", "beta", "stable"} and bool(version) and isinstance(artifacts, list) and bool(artifacts)
            warning = channel != "stable"
            return passed, warning, f"Update feed advertises {version or 'no version'} on {channel or 'no channel'}. Human promotion to stable remains required.", 0
        if role == "upgrade_backup":
            files = payload.get("artifacts") or payload.get("files")
            passed = isinstance(files, list) and bool(files) and bool(payload.get("version") or payload.get("source_version") or payload.get("backup_id"))
            return passed, False, "Upgrade backup manifest is present with integrity-listed artifacts." if passed else "Upgrade backup manifest is incomplete.", 0
        return False, False, f"Unsupported evidence role: {role}", 0

    @classmethod
    def _contains_secret(cls, value: object, *, key: str = "") -> bool:
        if (
            cls._SECRET_KEY_RE.fullmatch(key.strip())
            and not isinstance(value, (bool, int, float, type(None)))
            and value not in ("", [], {})
        ):
            return True
        if isinstance(value, Mapping):
            return any(cls._contains_secret(item, key=str(name)) for name, item in value.items())
        if isinstance(value, (list, tuple)):
            return any(cls._contains_secret(item, key=key) for item in value)
        if isinstance(value, str):
            return bool(cls._TOKEN_RE.search(value))
        return False

    def _captured_at(self, payload: Mapping[str, Any]) -> str:
        for key in ("finished_at", "generated_at", "captured_at", "created_at", "started_at"):
            value = str(payload.get(key) or "").strip()
            if value:
                return value
        return ""

    def _is_stale(self, captured_at: str, max_age_days: int) -> bool:
        if not captured_at:
            return True
        try:
            parsed = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        return self._now() - parsed.astimezone(timezone.utc) > timedelta(days=max(1, int(max_age_days)))

    def _resolve_commit(self, value: str) -> str:
        explicit = str(value or "").strip()
        if explicit:
            return explicit
        try:
            completed = self._command_runner(
                ["git", "rev-parse", "HEAD"],
                cwd=self.runtime.app_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if completed.returncode == 0:
                return str(completed.stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            pass
        return ""

    @staticmethod
    def _gate(
        gate_id: str,
        label: str,
        category: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str = "",
    ) -> ProductionCertificationGate:
        return ProductionCertificationGate(gate_id, label, category, status, severity, detail, remediation)

    def _artifact(
        self,
        role: str,
        path: Path,
        status: str,
        detail: str,
        *,
        captured_at: str = "",
    ) -> ProductionEvidenceArtifact:
        return ProductionEvidenceArtifact(
            role=role,
            path=path,
            status=status,
            size_bytes=path.stat().st_size,
            sha256=self._sha256(path),
            captured_at=captured_at,
            detail=detail,
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _payload_digest(payload: Mapping[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _now(self) -> datetime:
        return self._now_provider().astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat().replace("+00:00", "Z")
