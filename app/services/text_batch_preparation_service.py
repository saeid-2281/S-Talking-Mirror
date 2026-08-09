from __future__ import annotations

import re
from pathlib import Path

from app.models.text_batch_preparation import (
    TextBatchPreparationResult,
    TextBatchPreparationSnapshot,
    TextPreparationStage,
)
from app.services.text_source_service import TextSourceEntry, TextSourceService
from app.services.text_studio_quality import (
    TextStudioQualitySummary,
    analyze_text_studio_entries,
    normalize_reading_text,
)

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class TextBatchPreparationService:
    """Pure preparation decisions and safe batch transforms for Text Studio."""

    def __init__(self, text_source_service: TextSourceService | None = None) -> None:
        self.text_source_service = text_source_service or TextSourceService()

    def evaluate(
        self,
        entries: list[TextSourceEntry],
        *,
        enabled: list[bool] | None = None,
        selected_rows: list[int] | None = None,
        source_count: int = 0,
        max_characters: int = 0,
        quality: TextStudioQualitySummary | None = None,
    ) -> TextBatchPreparationSnapshot:
        states = self._states(entries, enabled)
        summary = quality or analyze_text_studio_entries(
            entries,
            enabled=states,
            max_characters=max_characters,
        )
        selected = len({row for row in selected_rows or [] if 0 <= row < len(entries)})
        safe_fix_count = (
            summary.whitespace_issues
            + summary.oversized_chunks
            + summary.duplicate_filenames
            + summary.invalid_filenames
        )

        if summary.enabled_jobs == 0:
            next_action = "add-source"
            next_label = "Add or paste source"
            next_detail = "Start with manual text or one or more supported documents."
            tone = "neutral"
        elif safe_fix_count:
            next_action = "safe-prepare"
            next_label = "Safe prepare enabled"
            next_detail = (
                f"Apply {safe_fix_count:,} non-destructive preparation fix(es) without removing duplicate text."
            )
            tone = "error" if summary.blocking_issues else "warning"
        elif summary.duplicate_texts:
            next_action = "review-duplicates"
            next_label = "Review duplicate text"
            next_detail = (
                f"{summary.duplicate_texts:,} enabled row(s) duplicate text. Removal stays a manual decision."
            )
            tone = "warning"
        elif summary.ready_for_import:
            next_action = "queue"
            next_label = "Review & add to queue"
            next_detail = "Preparation checks passed. Continue to Source Import Review before queue replacement."
            tone = "success"
        else:
            next_action = "review-quality"
            next_label = "Review preparation issues"
            next_detail = summary.status_text
            tone = summary.tone

        stages = (
            TextPreparationStage(
                "input",
                "Input",
                "pass" if source_count > 0 or entries else "pending",
                f"{source_count:,} active source input(s)" if source_count else "Paste text or add documents",
            ),
            TextPreparationStage(
                "structure",
                "Structure",
                "warning" if summary.oversized_chunks else ("pass" if summary.enabled_jobs else "pending"),
                (
                    f"{summary.oversized_chunks:,} oversized chunk(s)"
                    if summary.oversized_chunks
                    else f"{summary.enabled_jobs:,} enabled chunk(s)"
                ),
            ),
            TextPreparationStage(
                "quality",
                "Quality",
                "block" if summary.blocking_issues else ("warning" if summary.warnings else ("pass" if summary.enabled_jobs else "pending")),
                (
                    f"{summary.blocking_issues:,} blocker(s) · {summary.warnings:,} warning(s)"
                    if summary.enabled_jobs
                    else "Waiting for enabled jobs"
                ),
            ),
            TextPreparationStage(
                "batch",
                "Batch",
                "pass" if summary.enabled_jobs else "pending",
                (
                    f"{selected:,} selected · {summary.enabled_jobs:,} enabled · {len(entries) - summary.enabled_jobs:,} disabled"
                    if entries
                    else "No prepared rows"
                ),
            ),
            TextPreparationStage(
                "queue",
                "Queue",
                "pass" if summary.ready_for_import else "pending",
                "Ready for import review" if summary.ready_for_import else "Complete preparation checks first",
            ),
        )
        return TextBatchPreparationSnapshot(
            total_jobs=len(entries),
            enabled_jobs=summary.enabled_jobs,
            disabled_jobs=max(0, len(entries) - summary.enabled_jobs),
            characters=summary.characters,
            source_count=max(0, int(source_count)),
            selected_rows=selected,
            blocking_issues=summary.blocking_issues,
            warnings=summary.warnings,
            duplicate_texts=summary.duplicate_texts,
            oversized_chunks=summary.oversized_chunks,
            whitespace_issues=summary.whitespace_issues,
            safe_fix_count=safe_fix_count,
            ready_for_queue=summary.ready_for_import,
            next_action=next_action,
            next_label=next_label,
            next_detail=next_detail,
            tone=tone,
            stages=stages,
        )

    def safe_prepare(
        self,
        entries: list[TextSourceEntry],
        *,
        enabled: list[bool] | None = None,
        max_characters: int = 0,
        default_extension: str = ".mp3",
    ) -> TextBatchPreparationResult:
        states = self._states(entries, enabled)
        prepared: list[TextSourceEntry] = []
        prepared_states: list[bool] = []
        normalized_jobs = 0
        split_jobs = 0
        generated_jobs = 0

        for row, entry in enumerate(entries):
            is_enabled = states[row]
            if not is_enabled:
                prepared.append(entry)
                prepared_states.append(False)
                continue

            normalized = normalize_reading_text(entry.text)
            if normalized and normalized != entry.text:
                normalized_jobs += 1
            text = normalized or entry.text
            chunks = [text]
            if max_characters > 0 and len(text) > max_characters:
                chunks = self.text_source_service.split_text(
                    text,
                    "smart",
                    max_characters=max_characters,
                ) or [text]
            if len(chunks) > 1:
                split_jobs += 1
                generated_jobs += len(chunks) - 1
                stem = Path(entry.filename).stem or "text"
                suffix = Path(entry.filename).suffix or self._normalize_extension(default_extension)
                width = max(3, len(str(len(chunks))))
                for index, chunk in enumerate(chunks, start=1):
                    prepared.append(
                        TextSourceEntry(
                            chunk,
                            f"{stem}-part-{index:0{width}d}{suffix}",
                            entry.source_label,
                        )
                    )
                    prepared_states.append(True)
            else:
                prepared.append(TextSourceEntry(text, entry.filename, entry.source_label))
                prepared_states.append(True)

        repaired_entries, repaired_filenames = self._repair_enabled_filenames(
            prepared,
            prepared_states,
            default_extension=default_extension,
        )
        return TextBatchPreparationResult(
            entries=tuple(repaired_entries),
            enabled=tuple(prepared_states),
            normalized_jobs=normalized_jobs,
            split_jobs=split_jobs,
            generated_jobs=generated_jobs,
            repaired_filenames=repaired_filenames,
        )

    @staticmethod
    def _states(entries: list[TextSourceEntry], enabled: list[bool] | None) -> list[bool]:
        states = list(enabled or [True] * len(entries))
        if len(states) < len(entries):
            states.extend([True] * (len(entries) - len(states)))
        return [bool(value) for value in states[: len(entries)]]

    @staticmethod
    def _normalize_extension(value: str) -> str:
        extension = str(value or ".mp3").strip() or ".mp3"
        return extension if extension.startswith(".") else f".{extension}"

    def _repair_enabled_filenames(
        self,
        entries: list[TextSourceEntry],
        enabled: list[bool],
        *,
        default_extension: str,
    ) -> tuple[list[TextSourceEntry], int]:
        updated = list(entries)
        used: set[str] = set()
        repaired = 0
        fallback_extension = self._normalize_extension(default_extension)
        for row, entry in enumerate(entries):
            if not enabled[row]:
                continue
            original = entry.filename
            filename = self._safe_filename(original, fallback_extension)
            candidate = filename
            path = Path(filename)
            index = 2
            while candidate.casefold() in used:
                candidate = f"{path.stem}-{index}{path.suffix}"
                index += 1
            used.add(candidate.casefold())
            if candidate != original:
                repaired += 1
                updated[row] = TextSourceEntry(entry.text, candidate, entry.source_label)
        return updated, repaired

    @staticmethod
    def _safe_filename(value: str, default_extension: str) -> str:
        raw = Path(str(value or "").strip()).name
        cleaned = _INVALID_FILENAME.sub("-", raw)
        cleaned = re.sub(r"\s+", "-", cleaned)
        cleaned = re.sub(r"-+", "-", cleaned).strip("-. ")
        path = Path(cleaned or f"text{default_extension}")
        stem = path.stem.strip("-. ") or "text"
        suffix = path.suffix or default_extension
        return f"{stem}{suffix}"
