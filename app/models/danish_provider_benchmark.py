from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal


DanishDocumentationState = Literal[
    "documented",
    "unsupported",
    "runtime_dependent",
    "not_explicit",
    "test_only",
    "unknown",
]
DanishCertificationState = Literal[
    "certified",
    "conditional",
    "not_certified",
    "pending",
    "not_applicable",
]


@dataclass(frozen=True)
class DanishBenchmarkCase:
    case_id: str
    category: str
    text: str
    critical: bool = False
    guidance: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DanishDocumentationEvidence:
    provider_id: str
    state: DanishDocumentationState
    label: str
    source_label: str
    source_url: str
    checked_on: str
    note: str

    @property
    def supports_benchmark(self) -> bool:
        return self.state in {"documented", "runtime_dependent", "not_explicit"}

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DanishBenchmarkRating:
    case_id: str
    intelligibility: int
    pronunciation: int
    prosody: int
    stability: int
    note: str = ""

    def __post_init__(self) -> None:
        for name in ("intelligibility", "pronunciation", "prosody", "stability"):
            value = int(getattr(self, name))
            if value < 1 or value > 5:
                raise ValueError(f"{name} must be between 1 and 5")

    @property
    def average(self) -> float:
        return (
            self.intelligibility
            + self.pronunciation
            + self.prosody
            + self.stability
        ) / 4.0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["average"] = round(self.average, 3)
        return payload


@dataclass(frozen=True)
class DanishProviderCertification:
    provider_id: str
    provider_name: str
    status: DanishCertificationState
    documentation_state: DanishDocumentationState
    score: float | None
    case_count: int
    minimum_cases: int
    critical_failures: tuple[str, ...] = field(default_factory=tuple)
    voice_id: str = ""
    model_id: str = ""
    reviewer: str = ""
    reviewed_at: str = ""
    evidence_path: str = ""
    evidence_sha256: str = ""
    summary: str = ""

    @property
    def routing_state(self) -> str:
        if self.status == "certified":
            return "confirmed"
        if self.status == "not_certified":
            return "blocked"
        return "unknown"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DanishProviderBenchmarkSnapshot:
    generated_at: str
    language_code: str
    minimum_cases: int
    pass_score: float
    providers: tuple[DanishProviderCertification, ...]
    cases: tuple[DanishBenchmarkCase, ...]

    @property
    def certified_count(self) -> int:
        return sum(item.status == "certified" for item in self.providers)

    @property
    def blocked_count(self) -> int:
        return sum(item.status == "not_certified" for item in self.providers)

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "language_code": self.language_code,
            "minimum_cases": self.minimum_cases,
            "pass_score": self.pass_score,
            "certified_count": self.certified_count,
            "blocked_count": self.blocked_count,
            "providers": [item.to_dict() for item in self.providers],
            "cases": [item.to_dict() for item in self.cases],
        }
