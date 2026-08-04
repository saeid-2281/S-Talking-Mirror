from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class UxCertificationGate:
    gate_id: str
    label: str
    category: str
    status: str
    severity: str
    detail: str
    remediation: str = ""

    @property
    def passed(self) -> bool:
        return self.status in {"pass", "not_applicable", "not_measured"}

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class ThemeContrastResult:
    theme: str
    role: str
    foreground: str
    background: str
    ratio: float
    required_ratio: float
    status: str

    @property
    def passed(self) -> bool:
        return self.ratio >= self.required_ratio

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["ratio"] = round(self.ratio, 2)
        payload["required_ratio"] = round(self.required_ratio, 2)
        payload["passed"] = self.passed
        return payload


@dataclass(frozen=True)
class AccessibilityIssue:
    issue_id: str
    category: str
    severity: str
    widget_path: str
    widget_type: str
    detail: str
    remediation: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DisplayCertificationProfile:
    scale_percent: int
    minimum_width: int
    minimum_height: int
    text_scale_percent: int
    status: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class UxAccessibilitySnapshot:
    captured_at: str
    status: str
    summary: str
    active_theme: str
    preference_summary: str
    interactive_widget_count: int
    audited_widget_count: int
    gates: tuple[UxCertificationGate, ...] = field(default_factory=tuple)
    contrast_results: tuple[ThemeContrastResult, ...] = field(default_factory=tuple)
    issues: tuple[AccessibilityIssue, ...] = field(default_factory=tuple)
    display_profiles: tuple[DisplayCertificationProfile, ...] = field(default_factory=tuple)
    export_path: Path | None = None

    @property
    def blocker_count(self) -> int:
        return sum(gate.status == "block" for gate in self.gates) + sum(
            issue.severity == "blocker" for issue in self.issues
        )

    @property
    def warning_count(self) -> int:
        return sum(gate.status == "warn" for gate in self.gates) + sum(
            issue.severity == "warning" for issue in self.issues
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "captured_at": self.captured_at,
            "status": self.status,
            "summary": self.summary,
            "active_theme": self.active_theme,
            "preference_summary": self.preference_summary,
            "interactive_widget_count": self.interactive_widget_count,
            "audited_widget_count": self.audited_widget_count,
            "blocker_count": self.blocker_count,
            "warning_count": self.warning_count,
            "gates": [gate.to_dict() for gate in self.gates],
            "contrast_results": [result.to_dict() for result in self.contrast_results],
            "issues": [issue.to_dict() for issue in self.issues],
            "display_profiles": [profile.to_dict() for profile in self.display_profiles],
            "export_path": self.export_path.name if self.export_path else "",
        }
