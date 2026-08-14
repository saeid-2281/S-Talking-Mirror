from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PronunciationReadinessRow:
    row_number: int
    category: str
    risk_level: str
    language: str
    decision_kind: str
    freshness: str
    normalization_safe: bool
    flags: tuple[str, ...] = ()
    reason: str = ""
    audit_event_count: int = 0
    audit_note: str = ""


@dataclass(frozen=True)
class PronunciationProjectReadiness:
    rows: tuple[PronunciationReadinessRow, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)
    total_jobs: int = 0
    pronunciation_risk: int = 0
    reviewed_current: int = 0
    stale_decisions: int = 0
    unresolved: int = 0
    normalized: int = 0
    keep_original: int = 0
    audit_integrity: str = "EMPTY"
    audit_event_count: int = 0
    summary: str = ""

    @property
    def requires_attention(self) -> bool:
        return bool(
            self.counts.get("Needs review", 0)
            or self.counts.get("Stale", 0)
            or self.counts.get("Unsafe", 0)
            or self.audit_integrity == "FAILED"
        )
