from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GenerationOutputManifestEntry:
    """One secret-free planned-versus-actual output record."""

    row_number: int
    filename: str
    expected_path: str
    actual_path: str = ""
    disposition: str = "missing"
    job_status: str = "pending"
    existed_before: bool = False
    exists_after: bool = False
    size_bytes: int = 0
    sha256: str = ""
    modified_at: str = ""
    provider: str = ""
    model_id: str = ""
    voice_id: str = ""
    retry_count: int = 0
    duration_seconds: float = 0.0
    error_code: str = ""
    error_fingerprint: str = ""

    @property
    def requires_attention(self) -> bool:
        return self.disposition in {"failed", "missing", "incomplete", "unexpected"}


@dataclass(frozen=True)
class GenerationExecutionReceipt:
    """Integrity-protected receipt describing what a run actually produced."""

    path: Path
    markdown_path: Path
    manifest_csv_path: Path
    schema_version: int = 1
    receipt_id: str = ""
    created_at: str = ""
    run_id: str = ""
    status: str = "unknown"
    project_name: str = ""
    project_id: int | None = None
    project_key: str = ""
    launch_receipt_id: str = ""
    launch_receipt_path: str = ""
    execution_session_path: str = ""
    decision_trace_id: str = ""
    guard_approval_id: str = ""
    provider: str = ""
    model_id: str = ""
    voice_id: str = ""
    output_directory: str = ""
    report_path: str = ""
    started_at: str = ""
    finished_at: str = ""
    elapsed_seconds: float = 0.0
    planned_files: int = 0
    planned_characters: int = 0
    planned_requests: int = 0
    planned_existing_outputs: int = 0
    actual_outputs: int = 0
    created_outputs: int = 0
    overwritten_outputs: int = 0
    skipped_outputs: int = 0
    failed_outputs: int = 0
    missing_outputs: int = 0
    incomplete_outputs: int = 0
    unexpected_outputs: int = 0
    total_bytes: int = 0
    entries: tuple[GenerationOutputManifestEntry, ...] = field(default_factory=tuple)
    integrity_status: str = "verified"
    integrity_message: str = "Execution receipt integrity verified."

    @property
    def variance_files(self) -> int:
        return self.actual_outputs - self.planned_files

    @property
    def requires_attention(self) -> bool:
        return (
            self.integrity_status in {"mismatch", "unreadable"}
            or self.status in {"partial", "failed", "cancelled"}
            or self.failed_outputs > 0
            or self.missing_outputs > 0
            or self.incomplete_outputs > 0
            or self.unexpected_outputs > 0
        )


@dataclass(frozen=True)
class GenerationExecutionReceiptSummary:
    total_count: int = 0
    completed_count: int = 0
    partial_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0
    integrity_issue_count: int = 0
    planned_files: int = 0
    actual_outputs: int = 0
    created_outputs: int = 0
    overwritten_outputs: int = 0
    skipped_outputs: int = 0
    failed_outputs: int = 0
    missing_outputs: int = 0
    unexpected_outputs: int = 0
    total_bytes: int = 0
