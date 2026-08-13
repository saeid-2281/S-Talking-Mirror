from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PronunciationAssessment:
    row: int | None
    language: str
    original_text: str
    normalized_text: str
    normalization_kind: str = "none"
    normalization_safe: bool = False
    risk_level: str = "low"
    flags: tuple[str, ...] = ()
    summary: str = ""

    @property
    def changed(self) -> bool:
        return self.normalization_safe and self.normalized_text != self.original_text


@dataclass(frozen=True)
class PronunciationBatchAssessment:
    assessments: tuple[PronunciationAssessment, ...] = ()
    languages: tuple[str, ...] = ()
    high_risk_rows: tuple[int, ...] = ()
    medium_risk_rows: tuple[int, ...] = ()
    normalizable_rows: tuple[int, ...] = ()
    unsafe_normalization_rows: tuple[int, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)
    summary: str = ""

    @property
    def requires_review(self) -> bool:
        return bool(self.high_risk_rows or self.medium_risk_rows)
