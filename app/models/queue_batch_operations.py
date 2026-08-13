from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueBatchGroup:
    key: str
    label: str
    job_count: int
    character_count: int


@dataclass(frozen=True)
class QueueBatchSnapshot:
    visible_jobs: int
    visible_characters: int
    selected_jobs: int
    selected_characters: int
    pending_jobs: int
    failed_jobs: int
    quota_jobs: int
    quota_characters: int
    group_by: str
    groups: tuple[QueueBatchGroup, ...]
    completed_jobs: int = 0
    lens: str = "all"
    lens_jobs: int = 0
    lens_characters: int = 0

    @property
    def lens_label(self) -> str:
        return {
            "all": "All visible",
            "pending": "Pending",
            "failed": "Failed",
            "selected": "Current selection",
            "quota": "Quota-ready",
        }.get(self.lens, "All visible")

    @property
    def lens_summary(self) -> str:
        return (
            f"{self.lens_label} · {self.lens_jobs:,} job(s) · "
            f"{self.lens_characters:,} characters"
        )

    @property
    def summary(self) -> str:
        base = (
            f"Visible {self.visible_jobs:,} · Selected {self.selected_jobs:,} · "
            f"Pending {self.pending_jobs:,} · Failed {self.failed_jobs:,}"
        )
        if self.quota_jobs:
            base += f" · Quota batch {self.quota_jobs:,}"
        return base
