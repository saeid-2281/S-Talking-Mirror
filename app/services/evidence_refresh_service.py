from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.services.evidence_integrity import EvidenceIntegrityMixin
from app.models.evidence_refresh import EvidenceFreshnessEntry, EvidenceRefreshSnapshot

class EvidenceRefreshService(EvidenceIntegrityMixin):
    """Builds read-only freshness and certification evidence from verified artifacts."""

    SCHEMA_VERSION = 1
    POLICY: Mapping[str, int] = {
        "health": 30,
        "incidents": 14,
        "slo": 7,
        "capacity": 7,
        "recovery": 30,
        "providers": 14,
        "billing": 30,
        "audit": 30,
    }
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|passwd|secret|token|private[_-]?key)"
    )
    _ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|/(?:home|users|tmp|var/tmp)/)")

    def __init__(
        self,
        runtime: RuntimeConfig,
        operations_command_center_service: Any,
        *,
        version: str | None = None,
        channel: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.operations_command_center_service = operations_command_center_service
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.root = runtime.artifacts_dir / "evidence-refresh"
        self.registries_dir = self.root / "registries"
        self.certifications_dir = self.root / "certifications"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self.registries_dir.mkdir(parents=True, exist_ok=True)
        self.certifications_dir.mkdir(parents=True, exist_ok=True)

    def assess(self, *, project_id: int | None = None) -> EvidenceRefreshSnapshot:
        operations = self.operations_command_center_service.snapshot(project_id=project_id)
        entries = tuple(self._entry(domain) for domain in operations.domains)
        statuses = {item.status for item in entries}
        overall = (
            "blocked"
            if "blocked" in statuses
            else "attention"
            if statuses.intersection({"due_soon", "expired", "missing"})
            else "current"
        )
        recommendations = tuple(
            self._recommendation(item)
            for item in entries
            if item.status != "fresh"
        ) or ("All registered operational evidence is current.",)
        return EvidenceRefreshSnapshot(
            snapshot_id=f"evidence-refresh-{uuid.uuid4().hex[:12]}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            project_id=project_id,
            overall_status=overall,
            entries=entries,
            recommendations=recommendations,
        )

    def export_registry(self, snapshot: EvidenceRefreshSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["schema_version"] = self.SCHEMA_VERSION
        payload.update(self._safety_contract())
        payload["registry_sha256"] = self._payload_digest(payload)
        path = self.registries_dir / f"{snapshot.snapshot_id}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-evidence-registry.json", payload)
        return path

    def refresh_certification(
        self, *, project_id: int | None = None
    ) -> tuple[Path, Path]:
        # Refresh means recomputing read-only derived evidence. No source artifact is mutated.
        operations = self.operations_command_center_service.snapshot(project_id=project_id)
        operations_path = self.operations_command_center_service.export_snapshot(operations)
        operations_ok, operations_detail = (
            self.operations_command_center_service.verify_snapshot(operations_path)
        )
        snapshot = self.assess(project_id=project_id)
        registry_path = self.export_registry(snapshot)
        registry_ok, registry_detail = self.verify_registry(registry_path)
        status = (
            "blocked"
            if not operations_ok or not registry_ok or snapshot.overall_status == "blocked"
            else "attention"
            if snapshot.overall_status == "attention"
            else "certified"
        )
        payload: dict[str, object] = {
            "schema_version": self.SCHEMA_VERSION,
            "refresh_id": f"certification-refresh-{uuid.uuid4().hex[:12]}",
            "generated_at": self._now_iso(),
            "version": self.version,
            "channel": self.channel,
            "project_id": project_id,
            "status": status,
            "operations_snapshot_filename": operations_path.name,
            "operations_snapshot_sha256": self._sha256(operations_path),
            "operations_verification": operations_detail,
            "registry_filename": registry_path.name,
            "registry_sha256": self._sha256(registry_path),
            "registry_verification": registry_detail,
            "fresh_count": snapshot.count("fresh"),
            "due_soon_count": snapshot.count("due_soon"),
            "expired_count": snapshot.count("expired"),
            "missing_count": snapshot.count("missing"),
            "blocked_count": snapshot.count("blocked"),
        }
        payload.update(self._safety_contract())
        payload["certification_sha256"] = self._payload_digest(payload)
        path = self.certifications_dir / f"{payload['refresh_id']}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-certification-refresh.json", payload)
        return registry_path, path

    def verify_registry(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Evidence freshness registry is unreadable."
        expected = str(payload.get("registry_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("registry_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Evidence freshness registry SHA-256 changed."
        if not self._verify_safety_contract(payload):
            return False, "Evidence refresh safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Evidence freshness registry contains private material."
        entries = payload.get("entries")
        if not isinstance(entries, list) or len(entries) != len(self.POLICY):
            return False, "Evidence freshness registry is incomplete."
        allowed = {"fresh", "due_soon", "expired", "missing", "blocked"}
        for item in entries:
            if not isinstance(item, Mapping) or str(item.get("status")) not in allowed:
                return False, "Evidence freshness status is invalid."
        return True, "Evidence freshness registry verified."

    def verify_certification(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if not isinstance(payload, dict):
            return False, "Certification refresh record is unreadable."
        expected = str(payload.get("certification_sha256") or "")
        unsigned = dict(payload)
        unsigned.pop("certification_sha256", None)
        if not expected or expected != self._payload_digest(unsigned):
            return False, "Certification refresh SHA-256 changed."
        if not self._verify_safety_contract(payload):
            return False, "Certification refresh safety contract changed."
        if self._contains_private_payload(payload):
            return False, "Certification refresh contains private material."
        if str(payload.get("status") or "") not in {"certified", "attention", "blocked"}:
            return False, "Certification refresh status is invalid."
        registry = self.registries_dir / str(payload.get("registry_filename") or "")
        if not registry.is_file() or self._sha256(registry) != str(payload.get("registry_sha256") or ""):
            return False, "Certification refresh registry custody changed."
        ok, detail = self.verify_registry(registry)
        if not ok:
            return False, detail
        operations = (
            Path(self.operations_command_center_service.snapshots_dir)
            / str(payload.get("operations_snapshot_filename") or "")
        )
        if not operations.is_file() or self._sha256(operations) != str(
            payload.get("operations_snapshot_sha256") or ""
        ):
            return False, "Certification refresh operations snapshot custody changed."
        ok, detail = self.operations_command_center_service.verify_snapshot(operations)
        if not ok:
            return False, detail
        return True, "Certification refresh record and source custody verified."

    def _entry(self, domain: Any) -> EvidenceFreshnessEntry:
        code = str(domain.code)
        max_age = int(self.POLICY[code])
        due_soon = max(1, min(7, max_age // 4))
        filename = str(domain.evidence_filename or "")
        if not filename:
            return EvidenceFreshnessEntry(
                code=code,
                label=str(domain.label),
                status="missing",
                age_days=None,
                max_age_days=max_age,
                due_soon_days=due_soon,
                verification_detail=str(domain.headline),
                action_code=str(domain.action_code),
            )
        path = self.operations_command_center_service._evidence_path(code, filename)
        if path is None or not Path(path).is_file():
            return EvidenceFreshnessEntry(
                code=code,
                label=str(domain.label),
                status="missing",
                age_days=None,
                max_age_days=max_age,
                due_soon_days=due_soon,
                evidence_filename=filename,
                verification_detail="Registered evidence file is missing.",
                action_code=str(domain.action_code),
            )
        path = Path(path)
        age_days = max(0.0, (self._now_timestamp() - path.stat().st_mtime) / 86400.0)
        if str(domain.metric) == "Verification failed":
            status = "blocked"
        elif age_days > max_age:
            status = "expired"
        elif (max_age - age_days) <= due_soon:
            status = "due_soon"
        else:
            status = "fresh"
        return EvidenceFreshnessEntry(
            code=code,
            label=str(domain.label),
            status=status,
            age_days=round(age_days, 3),
            max_age_days=max_age,
            due_soon_days=due_soon,
            evidence_filename=path.name,
            evidence_sha256=self._sha256(path),
            verification_detail=self._safe_detail(str(domain.detail)),
            action_code=str(domain.action_code),
        )

    @classmethod
    def _safe_detail(cls, value: str) -> str:
        if cls._SECRET_RE.search(value) or cls._ABSOLUTE_PATH_RE.search(value):
            return "Source verification requires specialist review."
        return value

    @staticmethod
    def _recommendation(item: EvidenceFreshnessEntry) -> str:
        if item.status == "blocked":
            return f"Resolve verification failure for {item.label}."
        if item.status == "missing":
            return f"Create verified evidence for {item.label}."
        if item.status == "expired":
            return f"Refresh {item.label}; evidence is expired."
        return f"Refresh {item.label} before its evidence expires."

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "read_only_refresh": True,
            "source_evidence_mutated": False,
            "automatic_deploy": False,
            "automatic_rollback": False,
            "automatic_restart": False,
            "automatic_provider_change": False,
            "automatic_billing_change": False,
            "automatic_ticket_change": False,
            "automatic_publish": False,
            "private_data_included": False,
        }
