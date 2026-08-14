from __future__ import annotations

import hashlib
import io
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models.domain import AppSettings, TTSJob
from app.models.pronunciation_audit import (
    PronunciationAuditDraft,
    PronunciationAuditEvent,
    PronunciationAuditVerification,
)
from app.services.pronunciation_assurance_service import PronunciationAssuranceService


class PronunciationAuditTrailService:
    """Privacy-safe append-only evidence for explicit pronunciation decisions.

    The audit trail is evidence only. It never changes a job, provider, account,
    voice, model, language, Preflight state, routing decision, or generation state.
    Raw source/normalized text, credentials, and raw voice/model/dictionary IDs are
    intentionally excluded from persisted audit events.
    """

    SCHEMA_VERSION = 1
    CHAIN_GENESIS = "0" * 64

    def __init__(self) -> None:
        self.assurance = PronunciationAssuranceService()

    @staticmethod
    def _hash_ref(value: object) -> str:
        raw = str(value or "").encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16] if raw else ""

    @classmethod
    def _project_ref(cls, project_id: str | None) -> str:
        return cls._hash_ref(project_id or "unsaved-project")[:12]

    @classmethod
    def _safe_project_name(cls, project_id: str | None) -> str:
        return f"project-{cls._project_ref(project_id)}"

    def audit_path(self, output_dir: Path, project_id: str | None) -> Path:
        return Path(output_dir) / ".s-talking" / "pronunciation-audit" / f"{self._safe_project_name(project_id)}.jsonl"

    def _dictionary_ref(self, settings: AppSettings) -> str:
        payload = {
            "active": str(settings.active_pronunciation_dictionary_id or ""),
            "locators": list(settings.pronunciation_dictionary_locators),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _safe_context(self, job: TTSJob, settings: AppSettings) -> dict[str, str]:
        language = str(getattr(job, "language_override", None) or settings.language_code or "").strip()
        return {
            "context_fingerprint": self.assurance.review_context_fingerprint(job, settings),
            "language": self.assurance._canonical_language(language),
            "provider": str(settings.provider or ""),
            "voice_ref": self._hash_ref(settings.voice_id),
            "model_ref": self._hash_ref(settings.model_id),
            "dictionary_ref": self._dictionary_ref(settings),
        }

    @staticmethod
    def _canonical_event_payload(event: dict[str, object]) -> bytes:
        payload = {key: value for key, value in event.items() if key != "event_hash"}
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

    @classmethod
    def _event_hash(cls, event: dict[str, object]) -> str:
        return hashlib.sha256(cls._canonical_event_payload(event)).hexdigest()

    def _parse_lines(self, path: Path) -> tuple[list[dict[str, object]], PronunciationAuditVerification]:
        if not path.exists():
            return [], PronunciationAuditVerification(valid=True, event_count=0, last_event_hash=self.CHAIN_GENESIS)
        events: list[dict[str, object]] = []
        previous = self.CHAIN_GENESIS
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError(f"line {line_number} is not an object")
                    if int(event.get("schema_version", 0)) != self.SCHEMA_VERSION:
                        raise ValueError(f"line {line_number} has unsupported schema")
                    if str(event.get("previous_event_hash", "")) != previous:
                        raise ValueError(f"line {line_number} breaks the audit chain")
                    expected = self._event_hash(event)
                    actual = str(event.get("event_hash", ""))
                    if expected != actual:
                        raise ValueError(f"line {line_number} event hash mismatch")
                    previous = actual
                    events.append(event)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return events, PronunciationAuditVerification(
                valid=False,
                event_count=len(events),
                last_event_hash=previous,
                error=str(exc),
            )
        return events, PronunciationAuditVerification(
            valid=True,
            event_count=len(events),
            last_event_hash=previous,
        )

    def verify(self, output_dir: Path, project_id: str | None) -> PronunciationAuditVerification:
        _events, verification = self._parse_lines(self.audit_path(output_dir, project_id))
        return verification

    def read_events(self, output_dir: Path, project_id: str | None) -> tuple[PronunciationAuditEvent, ...]:
        events, verification = self._parse_lines(self.audit_path(output_dir, project_id))
        if not verification.valid:
            raise ValueError(f"Pronunciation audit integrity check failed: {verification.error}")
        return tuple(PronunciationAuditEvent(**event) for event in events)

    def append_events(
        self,
        output_dir: Path,
        project_id: str | None,
        jobs: dict[int, TTSJob],
        settings: AppSettings,
        drafts: tuple[PronunciationAuditDraft, ...],
    ) -> tuple[PronunciationAuditEvent, ...]:
        if not drafts:
            return ()
        path = self.audit_path(output_dir, project_id)
        _existing, verification = self._parse_lines(path)
        if not verification.valid:
            raise ValueError(f"Refusing to append to an invalid pronunciation audit chain: {verification.error}")
        previous = verification.last_event_hash or self.CHAIN_GENESIS
        project_ref = self._project_ref(project_id)
        created: list[PronunciationAuditEvent] = []
        lines: list[str] = []
        occurred_at = datetime.now(timezone.utc).isoformat()
        for draft in drafts:
            job = jobs.get(int(draft.row_number))
            if job is None:
                raise ValueError(f"Audit row {draft.row_number} is not present in the current generation plan.")
            assessment = self.assurance.assess_job(job, settings)
            context = self._safe_context(job, settings)
            freshness = self.assurance.decision_freshness(job, settings)
            event: dict[str, object] = {
                "schema_version": self.SCHEMA_VERSION,
                "event_id": str(uuid.uuid4()),
                "occurred_at": occurred_at,
                "project_ref": project_ref,
                "row_number": int(draft.row_number),
                "action": str(draft.action),
                "decision_kind": str(draft.decision_kind),
                "previous_decision_kind": str(draft.previous_decision_kind),
                "freshness": freshness,
                "context_fingerprint": context["context_fingerprint"],
                "language": context["language"],
                "provider": context["provider"],
                "voice_ref": context["voice_ref"],
                "model_ref": context["model_ref"],
                "dictionary_ref": context["dictionary_ref"],
                "normalization_kind": assessment.normalization_kind if assessment.normalization_safe else "none",
                "normalization_safe": bool(assessment.normalization_safe),
                "risk_level": assessment.risk_level,
                "previous_event_hash": previous,
            }
            event["event_hash"] = self._event_hash(event)
            previous = str(event["event_hash"])
            created.append(PronunciationAuditEvent(**event))
            lines.append(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

        path.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(lines).encode("utf-8")
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        verification = self.verify(output_dir, project_id)
        if not verification.valid:
            raise ValueError(f"Pronunciation audit append verification failed: {verification.error}")
        return tuple(created)

    def stale_reason(self, event: PronunciationAuditEvent, job: TTSJob, settings: AppSettings) -> str:
        context = self._safe_context(job, settings)
        if event.context_fingerprint == context["context_fingerprint"]:
            return "current context"
        reasons: list[str] = []
        if event.language != context["language"]:
            reasons.append("effective language changed")
        if event.provider != context["provider"]:
            reasons.append("provider changed")
        if event.voice_ref != context["voice_ref"]:
            reasons.append("voice changed")
        if event.model_ref != context["model_ref"]:
            reasons.append("model changed")
        if event.dictionary_ref != context["dictionary_ref"]:
            reasons.append("pronunciation dictionary context changed")
        if not reasons:
            reasons.append("source text changed")
        return "; ".join(reasons)

    def workspace_evidence(
        self,
        output_dir: Path,
        project_id: str | None,
        jobs: tuple[TTSJob, ...],
        settings: AppSettings,
    ) -> tuple[str, dict[int, dict[str, object]]]:
        path = self.audit_path(output_dir, project_id)
        events_raw, verification = self._parse_lines(path)
        if not verification.valid:
            return f"Audit evidence: INTEGRITY FAILURE · {verification.error}", {}
        jobs_by_row = {job.row_number: job for job in jobs}
        rows: dict[int, dict[str, object]] = {}
        for raw in events_raw:
            event = PronunciationAuditEvent(**raw)
            row = rows.setdefault(event.row_number, {"count": 0})
            row["count"] = int(row["count"]) + 1
            row["last_action"] = event.action
            row["last_at"] = event.occurred_at
            row["last_hash"] = event.event_hash[:12]
            job = jobs_by_row.get(event.row_number)
            if job is not None:
                row["stale_reason"] = self.stale_reason(event, job, settings)
        decisions = sum(1 for event in events_raw if event.get("action") == "decision_set")
        revalidations = sum(1 for event in events_raw if event.get("action") == "decision_revalidated")
        clears = sum(1 for event in events_raw if event.get("action") == "decision_cleared")
        summary = (
            f"Audit evidence: {verification.event_count} event(s), chain VERIFIED; "
            f"decision sets {decisions}, revalidations {revalidations}, clears {clears}."
        )
        return summary, rows

    def export_report(
        self,
        output_dir: Path,
        project_id: str | None,
        jobs: tuple[TTSJob, ...],
        settings: AppSettings,
    ) -> Path:
        events = self.read_events(output_dir, project_id)
        verification = self.verify(output_dir, project_id)
        jobs_by_row = {job.row_number: job for job in jobs}
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target = Path(output_dir) / f"pronunciation-audit-{self._project_ref(project_id)}-{timestamp}.md"
        buffer = io.StringIO()
        buffer.write("# Pronunciation Decision Audit Evidence\n\n")
        buffer.write("Privacy-safe report: raw source/normalized text, credentials, and raw voice/model/dictionary IDs are excluded.\n\n")
        buffer.write(f"- Project reference: `{self._project_ref(project_id)}`\n")
        buffer.write(f"- Events: {verification.event_count}\n")
        buffer.write(f"- Audit chain: {'VERIFIED' if verification.valid else 'FAILED'}\n")
        buffer.write(f"- Last event hash: `{verification.last_event_hash}`\n\n")
        buffer.write("| UTC time | Row | Action | Decision | Previous | Freshness | Risk | Normalization | Context | Current context note |\n")
        buffer.write("|---|---:|---|---|---|---|---|---|---|---|\n")
        for event in events:
            job = jobs_by_row.get(event.row_number)
            reason = self.stale_reason(event, job, settings) if job is not None else "row not in current plan"
            values = [
                event.occurred_at,
                str(event.row_number),
                event.action,
                event.decision_kind or "—",
                event.previous_decision_kind or "—",
                event.freshness,
                event.risk_level,
                event.normalization_kind,
                event.context_fingerprint,
                reason,
            ]
            escaped = [value.replace("|", "\\|").replace("\n", " ") for value in values]
            buffer.write("| " + " | ".join(escaped) + " |\n")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(buffer.getvalue(), encoding="utf-8", newline="\n")
        return target
