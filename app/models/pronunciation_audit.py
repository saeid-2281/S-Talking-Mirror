from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PronunciationAuditDraft:
    row_number: int
    action: str
    decision_kind: str = ""
    previous_decision_kind: str = ""


@dataclass(frozen=True)
class PronunciationAuditEvent:
    schema_version: int
    event_id: str
    occurred_at: str
    project_ref: str
    row_number: int
    action: str
    decision_kind: str
    previous_decision_kind: str
    freshness: str
    context_fingerprint: str
    language: str
    provider: str
    voice_ref: str
    model_ref: str
    dictionary_ref: str
    normalization_kind: str
    normalization_safe: bool
    risk_level: str
    previous_event_hash: str
    event_hash: str


@dataclass(frozen=True)
class PronunciationAuditVerification:
    valid: bool
    event_count: int = 0
    last_event_hash: str = ""
    error: str = ""
