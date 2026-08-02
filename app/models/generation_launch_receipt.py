from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GenerationLaunchReceipt:
    """One persisted, secret-free generation launch decision."""

    path: Path
    markdown_path: Path
    schema_version: int = 1
    receipt_id: str = ""
    created_at: str = ""
    project_name: str = ""
    launch_fingerprint: str = ""
    preflight_status: str = ""
    review_status: str = ""
    provider: str = ""
    model_id: str = ""
    voice_id: str = ""
    output_directory: str = ""
    files: int = 0
    characters: int = 0
    provider_requests: int = 0
    existing_outputs: int = 0
    risk_level: str = "unknown"
    estimated_cost: float = 0.0
    currency: str = "USD"
    acknowledged_codes: tuple[str, ...] = field(default_factory=tuple)
    required_acknowledgements: tuple[str, ...] = field(default_factory=tuple)
    integrity_status: str = "legacy"
    integrity_message: str = "Receipt predates integrity metadata."

    @property
    def integrity_ok(self) -> bool:
        return self.integrity_status in {"verified", "legacy"}

    @property
    def requires_attention(self) -> bool:
        return self.integrity_status in {"mismatch", "unreadable"} or self.risk_level == "high"


@dataclass(frozen=True)
class GenerationLaunchReceiptSummary:
    receipt_count: int = 0
    verified_count: int = 0
    legacy_count: int = 0
    mismatch_count: int = 0
    unreadable_count: int = 0
    high_risk_count: int = 0
    confirmation_required_count: int = 0
    total_files: int = 0
    total_characters: int = 0
