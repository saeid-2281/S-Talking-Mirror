from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderStatusState:
    provider: str
    connection_state: str
    account_tier: str = "—"
    remaining_quota: int | None = None
    selected_voice: str = ""
    selected_model: str = ""
    model_availability: str = "unknown"
    voice_accessibility: str = "unknown"
    last_catalog_refresh: str = "not refreshed"


@dataclass(frozen=True)
class ReleaseReadinessState:
    version: str
    release_channel: str
    branch: str
    dirty: bool
    compile_status: str
    test_count: int
    ruff_status: str
    database_status: str
    migration_status: str
    csv_source_status: str
    valid_rows: int
    rejected_rows: int
    preflight_status: str
    provider_status: ProviderStatusState
    latest_report: Path | None
    latest_diagnostics: Path | None
    temporary_file_status: str
    secret_redaction_status: str
    artifact_folder: Path

    @property
    def ready(self) -> bool:
        return (
            self.compile_status == "passed"
            and self.ruff_status == "passed"
            and self.database_status == "passed"
            and self.migration_status == "passed"
            and self.rejected_rows == 0
            and self.secret_redaction_status == "passed"
        )
