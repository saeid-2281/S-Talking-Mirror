from __future__ import annotations

import csv
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.services.text_sources import ClipboardReader, DocumentSection, TextReaderFactory
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


@dataclass(frozen=True)
class TextStudioMetrics:
    jobs: int
    characters: int
    estimated_seconds: float
    estimated_cost: float


class TextSourceService:
    """Creates queue-ready rows from manual text and supported documents.

    Format-specific parsing is delegated to independent readers. The facade
    owns chunking, filename generation, estimates and normalized CSV output.
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
        max_characters: int = 0,
    ) -> list[TextSourceEntry]:
        chunks = self.split_text(
            self.clipboard_reader.read_value(text),
            split_mode,
            max_characters=max_characters,
        )
        return self._entries(chunks, filename_prefix, start_index, extension, "Manual text")

    def entries_from_files(
        self,
        paths: list[Path],
        *,
        split_mode: str = "file",
        filename_prefix: str = "",
        start_index: int = 1,
        extension: str = ".mp3",
        max_characters: int = 0,
    ) -> list[TextSourceEntry]:
        entries: list[TextSourceEntry] = []
        next_index = start_index
        for raw_path in paths:
            path = Path(raw_path)
            text = self.read_text_file(path)
            mode = "single" if split_mode == "file" else split_mode
            chunks = self.split_text(text, mode, max_characters=max_characters)
            prefix = filename_prefix.strip() or self._safe_stem(path.stem)
            file_entries = self._entries(chunks, prefix, next_index, extension, path.name)
            entries.extend(file_entries)
            next_index += len(file_entries)
        return entries


    def document_sections(self, path: Path) -> list[DocumentSection]:
        """Return selectable document units, falling back to one whole-document section."""
        path = Path(path)
        reader = self.reader_factory.reader_for(path)
        read_sections = getattr(reader, "read_sections", None)
        if callable(read_sections):
            return list(read_sections(path))
        text = clean_text(reader.read(path))
        if not text:
            return []
        return [DocumentSection("document", path.name, text, path, 1)]

    def entries_from_sections(
        self,
        sections: list[DocumentSection],
        *,
        split_mode: str = "smart",
        filename_prefix: str = "",
        start_index: int = 1,
        extension: str = ".mp3",
        max_characters: int = 0,
    ) -> list[TextSourceEntry]:
        entries: list[TextSourceEntry] = []
        next_index = start_index
        for section in sections:
            mode = "single" if split_mode == "file" else split_mode
            chunks = self.split_text(section.text, mode, max_characters=max_characters)
            prefix = filename_prefix.strip() or self._safe_stem(section.source_path.stem)
            section_entries = self._entries(
                chunks, prefix, next_index, extension, f"{section.source_path.name} · {section.label}"
            )
            entries.extend(section_entries)
            next_index += len(section_entries)
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
    def metrics(
        entries: list[TextSourceEntry],
        *,
        characters_per_minute: int = 900,
        price_per_million_characters: float = 0.0,
    ) -> TextStudioMetrics:
        characters = sum(entry.character_count for entry in entries)
        speed = max(1, characters_per_minute)
        return TextStudioMetrics(
            jobs=len(entries),
            characters=characters,
            estimated_seconds=(characters / speed) * 60.0,
            estimated_cost=(characters / 1_000_000.0) * max(0.0, price_per_million_characters),
        )

    @staticmethod
    def split_text(text: str, mode: str, *, max_characters: int = 0) -> list[str]:
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
        elif mode == "smart":
            chunks = TextSourceService._smart_chunks(cleaned, max_characters or 1200)
        else:
            raise ValueError(f"Unknown split mode: {mode}")

        normalized = [chunk.strip() for chunk in chunks if chunk.strip()]
        if max_characters > 0 and mode != "smart":
            expanded: list[str] = []
            for chunk in normalized:
                expanded.extend(TextSourceService._split_long_chunk(chunk, max_characters))
            normalized = expanded
        return normalized

    @staticmethod
    def _smart_chunks(text: str, max_characters: int) -> list[str]:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n+", text) if item.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            for part in TextSourceService._split_long_chunk(paragraph, max_characters):
                candidate = f"{current}\n\n{part}".strip() if current else part
                if current and len(candidate) > max_characters:
                    chunks.append(current)
                    current = part
                else:
                    current = candidate
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _split_long_chunk(text: str, max_characters: int) -> list[str]:
        if max_characters <= 0 or len(text) <= max_characters:
            return [text]
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[.!?…])\s+(?=[^\s])", text)
            if item.strip()
        ]
        if len(sentences) == 1:
            return [text[index : index + max_characters].strip() for index in range(0, len(text), max_characters)]

        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            if len(sentence) > max_characters:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(
                    sentence[index : index + max_characters].strip()
                    for index in range(0, len(sentence), max_characters)
                )
                continue
            candidate = f"{current} {sentence}".strip() if current else sentence
            if current and len(candidate) > max_characters:
                chunks.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            chunks.append(current)
        return [chunk for chunk in chunks if chunk]

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
