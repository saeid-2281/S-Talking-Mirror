from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.text_source_service import TextSourceEntry


@dataclass(frozen=True)
class TextPreparationStage:
    code: str
    title: str
    status: str
    detail: str


@dataclass(frozen=True)
class TextBatchPreparationSnapshot:
    total_jobs: int
    enabled_jobs: int
    disabled_jobs: int
    characters: int
    source_count: int
    selected_rows: int
    blocking_issues: int
    warnings: int
    duplicate_texts: int
    oversized_chunks: int
    whitespace_issues: int
    safe_fix_count: int
    ready_for_queue: bool
    next_action: str
    next_label: str
    next_detail: str
    tone: str
    stages: tuple[TextPreparationStage, ...]


@dataclass(frozen=True)
class TextBatchPreparationResult:
    entries: tuple[TextSourceEntry, ...]
    enabled: tuple[bool, ...]
    normalized_jobs: int
    split_jobs: int
    generated_jobs: int
    repaired_filenames: int
