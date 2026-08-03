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
    language_code: str = ""
    file_extension: str = ""
    max_retries: int = 0
    delay_seconds: float = 0.0
    skip_existing: bool = False
    overwrite_existing: bool = False
    generation_scope: str = ""
    execution_order: str = ""
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
    guard_approval_id: str = ""
    guard_policy_profile_id: str = ""
    guard_policy_version: int = 0
    guard_policy_locked: bool = False
    decision_status: str = ""
    decision_trace_id: str = ""
    decision_summary: str = ""
    run_id: str = ""
    execution_session_path: str = ""

    @property
    def integrity_ok(self) -> bool:
        return self.integrity_status in {"verified", "legacy"}

    @property
    def requires_attention(self) -> bool:
        return (
            self.integrity_status in {"mismatch", "unreadable"}
            or self.risk_level == "high"
            or self.decision_status in {"blocked", "approval_required"}
        )


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


@dataclass(frozen=True)
class GenerationLaunchReceiptChange:
    """One normalized difference between a baseline and candidate receipt."""

    key: str
    label: str
    category: str
    baseline_value: str
    candidate_value: str
    severity: str = "info"


@dataclass(frozen=True)
class GenerationLaunchReceiptComparison:
    """Secret-free configuration drift analysis for two launch receipts."""

    baseline: GenerationLaunchReceipt
    candidate: GenerationLaunchReceipt
    changes: tuple[GenerationLaunchReceiptChange, ...] = field(default_factory=tuple)
    status: str = "matching"
    summary: str = "No launch drift detected."

    @property
    def changed_count(self) -> int:
        return len(self.changes)

    @property
    def critical_count(self) -> int:
        return sum(item.severity == "critical" for item in self.changes)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.changes)

    @property
    def information_count(self) -> int:
        return sum(item.severity == "info" for item in self.changes)

    @property
    def safe_to_reuse(self) -> bool:
        return (
            self.critical_count == 0
            and self.warning_count == 0
            and self.baseline.integrity_ok
            and self.candidate.integrity_ok
        )


@dataclass(frozen=True)
class GenerationLaunchGuardPolicy:
    """Per-project policy controlling baseline drift checks before launch."""

    project_name: str
    mode: str = "warn"
    protected_categories: tuple[str, ...] = field(default_factory=tuple)
    updated_at: str = ""
    profile_id: str = ""
    profile_name: str = ""
    locked: bool = False
    version: int = 0
    updated_by: str = ""
    history_count: int = 0

    @property
    def enabled(self) -> bool:
        return self.mode in {"warn", "enforce"}

    @property
    def blocks_critical_drift(self) -> bool:
        return self.mode == "enforce"


@dataclass(frozen=True)
class GenerationLaunchGuardPolicyProfile:
    """Reusable secret-free template for project baseline guard policies."""

    profile_id: str
    name: str
    description: str = ""
    mode: str = "warn"
    protected_categories: tuple[str, ...] = field(default_factory=tuple)
    built_in: bool = False
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class GenerationLaunchGuardPolicyHistoryEntry:
    """Immutable audit entry for one project guard-policy revision."""

    version: int
    occurred_at: str
    action: str
    actor: str = ""
    profile_id: str = ""
    profile_name: str = ""
    mode: str = "warn"
    protected_categories: tuple[str, ...] = field(default_factory=tuple)
    locked: bool = False
    note: str = ""


@dataclass(frozen=True)
class GenerationLaunchGuardApprovalEvent:
    """One immutable audit event in an approval lifecycle."""

    action: str
    occurred_at: str
    actor: str = ""
    note: str = ""
    receipt_id: str = ""


@dataclass(frozen=True)
class GenerationLaunchGuardApprovalSummary:
    """Operational metrics for a filtered approval archive."""

    total_count: int = 0
    active_count: int = 0
    expired_count: int = 0
    consumed_count: int = 0
    revoked_count: int = 0
    project_count: int = 0
    authorized_uses: int = 0
    used_count: int = 0


@dataclass(frozen=True)
class GenerationLaunchGuardApproval:
    """Time-bound approval for one exact protected launch drift."""

    approval_id: str
    project_name: str
    launch_fingerprint: str
    baseline_receipt_id: str
    protected_change_keys: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    approved_by: str = ""
    created_at: str = ""
    expires_at: str = ""
    max_uses: int = 1
    used_count: int = 0
    status: str = "approved"
    revoked_at: str = ""
    last_used_at: str = ""
    renewed_from_id: str = ""
    audit_events: tuple[GenerationLaunchGuardApprovalEvent, ...] = field(
        default_factory=tuple
    )

    @property
    def remaining_uses(self) -> int:
        return max(0, self.max_uses - self.used_count)


@dataclass(frozen=True)
class GenerationLaunchGuardDecision:
    """Result of evaluating current launch settings against a project baseline."""

    policy: GenerationLaunchGuardPolicy
    status: str = "no_baseline"
    allowed: bool = True
    requires_acknowledgement: bool = False
    summary: str = "No project launch baseline is configured."
    comparison: GenerationLaunchReceiptComparison | None = None
    protected_changes: tuple[GenerationLaunchReceiptChange, ...] = field(
        default_factory=tuple
    )
    approval: GenerationLaunchGuardApproval | None = None

    @property
    def critical_count(self) -> int:
        return sum(item.severity == "critical" for item in self.protected_changes)

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "warning" for item in self.protected_changes)

    @property
    def information_count(self) -> int:
        return sum(item.severity == "info" for item in self.protected_changes)
