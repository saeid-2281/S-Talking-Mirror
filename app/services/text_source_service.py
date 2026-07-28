from __future__ import annotations

import csv
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.text_sources import ClipboardReader, TextReaderFactory
from app.services.text_sources.common import clean_text

_DEFAULT_FACTORY = TextReaderFactory()
SUPPORTED_TEXT_EXTENSIONS = _DEFAULT_FACTORY.supported_extensions


@dataclass(frozen=True)
class TextSourceEntry:
    text: str
    filename: str
    source_label: str = "Manual text"

    @property
    def character_count(self) -> int:
        return len(self.text)


class TextSourceService:
    """Creates queue-ready rows from manual text and supported documents.

    Format-specific parsing is delegated to independent readers. This keeps the
    import workflow stable while allowing new document formats to be added
    without expanding this service into another monolith.
    """

    def __init__(
        self,
        reader_factory: TextReaderFactory | None = None,
        clipboard_reader: ClipboardReader | None = None,
    ) -> None:
        self.reader_factory = reader_factory or TextReaderFactory()
        self.clipboard_reader = clipboard_reader or ClipboardReader()

    @property
    def supported_extensions(self) -> frozenset[str]:
        return self.reader_factory.supported_extensions

    def entries_from_manual(
        self,
        text: str,
        *,
        split_mode: str = "single",
        filename_prefix: str = "manual",
        start_index: int = 1,
        extension: str = ".mp3",
    ) -> list[TextSourceEntry]:
        chunks = self.split_text(self.clipboard_reader.read_value(text), split_mode)
        return self._entries(chunks, filename_prefix, start_index, extension, "Manual text")

    def entries_from_files(
        self,
        paths: list[Path],
        *,
        split_mode: str = "file",
        filename_prefix: str = "",
        start_index: int = 1,
        extension: str = ".mp3",
    ) -> list[TextSourceEntry]:
        entries: list[TextSourceEntry] = []
        next_index = start_index
        for raw_path in paths:
            path = Path(raw_path)
            text = self.read_text_file(path)
            mode = "single" if split_mode == "file" else split_mode
            chunks = self.split_text(text, mode)
            prefix = filename_prefix.strip() or self._safe_stem(path.stem)
            file_entries = self._entries(chunks, prefix, next_index, extension, path.name)
            entries.extend(file_entries)
            next_index += len(file_entries)
        return entries

    def write_normalized_csv(self, entries: list[TextSourceEntry], destination_dir: Path, *, label: str) -> Path:
        if not entries:
            raise ValueError("At least one non-empty text entry is required.")
        destination_dir.mkdir(parents=True, exist_ok=True)
        safe_label = self._safe_stem(label) or "text-source"
        path = destination_dir / f"{safe_label}-{uuid.uuid4().hex[:10]}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["text", "filename", "source_label"])
            writer.writeheader()
            for entry in entries:
                writer.writerow(
                    {
                        "text": entry.text,
                        "filename": entry.filename,
                        "source_label": entry.source_label,
                    }
                )
        return path

    def read_text_file(self, path: Path) -> str:
        return clean_text(self.reader_factory.read(Path(path)))

    @staticmethod
    def split_text(text: str, mode: str) -> list[str]:
        cleaned = clean_text(text)
        if not cleaned:
            return []
        if mode in {"single", "file"}:
            chunks = [cleaned]
        elif mode == "paragraphs":
            chunks = re.split(r"\n\s*\n+", cleaned)
        elif mode == "lines":
            chunks = cleaned.splitlines()
        elif mode == "sentences":
            chunks = re.split(r"(?<=[.!?…])\s+(?=[^\s])", cleaned)
        else:
            raise ValueError(f"Unknown split mode: {mode}")
        return [chunk.strip() for chunk in chunks if chunk.strip()]

    @staticmethod
    def _entries(
        chunks: list[str],
        prefix: str,
        start_index: int,
        extension: str,
        source_label: str,
    ) -> list[TextSourceEntry]:
        safe_prefix = TextSourceService._safe_stem(prefix) or "text"
        normalized_extension = extension if extension.startswith(".") else f".{extension}"
        width = max(3, len(str(start_index + max(len(chunks) - 1, 0))))
        return [
            TextSourceEntry(
                text=chunk,
                filename=f"{safe_prefix}-{index:0{width}d}{normalized_extension}",
                source_label=source_label,
            )
            for index, chunk in enumerate(chunks, start=start_index)
        ]

    @staticmethod
    def _safe_stem(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value.strip())
        cleaned = re.sub(r"\s+", "-", cleaned)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-. ")
        return cleaned or "text"
