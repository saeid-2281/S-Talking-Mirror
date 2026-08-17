from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.services.intelligent_tts_execution_service import (
    IntelligentTTSExecutionBinding,
)


RUN_LEDGER_SCHEMA_VERSION = 1
RUN_LEDGER_EVENT_SCHEMA_VERSION = 1
TERMINAL_STATUSES = frozenset({"completed", "partial", "failed", "cancelled"})
LIFECYCLE_STATUSES = frozenset(
    {"approved", "running", "paused", "stopping"} | TERMINAL_STATUSES
)


class IntelligentTTSRunLedgerError(RuntimeError):
    """Base error for the B3 durable run ledger."""


class IntelligentTTSRunLedgerIntegrityError(IntelligentTTSRunLedgerError):
    """Raised when persisted ledger evidence no longer verifies."""


class IntelligentTTSRunLedgerTransitionError(IntelligentTTSRunLedgerError):
    """Raised for an invalid lifecycle transition."""


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


def _count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _optional_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _safe_component(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip())
    normalized = normalized.strip(".-_")
    if not normalized:
        normalized = fallback
    return normalized[:96]


@dataclass(frozen=True)
class IntelligentTTSRunLedgerEvent:
    schema_version: int
    index: int
    event_type: str
    timestamp: str
    payload: Mapping[str, Any]
    previous_digest: str
    event_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "index": self.index,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "payload": dict(self.payload),
            "previous_digest": self.previous_digest,
            "event_digest": self.event_digest,
        }


@dataclass(frozen=True)
class IntelligentTTSRunLedger:
    schema_version: int
    run_id: str
    project_key: str
    path: Path
    status: str
    manifest_digest: str
    authority_digest: str
    request_ids: tuple[str, ...]
    row_numbers: tuple[int, ...]
    provider: str
    profile_id: str | None
    voice_id: str
    model_id: str
    default_language: str
    output_root: str
    request_count: int
    character_count: int
    started_at: str
    events: tuple[IntelligentTTSRunLedgerEvent, ...]
    ledger_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "project_key": self.project_key,
            "status": self.status,
            "manifest_digest": self.manifest_digest,
            "authority_digest": self.authority_digest,
            "request_ids": list(self.request_ids),
            "row_numbers": list(self.row_numbers),
            "provider": self.provider,
            "profile_id": self.profile_id,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "default_language": self.default_language,
            "output_root": self.output_root,
            "request_count": self.request_count,
            "character_count": self.character_count,
            "started_at": self.started_at,
            "events": [event.to_dict() for event in self.events],
            "ledger_digest": self.ledger_digest,
        }


class IntelligentTTSRunLedgerService:
    """Persist B1/B2 execution identity through the complete run lifecycle.

    B3 is evidence-only. It cannot create/select a provider, run Preflight,
    start/restart Generation, apply Smart Routing, detect language from text,
    reorder the queue, retry a request, or choose a recovery provider.
    """

    def begin(
        self,
        binding: IntelligentTTSExecutionBinding,
        *,
        run_id: str,
        project_key: str,
        evidence_root: Path,
        started_at: datetime | None = None,
    ) -> IntelligentTTSRunLedger:
        normalized_run_id = str(run_id).strip()
        if not normalized_run_id:
            raise IntelligentTTSRunLedgerError("run_id is required")

        path = self.path_for(
            evidence_root,
            project_key,
            normalized_run_id,
        )

        if path.exists():
            existing = self.load(path)
            if (
                existing.run_id == normalized_run_id
                and existing.manifest_digest == binding.manifest_digest
                and existing.authority_digest == binding.authority_digest
            ):
                return existing
            raise IntelligentTTSRunLedgerError(
                "Run ledger path already exists for different execution evidence"
            )

        started = _utc_iso(started_at)
        base = {
            "schema_version": RUN_LEDGER_SCHEMA_VERSION,
            "run_id": normalized_run_id,
            "project_key": str(project_key),
            "status": "approved",
            "manifest_digest": binding.manifest_digest,
            "authority_digest": binding.authority_digest,
            "request_ids": list(binding.request_ids),
            "row_numbers": list(binding.row_numbers),
            "provider": binding.provider,
            "profile_id": binding.profile_id,
            "voice_id": binding.voice_id,
            "model_id": binding.model_id,
            "default_language": binding.default_language,
            "output_root": binding.output_root,
            "request_count": binding.request_count,
            "character_count": binding.character_count,
            "started_at": started,
            "events": [],
        }
        event = self._event(
            index=1,
            event_type="approved",
            timestamp=started,
            previous_digest="",
            payload={
                "manifest_digest": binding.manifest_digest,
                "authority_digest": binding.authority_digest,
                "request_count": binding.request_count,
                "character_count": binding.character_count,
                "cross_provider_failover": binding.cross_provider_failover,
                "automatic_execution": binding.automatic_execution,
                "language_override_policy": binding.language_override_policy,
            },
        )
        base["events"] = [event.to_dict()]
        payload = self._with_ledger_digest(base)
        self._write(path, payload)
        return self.load(path)

    @staticmethod
    def path_for(
        evidence_root: Path,
        project_key: str,
        run_id: str,
    ) -> Path:
        root = Path(evidence_root)
        project_dir = root / _safe_component(project_key, "project")
        filename = _safe_component(str(run_id), "run") + ".intelligent-tts-ledger.json"
        return project_dir / filename

    def discover_open(
        self,
        evidence_root: Path,
    ) -> tuple[IntelligentTTSRunLedger, ...]:
        root = Path(evidence_root)
        if not root.exists():
            return ()
        ledgers: list[IntelligentTTSRunLedger] = []
        for path in sorted(root.rglob("*.intelligent-tts-ledger.json")):
            try:
                ledger = self.load(path)
            except IntelligentTTSRunLedgerIntegrityError:
                continue
            if ledger.status not in TERMINAL_STATUSES:
                ledgers.append(ledger)
        return tuple(sorted(ledgers, key=lambda item: (item.started_at, str(item.path))))

    def record_recovery_lineage(
        self,
        ledger_path: Path,
        lineage: Mapping[str, Any],
        *,
        timestamp: datetime | None = None,
    ) -> IntelligentTTSRunLedger:
        ledger = self.load(Path(ledger_path))
        if ledger.status in TERMINAL_STATUSES:
            raise IntelligentTTSRunLedgerTransitionError(
                f"Run ledger is already terminal: {ledger.status}"
            )
        allowed = (
            "continuity_status",
            "parent_run_id",
            "parent_ledger_path",
            "parent_ledger_digest",
            "parent_status",
            "resume_receipt_id",
            "resume_receipt_path",
        )
        safe_lineage = {
            key: None if lineage.get(key) is None else str(lineage.get(key))
            for key in allowed
        }
        for event in ledger.events:
            if event.event_type != "recovery_lineage":
                continue
            if dict(event.payload) == safe_lineage:
                return ledger
            raise IntelligentTTSRunLedgerTransitionError(
                "Run ledger already contains different recovery lineage"
            )
        payload = ledger.to_dict()
        payload.pop("ledger_digest", None)
        event = self._event(
            index=len(ledger.events) + 1,
            event_type="recovery_lineage",
            timestamp=_utc_iso(timestamp),
            previous_digest=ledger.events[-1].event_digest,
            payload=safe_lineage,
        )
        payload["events"].append(event.to_dict())
        payload = self._with_ledger_digest(payload)
        self._write(ledger.path, payload)
        return self.load(ledger.path)

    def record_status(
        self,
        ledger_path: Path,
        status: str,
        *,
        metrics: Mapping[str, Any] | None = None,
        timestamp: datetime | None = None,
    ) -> IntelligentTTSRunLedger:
        normalized = str(status).strip().casefold()
        if normalized not in LIFECYCLE_STATUSES:
            raise IntelligentTTSRunLedgerTransitionError(
                f"Unsupported run-ledger status: {status}"
            )

        ledger = self.load(Path(ledger_path))
        if ledger.status in TERMINAL_STATUSES:
            if ledger.status == normalized:
                return ledger
            raise IntelligentTTSRunLedgerTransitionError(
                f"Run ledger is already terminal: {ledger.status}"
            )
        if normalized in TERMINAL_STATUSES:
            raise IntelligentTTSRunLedgerTransitionError(
                "Use finalize() for a terminal run-ledger transition"
            )

        payload = ledger.to_dict()
        payload.pop("ledger_digest", None)
        payload["status"] = normalized
        event = self._event(
            index=len(ledger.events) + 1,
            event_type=normalized,
            timestamp=_utc_iso(timestamp),
            previous_digest=ledger.events[-1].event_digest,
            payload=self._safe_metrics(metrics),
        )
        payload["events"].append(event.to_dict())
        payload = self._with_ledger_digest(payload)
        self._write(ledger.path, payload)
        return self.load(ledger.path)

    def finalize(
        self,
        ledger_path: Path,
        result: str,
        *,
        summary: Mapping[str, Any] | None = None,
        execution_session_path: str | Path | None = None,
        execution_receipt_path: str | Path | None = None,
        report_path: str | Path | None = None,
        artifact_receipt_path: str | Path | None = None,
        operations_snapshot_path: str | Path | None = None,
        finished_at: datetime | None = None,
    ) -> IntelligentTTSRunLedger:
        normalized_result = str(result).strip().casefold()
        if normalized_result not in TERMINAL_STATUSES:
            raise IntelligentTTSRunLedgerTransitionError(
                f"Unsupported terminal result: {result}"
            )

        ledger = self.load(Path(ledger_path))
        if ledger.status in TERMINAL_STATUSES:
            if ledger.status == normalized_result:
                return ledger
            raise IntelligentTTSRunLedgerTransitionError(
                f"Run ledger is already terminal: {ledger.status}"
            )

        reconciliation = self._reconcile(ledger.request_count, normalized_result, summary)
        event_payload = {
            "result": normalized_result,
            "outcome_reconciliation": reconciliation,
            "execution_session_path": _optional_path(execution_session_path),
            "execution_receipt_path": _optional_path(execution_receipt_path),
            "report_path": _optional_path(report_path),
            "artifact_receipt_path": _optional_path(artifact_receipt_path),
            "operations_snapshot_path": _optional_path(
                operations_snapshot_path
            ),
        }
        payload = ledger.to_dict()
        payload.pop("ledger_digest", None)
        payload["status"] = normalized_result
        event = self._event(
            index=len(ledger.events) + 1,
            event_type="finalized",
            timestamp=_utc_iso(finished_at),
            previous_digest=ledger.events[-1].event_digest,
            payload=event_payload,
        )
        payload["events"].append(event.to_dict())
        payload = self._with_ledger_digest(payload)
        self._write(ledger.path, payload)
        return self.load(ledger.path)

    def load(self, ledger_path: Path) -> IntelligentTTSRunLedger:
        path = Path(ledger_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntelligentTTSRunLedgerIntegrityError(
                f"Unable to read run ledger: {exc}"
            ) from exc

        self._verify_payload(payload)
        events = tuple(
            IntelligentTTSRunLedgerEvent(
                schema_version=int(item["schema_version"]),
                index=int(item["index"]),
                event_type=str(item["event_type"]),
                timestamp=str(item["timestamp"]),
                payload=dict(item.get("payload") or {}),
                previous_digest=str(item.get("previous_digest") or ""),
                event_digest=str(item["event_digest"]),
            )
            for item in payload.get("events") or []
        )
        return IntelligentTTSRunLedger(
            schema_version=int(payload["schema_version"]),
            run_id=str(payload["run_id"]),
            project_key=str(payload["project_key"]),
            path=path,
            status=str(payload["status"]),
            manifest_digest=str(payload["manifest_digest"]),
            authority_digest=str(payload["authority_digest"]),
            request_ids=tuple(str(value) for value in payload.get("request_ids") or []),
            row_numbers=tuple(int(value) for value in payload.get("row_numbers") or []),
            provider=str(payload["provider"]),
            profile_id=(None if payload.get("profile_id") is None else str(payload["profile_id"])),
            voice_id=str(payload["voice_id"]),
            model_id=str(payload["model_id"]),
            default_language=str(payload["default_language"]),
            output_root=str(payload["output_root"]),
            request_count=int(payload["request_count"]),
            character_count=int(payload["character_count"]),
            started_at=str(payload["started_at"]),
            events=events,
            ledger_digest=str(payload["ledger_digest"]),
        )

    def verify(self, ledger_path: Path) -> bool:
        self.load(Path(ledger_path))
        return True

    @staticmethod
    def _safe_metrics(metrics: Mapping[str, Any] | None) -> dict[str, Any]:
        if not metrics:
            return {}
        allowed = (
            "elapsed_seconds",
            "active_generation_time",
            "paused_time",
            "retry_events",
            "files_per_minute",
            "characters_per_minute",
        )
        result: dict[str, Any] = {}
        for key in allowed:
            value = metrics.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                result[key] = value
        return result

    @staticmethod
    def _reconcile(
        request_count: int,
        result: str,
        summary: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        source = summary or {}
        completed = _count(source.get("completed"))
        failed = _count(source.get("failed"))
        skipped = _count(source.get("skipped"))
        accounted = completed + failed + skipped
        unaccounted = max(0, request_count - accounted)
        if accounted > request_count:
            status = "over_accounted"
        elif result == "cancelled" and accounted == 0:
            status = "cancelled_unexecuted"
        elif accounted == request_count:
            status = "exact"
        else:
            status = "partial_accounting"
        return {
            "status": status,
            "request_count": request_count,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "accounted": accounted,
            "unaccounted": unaccounted,
        }

    @staticmethod
    def _event(
        *,
        index: int,
        event_type: str,
        timestamp: str,
        previous_digest: str,
        payload: Mapping[str, Any],
    ) -> IntelligentTTSRunLedgerEvent:
        material = {
            "schema_version": RUN_LEDGER_EVENT_SCHEMA_VERSION,
            "index": index,
            "event_type": event_type,
            "timestamp": timestamp,
            "payload": dict(payload),
            "previous_digest": previous_digest,
        }
        return IntelligentTTSRunLedgerEvent(
            schema_version=RUN_LEDGER_EVENT_SCHEMA_VERSION,
            index=index,
            event_type=event_type,
            timestamp=timestamp,
            payload=dict(payload),
            previous_digest=previous_digest,
            event_digest=_digest(material),
        )

    @staticmethod
    def _with_ledger_digest(payload: Mapping[str, Any]) -> dict[str, Any]:
        material = dict(payload)
        material.pop("ledger_digest", None)
        material["ledger_digest"] = _digest(material)
        return material

    def _verify_payload(self, payload: Mapping[str, Any]) -> None:
        if int(payload.get("schema_version", 0)) != RUN_LEDGER_SCHEMA_VERSION:
            raise IntelligentTTSRunLedgerIntegrityError(
                "Unsupported run-ledger schema version"
            )
        events = list(payload.get("events") or [])
        if not events:
            raise IntelligentTTSRunLedgerIntegrityError(
                "Run ledger contains no events"
            )
        previous = ""
        for expected_index, item in enumerate(events, start=1):
            material = {
                "schema_version": int(item["schema_version"]),
                "index": int(item["index"]),
                "event_type": str(item["event_type"]),
                "timestamp": str(item["timestamp"]),
                "payload": dict(item.get("payload") or {}),
                "previous_digest": str(item.get("previous_digest") or ""),
            }
            if material["index"] != expected_index:
                raise IntelligentTTSRunLedgerIntegrityError(
                    "Run-ledger event index is not contiguous"
                )
            if material["previous_digest"] != previous:
                raise IntelligentTTSRunLedgerIntegrityError(
                    "Run-ledger event chain is broken"
                )
            expected_digest = _digest(material)
            if str(item.get("event_digest") or "") != expected_digest:
                raise IntelligentTTSRunLedgerIntegrityError(
                    "Run-ledger event digest mismatch"
                )
            previous = expected_digest
        material = dict(payload)
        actual_digest = str(material.pop("ledger_digest", ""))
        if actual_digest != _digest(material):
            raise IntelligentTTSRunLedgerIntegrityError(
                "Run-ledger digest mismatch"
            )

    @staticmethod
    def _write(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(path)
