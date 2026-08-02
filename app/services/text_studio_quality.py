from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from app.services.text_source_service import TextSourceEntry

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_REPEATED_SPACES = re.compile(r"[ \t]+")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class TextStudioQualityIssue:
    row: int
    code: str
    severity: str
    message: str


@dataclass(frozen=True)
class TextStudioQualitySummary:
    total_jobs: int
    enabled_jobs: int
    characters: int
    blocking_issues: int
    warnings: int
    empty_texts: int
    duplicate_filenames: int
    duplicate_texts: int
    oversized_chunks: int
    whitespace_issues: int
    invalid_filenames: int
    issues: tuple[TextStudioQualityIssue, ...]

    @property
    def ready_for_import(self) -> bool:
        return self.enabled_jobs > 0 and self.blocking_issues == 0

    @property
    def issue_rows(self) -> frozenset[int]:
        return frozenset(issue.row for issue in self.issues)

    @property
    def status_text(self) -> str:
        if not self.enabled_jobs:
            return "No enabled jobs"
        if self.blocking_issues:
            return f"Fix {self.blocking_issues:,} blocking issue(s)"
        if self.warnings:
            return f"Ready with {self.warnings:,} warning(s)"
        return "Ready for queue"

    @property
    def tone(self) -> str:
        if not self.enabled_jobs:
            return "neutral"
        if self.blocking_issues:
            return "error"
        if self.warnings:
            return "warning"
        return "success"


def normalize_reading_text(text: str) -> str:
    """Normalize accidental whitespace while preserving paragraph boundaries."""

    lines = []
    for raw_line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = _REPEATED_SPACES.sub(" ", raw_line.strip())
        lines.append(line)
    normalized = "\n".join(lines).strip()
    return _EXCESS_BLANK_LINES.sub("\n\n", normalized)


def _canonical_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


def _canonical_filename(filename: str) -> str:
    return str(filename).strip().casefold()


def analyze_text_studio_entries(
    entries: list[TextSourceEntry],
    *,
    enabled: list[bool] | None = None,
    max_characters: int = 0,
) -> TextStudioQualitySummary:
    states = list(enabled or [True] * len(entries))
    if len(states) < len(entries):
        states.extend([True] * (len(entries) - len(states)))

    enabled_rows = [row for row, state in enumerate(states[: len(entries)]) if state]
    filename_counts = Counter(
        _canonical_filename(entries[row].filename)
        for row in enabled_rows
        if entries[row].filename.strip()
    )
    text_counts = Counter(
        _canonical_text(entries[row].text)
        for row in enabled_rows
        if _canonical_text(entries[row].text)
    )

    issues: list[TextStudioQualityIssue] = []
    empty_texts = duplicate_filenames = duplicate_texts = 0
    oversized_chunks = whitespace_issues = invalid_filenames = 0

    for row in enabled_rows:
        entry = entries[row]
        text = entry.text.strip()
        filename = entry.filename.strip()
        if not text:
            empty_texts += 1
            issues.append(TextStudioQualityIssue(row, "empty-text", "error", "Text is empty."))
        canonical_filename = _canonical_filename(filename)
        if not filename or Path(filename).name != filename or _INVALID_FILENAME.search(filename):
            invalid_filenames += 1
            issues.append(
                TextStudioQualityIssue(row, "invalid-filename", "error", "Filename is missing or contains unsupported characters.")
            )
        if canonical_filename and filename_counts[canonical_filename] > 1:
            duplicate_filenames += 1
            issues.append(
                TextStudioQualityIssue(row, "duplicate-filename", "error", "Filename is duplicated in the enabled job set.")
            )
        canonical_text = _canonical_text(text)
        if canonical_text and text_counts[canonical_text] > 1:
            duplicate_texts += 1
            issues.append(
                TextStudioQualityIssue(row, "duplicate-text", "warning", "Text duplicates another enabled job.")
            )
        if max_characters > 0 and len(text) > max_characters:
            oversized_chunks += 1
            issues.append(
                TextStudioQualityIssue(
                    row,
                    "oversized",
                    "warning",
                    f"Chunk contains {len(text):,} characters; configured limit is {max_characters:,}.",
                )
            )
        if text and normalize_reading_text(text) != text:
            whitespace_issues += 1
            issues.append(
                TextStudioQualityIssue(row, "whitespace", "warning", "Whitespace can be normalized without changing words.")
            )

    blocking = empty_texts + duplicate_filenames + invalid_filenames
    warnings = duplicate_texts + oversized_chunks + whitespace_issues
    characters = sum(entries[row].character_count for row in enabled_rows)
    return TextStudioQualitySummary(
        total_jobs=len(entries),
        enabled_jobs=len(enabled_rows),
        characters=characters,
        blocking_issues=blocking,
        warnings=warnings,
        empty_texts=empty_texts,
        duplicate_filenames=duplicate_filenames,
        duplicate_texts=duplicate_texts,
        oversized_chunks=oversized_chunks,
        whitespace_issues=whitespace_issues,
        invalid_filenames=invalid_filenames,
        issues=tuple(issues),
    )


def replace_entry_text(
    entries: list[TextSourceEntry],
    *,
    find_text: str,
    replacement: str,
    rows: list[int] | None = None,
    case_sensitive: bool = False,
) -> tuple[list[TextSourceEntry], int]:
    if not find_text:
        return list(entries), 0
    selected = set(rows if rows is not None else range(len(entries)))
    updated = list(entries)
    replacements = 0
    pattern = re.compile(re.escape(find_text), 0 if case_sensitive else re.IGNORECASE)
    for row, entry in enumerate(entries):
        if row not in selected:
            continue
        text, count = pattern.subn(lambda _match: replacement, entry.text)
        if count:
            replacements += count
            updated[row] = TextSourceEntry(text=text, filename=entry.filename, source_label=entry.source_label)
    return updated, replacements


def renumber_entry_filenames(
    entries: list[TextSourceEntry],
    *,
    prefix: str,
    start_index: int,
    extension: str,
) -> list[TextSourceEntry]:
    safe_prefix = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", prefix.strip())
    safe_prefix = re.sub(r"\s+", "-", safe_prefix)
    safe_prefix = re.sub(r"-+", "-", safe_prefix).strip("-. ") or "text-studio"
    suffix = extension if extension.startswith(".") else f".{extension}"
    width = max(3, len(str(start_index + max(len(entries) - 1, 0))))
    return [
        TextSourceEntry(
            text=entry.text,
            filename=f"{safe_prefix}-{index:0{width}d}{suffix}",
            source_label=entry.source_label,
        )
        for index, entry in enumerate(entries, start=start_index)
    ]
