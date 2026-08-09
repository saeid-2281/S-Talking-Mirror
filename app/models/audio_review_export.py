from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AudioReviewItem:
    row_number: int
    filename: str
    path: Path
    job_status: str
    review_status: str
    size_bytes: int = 0

    @property
    def ready(self) -> bool:
        return self.review_status == "ready"


@dataclass(frozen=True)
class AudioReviewSummary:
    items: tuple[AudioReviewItem, ...] = ()
    ready: int = 0
    missing: int = 0
    failed: int = 0
    pending: int = 0

    @property
    def total(self) -> int:
        return len(self.items)


@dataclass(frozen=True)
class AudioExportItem:
    row_number: int
    source_path: Path
    destination_path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class AudioExportReceipt:
    destination: Path
    copied: tuple[AudioExportItem, ...] = ()
    skipped_missing: int = 0
    collisions_resolved: int = 0
    manifest_path: Path | None = None
