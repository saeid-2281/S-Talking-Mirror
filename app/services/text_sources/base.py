from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class TextDocumentReader(ABC):
    """Reads one document format and returns normalized plain text."""

    extensions: frozenset[str] = frozenset()

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    @abstractmethod
    def read(self, path: Path) -> str:
        """Return plain text or raise ValueError for an invalid document."""
