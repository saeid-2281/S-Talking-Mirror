from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DocumentSection:
    """One selectable logical unit from an imported document."""

    section_id: str
    label: str
    text: str
    source_path: Path
    index: int = 0

    @property
    def character_count(self) -> int:
        return len(self.text)

    @property
    def selection_key(self) -> str:
        return f"{self.source_path.resolve()}|{self.section_id}"
