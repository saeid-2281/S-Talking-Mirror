from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.services.evidence_integrity import EvidenceIntegrityMixin
from app.models.operational_readiness import (
    OperationalReadinessGate,
    OperationalReadinessSnapshot,
    OperationalReadinessSource,
)

class OperationalReadinessCertificationService(EvidenceIntegrityMixin):
    """Final read-only operational certification over verified production evidence."""

    SCHEMA_VERSION = 1
    SOURCE_ROLES = (
        "production_release",
        "operations_snapshot",
        "evidence_registry",
        "certification_refresh",
        "reliability_renewal",
    )
    _COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|private[_-]?key)"
    )
    _ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|/(?:home|users|tmp|var/tmp)/)")

    def __init__(
        self,
        runtime: RuntimeConfig,
        evidence_refresh_service: Any,
        operations_command_center_service: Any,
        production_release_certification_service: Any,
        reliability_assurance_renewal_service: Any,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.evidence_refresh_service = evidence_refresh_service
        self.operations_command_center_service = operations_command_center_service
        self.production_release_certification_service = (
            production_release_certification_service
        )
        self.reliability_assurance_renewal_service = (
            reliability_assurance_renewal_service
        )
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "operational-readiness-certification"
        self.snapshots_dir = self.root / "snapshots"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._command_runner = command_runner or subprocess.run
        for path in (
            self.root,
            self.snapshots_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def assess(
        self,
        *,
        project_id: int | None = None,
        source_commit: str = "",
    ) -> OperationalReadinessSnapshot:
        commit = self._resolve_commit(source_commit)
        gates: list[OperationalReadinessGate] = []
        sources: list[OperationalReadinessSource] = []

        gates.append(
            self._gate(
                "source_commit",
                "Immutable source commit",
                "pass" if self._COMMIT_RE.fullmatch(commit) else "block",
                "blocker",
                f"Certification is bound to commit {commit}." if commit else "No valid Git commit is available.",
                "Commit the reviewed source before final operational certification.",
            )
        )
        gates.append(
            self._gate(
                "stable_channel",
                "Stable release channel",
                "pass" if self.channel == "stable" else "block",
                "blocker",
                f"Release channel is {self.channel or 'unset'}.",
                "Run final operational certification only from the stable release channel.",
            )
        )

        source_paths = self._source_paths()
        for role in self.SOURCE_ROLES:
            source, gate = self._inspect_source(role, source_paths[role])
            sources.append(source)
            gates.append(gate)

        registry = self._read_json(source_paths["evidence_registry"])
        gates.append(self._freshness_gate(registry))

        refresh = self._read_json(source_paths["certification_refresh"])
        gates.append(self._refresh_status_gate(refresh))

        operations = self._read_json(source_paths["operations_snapshot"])
        gates.append(self._operations_status_gate(operations))

        renewal = self._read_json(source_paths["reliability_renewal"])
        gates.append(self._renewal_status_gate(renewal))

        blockers = sum(item.status == "block" for item in gates)
        warnings = sum(item.status == "warn" for item in gates)
        status = "blocked" if blockers else "ready_with_warnings" if warnings else "certified"
        summary = (
            f"Operational certification is blocked by {blockers} gate(s)."
            if blockers
            else f"Operational certification is eligible with {warnings} review warning(s)."
            if warnings
            else "All final operational readiness gates are certified."
        )
        certification_id = hashlib.sha256(
            f"{self.version}|{self.channel}|{commit}|{project_id}|{self._now().date().isoformat()}".encode(
                "utf-8"
            )
        ).hexdigest()[:20]
        return OperationalReadinessSnapshot(
            certification_id=f"operational-certification-{certification_id}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            source_commit=commit,
            project_id=project_id,
            status=status,
            summary=summary,
            gates=tuple(gates),
            sources=tuple(sources),
        )

    def export_snapshot(self, snapshot: OperationalReadinessSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload.update(self._safety_contract())
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.certification_id}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-operational-readiness-snapshot.json", payload)
        return path

    def create_certification(
        self,
        snapshot: OperationalReadinessSnapshot,
        *,
        reviewer: str,
        statement: str,
        acknowledge: bool = False,
    ) -> dict[str, object]:
        if snapshot.blocker_count:
            return {
                "status": "blocked",
                "detail": "Final certification cannot be written while operational blockers remain.",
                "path": "",
            }
        if not acknowledge:
            return {
                "status": "dry_run",
                "detail": "No certification was written. Explicit human acknowledgement is required.",
                "path": "",
            }
        reviewer_text = str(reviewer or "").strip()
        statement_text = str(statement or "").strip()
        if not reviewer_text or not statement_text:
            return {
                "status": "blocked",
                "detail": "Reviewer and certification statement are required.",
                "path": "",
            }
        if self._contains_private_text(reviewer_text) or self._contains_private_text(statement_text):
            return {
                "status": "blocked",
                "detail": "Reviewer or certification statement contains private material.",
                "path": "",
            }

        snapshot_path = self.export_snapshot(snapshot)
        snapshot_ok, snapshot_detail = self.verify_snapshot(snapshot_path)
        if not snapshot_ok:
            return {"status": "blocked", "detail": snapshot_detail, "path": ""}

        attestation: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "certification_id": snapshot.certification_id,
            "generated_at": self._now_iso(),
            "version": snapshot.version,
            "channel": snapshot.channel,
            "source_commit": snapshot.source_commit,
            "project_id": snapshot.project_id,
            "status": (
                "certified_with_warnings"
                if snapshot.warning_count
                else "certified"
            ),
            "reviewer": reviewer_text,
            "statement": statement_text,
            "human_acknowledged": True,
            "blocker_count": snapshot.blocker_count,
            "warning_count": snapshot.warning_count,
            "snapshot_filename": snapshot_path.name,
            "snapshot_sha256": self._sha256(snapshot_path),
            "sources": [item.to_dict() for item in snapshot.sources],
        }
        attestation.update(self._safety_contract())
        attestation["attestation_sha256"] = self._payload_digest(attestation)
        attestation_path = self.attestations_dir / f"{snapshot.certification_id}.json"
        self._write_json(attestation_path, attestation)
        self._write_json(self.root / "latest-operational-readiness-attestation.json", attestation)

        pack_path, receipt_path = self._build_audit_pack(snapshot_path, attestation_path)
        ok, detail = self.verify_audit_pack(pack_path, receipt_path)
        if not ok:
            for path in (attestation_path, pack_path, receipt_path):
                path.unlink(missing_ok=True)
            return {"status": "blocked", "detail": detail, "path": ""}
        return {
            "status": str(attestation["status"]),
            "detail": "Final operational certification and audit pack verified. No production state was changed.",
            "path": str(attestation_path),
            "snapshot_path": str(snapshot_path),
            "audit_pack_path": str(pack_path),
            "receipt_path": str(receipt_path),
        }

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Operational readiness snapshot is unreadable."
        expected = str(payload.get("snapshot_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("snapshot_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Operational readiness snapshot SHA-256 changed."
        if not self._verify_safety_contract(payload):
            return False, "Operational readiness safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Operational readiness snapshot contains private material."
        if str(payload.get("status") or "") not in {
            "certified",
            "ready_with_warnings",
            "blocked",
        }:
            return False, "Operational readiness snapshot status is invalid."
        sources = payload.get("sources")
        if not isinstance(sources, list) or len(sources) != len(self.SOURCE_ROLES):
            return False, "Operational readiness source custody is incomplete."
        for item in sources:
            if not isinstance(item, Mapping):
                return False, "Operational readiness source record is invalid."
            ok, detail = self._verify_source_record(item)
            if not ok:
                return False, detail
        return True, "Operational readiness snapshot and source custody verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Operational readiness attestation is unreadable."
        expected = str(payload.get("attestation_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("attestation_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Operational readiness attestation SHA-256 changed."
        if not self._verify_safety_contract(payload):
            return False, "Operational readiness attestation safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Operational readiness attestation contains private material."
        if payload.get("human_acknowledged") is not True:
            return False, "Operational readiness attestation lacks human acknowledgement."
        if str(payload.get("status") or "") not in {"certified", "certified_with_warnings"}:
            return False, "Operational readiness attestation is not certification-eligible."
        snapshot = self.snapshots_dir / str(payload.get("snapshot_filename") or "")
        if not snapshot.is_file() or self._sha256(snapshot) != str(payload.get("snapshot_sha256") or ""):
            return False, "Operational readiness snapshot custody changed."
        ok, detail = self.verify_snapshot(snapshot)
        if not ok:
            return False, detail
        sources = payload.get("sources")
        if not isinstance(sources, list) or len(sources) != len(self.SOURCE_ROLES):
            return False, "Operational readiness attestation source custody is incomplete."
        for item in sources:
            if not isinstance(item, Mapping):
                return False, "Operational readiness attestation source record is invalid."
            ok, detail = self._verify_source_record(item)
            if not ok:
                return False, detail
        return True, "Operational readiness attestation and source custody verified."

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        pack_path = Path(pack_path)
        receipt = self._read_json(Path(receipt_path))
        if not isinstance(receipt, dict):
            return False, "Operational readiness audit receipt is unreadable."
        expected = str(receipt.get("receipt_sha256") or "")
        unsigned = dict(receipt)
        unsigned.pop("receipt_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Operational readiness audit receipt SHA-256 changed."
        if not self._verify_safety_contract(receipt):
            return False, "Operational readiness audit receipt safety contract changed."
        if self._contains_private_payload(receipt):
            return False, "Operational readiness audit receipt contains private material."
        if not pack_path.is_file():
            return False, "Operational readiness audit pack is missing."
        if str(receipt.get("pack_filename") or "") != pack_path.name:
            return False, "Operational readiness audit pack filename changed."
        if int(receipt.get("pack_size_bytes") or -1) != pack_path.stat().st_size:
            return False, "Operational readiness audit pack size changed."
        if str(receipt.get("pack_sha256") or "") != self._sha256(pack_path):
            return False, "Operational readiness audit pack SHA-256 changed."

        try:
            with zipfile.ZipFile(pack_path, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Operational readiness audit pack contains an unsafe path."
                required = {
                    "manifest.json",
                    "certification/snapshot.json",
                    "certification/attestation.json",
                }
                if not required.issubset(names):
                    return False, "Operational readiness audit pack is incomplete."
                manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
                if not isinstance(manifest, dict):
                    return False, "Operational readiness audit manifest is invalid."
                manifest_expected = str(manifest.get("manifest_sha256") or "")
                manifest_unsigned = dict(manifest)
                manifest_unsigned.pop("manifest_sha256", None)
                if manifest_expected != self._payload_digest(manifest_unsigned):
                    return False, "Operational readiness audit manifest SHA-256 changed."
                entries = manifest.get("entries")
                if not isinstance(entries, list):
                    return False, "Operational readiness audit manifest entries are invalid."
                for record in entries:
                    if not isinstance(record, Mapping):
                        return False, "Operational readiness audit manifest entry is invalid."
                    name = str(record.get("path") or "")
                    if name == "manifest.json" or name not in names:
                        return False, "Operational readiness audit manifest references an invalid entry."
                    data = archive.read(name)
                    if int(record.get("size_bytes") or -1) != len(data):
                        return False, f"Operational readiness audit entry size changed: {name}"
                    if str(record.get("sha256") or "") != hashlib.sha256(data).hexdigest():
                        return False, f"Operational readiness audit entry SHA-256 changed: {name}"
        except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile, KeyError):
            return False, "Operational readiness audit pack is unreadable."

        attestation_name = str(receipt.get("attestation_filename") or "")
        attestation = self.attestations_dir / attestation_name
        if not attestation.is_file() or self._sha256(attestation) != str(
            receipt.get("attestation_sha256") or ""
        ):
            return False, "Operational readiness attestation custody changed."
        ok, detail = self.verify_attestation(attestation)
        if not ok:
            return False, detail
        return True, "Operational readiness audit pack, receipt and source custody verified."

    def _source_paths(self) -> dict[str, Path]:
        return {
            "production_release": Path(self.production_release_certification_service.root)
            / str(self.production_release_certification_service.ATTESTATION_NAME),
            "operations_snapshot": Path(self.operations_command_center_service.root)
            / "latest-operations-command-center.json",
            "evidence_registry": Path(self.evidence_refresh_service.root)
            / "latest-evidence-registry.json",
            "certification_refresh": Path(self.evidence_refresh_service.root)
            / "latest-certification-refresh.json",
            "reliability_renewal": Path(self.reliability_assurance_renewal_service.root)
            / "latest-reliability-renewal.json",
        }

    def _inspect_source(
        self, role: str, path: Path
    ) -> tuple[OperationalReadinessSource, OperationalReadinessGate]:
        labels = {
            "production_release": "Production release attestation",
            "operations_snapshot": "Operations command-center snapshot",
            "evidence_registry": "Evidence freshness registry",
            "certification_refresh": "Certification refresh record",
            "reliability_renewal": "Reliability assurance renewal",
        }
        label = labels[role]
        if not Path(path).is_file():
            source = OperationalReadinessSource(role, label, "", "", "Evidence is missing.")
            return source, self._gate(
                f"source_{role}",
                label,
                "block",
                "blocker",
                "Required verified evidence is missing.",
                f"Create and verify {label.lower()} before final certification.",
            )
        ok, detail = self._verify_source(role, Path(path))
        source = OperationalReadinessSource(
            role=role,
            label=label,
            filename=Path(path).name,
            sha256=self._sha256(Path(path)),
            verification_detail=detail,
        )
        return source, self._gate(
            f"source_{role}",
            label,
            "pass" if ok else "block",
            "blocker",
            detail,
            "Regenerate the source evidence if integrity verification fails.",
        )

    def _verify_source(self, role: str, path: Path) -> tuple[bool, str]:
        if role == "production_release":
            return self.production_release_certification_service.verify_attestation(path)
        if role == "operations_snapshot":
            return self.operations_command_center_service.verify_snapshot(path)
        if role == "evidence_registry":
            return self.evidence_refresh_service.verify_registry(path)
        if role == "certification_refresh":
            return self.evidence_refresh_service.verify_certification(path)
        if role == "reliability_renewal":
            return self.reliability_assurance_renewal_service.verify_renewal(path)
        return False, "Unknown operational readiness source role."

    def _verify_source_record(self, item: Mapping[str, object]) -> tuple[bool, str]:
        role = str(item.get("role") or "")
        if role not in self.SOURCE_ROLES:
            return False, "Operational readiness source role is invalid."
        expected_path = self._source_paths()[role]
        if str(item.get("filename") or "") != expected_path.name:
            return False, f"Operational readiness source filename changed: {role}"
        if not expected_path.is_file():
            return False, f"Operational readiness source is missing: {role}"
        if str(item.get("sha256") or "") != self._sha256(expected_path):
            return False, f"Operational readiness source custody changed: {role}"
        return self._verify_source(role, expected_path)

    def _freshness_gate(self, payload: dict[str, Any] | None) -> OperationalReadinessGate:
        if not isinstance(payload, dict):
            return self._gate(
                "evidence_freshness",
                "Evidence freshness",
                "block",
                "blocker",
                "Evidence freshness registry is unavailable.",
                "Refresh operational evidence before final certification.",
            )
        blocked = int(payload.get("blocked_count") or 0)
        expired = int(payload.get("expired_count") or 0)
        missing = int(payload.get("missing_count") or 0)
        due = int(payload.get("due_soon_count") or 0)
        if blocked or expired or missing:
            return self._gate(
                "evidence_freshness",
                "Evidence freshness",
                "block",
                "blocker",
                f"Evidence has {blocked} blocked, {expired} expired and {missing} missing item(s).",
                "Resolve blocked, expired and missing evidence before final certification.",
            )
        if due:
            return self._gate(
                "evidence_freshness",
                "Evidence freshness",
                "warn",
                "warning",
                f"{due} evidence item(s) are due soon.",
                "Acknowledge the freshness warning or refresh evidence before certification.",
            )
        return self._gate(
            "evidence_freshness",
            "Evidence freshness",
            "pass",
            "info",
            "All registered operational evidence is fresh.",
        )

    def _refresh_status_gate(self, payload: dict[str, Any] | None) -> OperationalReadinessGate:
        status = str((payload or {}).get("status") or "")
        if status == "certified":
            state = "pass"
            severity = "info"
            detail = "Latest certification refresh is certified."
        elif status == "attention":
            state = "warn"
            severity = "warning"
            detail = "Latest certification refresh requires review."
        else:
            state = "block"
            severity = "blocker"
            detail = "Latest certification refresh is blocked or unavailable."
        return self._gate(
            "certification_refresh_status",
            "Certification refresh status",
            state,
            severity,
            detail,
            "Create a current certified refresh before final operational certification.",
        )

    def _operations_status_gate(self, payload: dict[str, Any] | None) -> OperationalReadinessGate:
        status = str((payload or {}).get("overall_status") or "")
        if status == "healthy":
            state = "pass"
            severity = "info"
        elif status == "attention":
            state = "warn"
            severity = "warning"
        else:
            state = "block"
            severity = "blocker"
        return self._gate(
            "operations_status",
            "Production operations status",
            state,
            severity,
            f"Operations command center reports {status or 'unknown'}.",
            "Resolve critical/unknown operational domains before final certification.",
        )

    def _renewal_status_gate(self, payload: dict[str, Any] | None) -> OperationalReadinessGate:
        decision = str((payload or {}).get("decision") or "")
        if decision == "renew":
            state = "pass"
            severity = "info"
        elif decision == "renew_with_follow_up":
            state = "warn"
            severity = "warning"
        else:
            state = "block"
            severity = "blocker"
        return self._gate(
            "reliability_renewal_status",
            "Reliability assurance renewal",
            state,
            severity,
            f"Latest reliability renewal decision is {decision or 'unavailable'}.",
            "Resolve withheld or follow-up reliability assurance before final certification.",
        )

    def _build_audit_pack(self, snapshot_path: Path, attestation_path: Path) -> tuple[Path, Path]:
        certification_id = attestation_path.stem
        pack_path = self.audit_packs_dir / f"{certification_id}-audit-pack.zip"
        receipt_path = self.receipts_dir / f"{certification_id}-receipt.json"
        entries = {
            "certification/snapshot.json": snapshot_path.read_bytes(),
            "certification/attestation.json": attestation_path.read_bytes(),
        }
        manifest: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "certification_id": certification_id,
            "created_at": self._now_iso(),
            "entries": [
                {
                    "path": name,
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for name, data in sorted(entries.items())
            ],
        }
        manifest.update(self._safety_contract())
        manifest["manifest_sha256"] = self._payload_digest(manifest)
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(entries.items()):
                archive.writestr(name, data)
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8"),
            )
        receipt: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "certification_id": certification_id,
            "created_at": self._now_iso(),
            "pack_filename": pack_path.name,
            "pack_size_bytes": pack_path.stat().st_size,
            "pack_sha256": self._sha256(pack_path),
            "attestation_filename": attestation_path.name,
            "attestation_sha256": self._sha256(attestation_path),
        }
        receipt.update(self._safety_contract())
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        self._write_json(receipt_path, receipt)
        self._write_json(self.root / "latest-operational-readiness-receipt.json", receipt)
        return pack_path, receipt_path

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "read_only_certification": True,
            "source_evidence_mutated": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_provider_change": False,
            "automatic_billing_change": False,
            "automatic_ticket_change": False,
            "automatic_publish": False,
            "automatic_tag": False,
            "private_data_included": False,
        }

    def _resolve_commit(self, source_commit: str) -> str:
        explicit = str(source_commit or "").strip()
        if self._COMMIT_RE.fullmatch(explicit):
            return explicit.lower()
        try:
            result = self._command_runner(
                ["git", "-C", str(self.runtime.app_root), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, TypeError):
            return ""
        if int(getattr(result, "returncode", 1)) != 0:
            return ""
        value = str(getattr(result, "stdout", "") or "").strip()
        return value.lower() if self._COMMIT_RE.fullmatch(value) else ""

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        action: str = "",
    ) -> OperationalReadinessGate:
        return OperationalReadinessGate(code, label, status, severity, detail, action)
