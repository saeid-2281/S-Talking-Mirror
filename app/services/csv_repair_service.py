from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.csv_loader import ENCODINGS, FILENAME_EXT, INVALID_WINDOWS, diagnose_csv, file_sha256
from app.exceptions import CSVValidationError
from app.models import CsvImportIssue, CsvImportState

RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class FilenamePattern:
    prefix: str = ""
    width: int = 0
    extension: str = ".mp3"
    confidence: str = "low"


@dataclass(frozen=True)
class RepairValidation:
    valid: bool
    problems: tuple[str, ...] = ()


@dataclass
class RejectedRowRepair:
    physical_row: int
    raw_row_excerpt: str
    text: str
    old_filename: str
    filename: str
    issue_codes: list[str]
    validation: RepairValidation = field(default_factory=lambda: RepairValidation(False, ("Unresolved.",)))
    method: str = "manual"


@dataclass(frozen=True)
class BatchPreviewRow:
    physical_row: int
    old_filename: str
    proposed_filename: str
    conflict: str


@dataclass(frozen=True)
class RepairAuditEntry:
    physical_row: int
    old_filename: str
    new_filename: str
    repair_method: str
    timestamp: str


@dataclass(frozen=True)
class RepairSaveResult:
    repaired_csv_path: Path
    repaired_hash: str
    audit_json_path: Path
    audit_csv_path: Path
    diagnostics: CsvImportState


class CsvRepairSession:
    def __init__(self, state: CsvImportState, *, project_name: str = "No project", project: str = "") -> None:
        self.state = state
        self.project_name = project_name or "No project"
        self.project = project or _safe_stem(self.project_name)
        self.source_hash = file_sha256(state.source_path)
        self.headers, self.original_rows = _read_rows(state)
        self.filename_index = state.header_names.index("filename") if "filename" in state.header_names else 0
        self.text_index = state.header_names.index("text") if "text" in state.header_names else 1
        self.valid_by_row = {job.row_number: job for job in state.jobs}
        self.repairs = self._build_repairs()
        self.undo_stack: list[dict[int, tuple[str, str, str]]] = []
        self.redo_stack: list[dict[int, tuple[str, str, str]]] = []
        self.audit_entries: list[RepairAuditEntry] = []
        self._validate_all()

    @property
    def unresolved_count(self) -> int:
        return sum(1 for repair in self.repairs if not repair.validation.valid)

    @property
    def high_confidence_suggestion_count(self) -> int:
        return sum(1 for repair in self.repairs if self.suggest_from_neighbors(repair.physical_row)[1].confidence == "high")

    def pattern_for_row(self, physical_row: int) -> FilenamePattern:
        neighbors = self._neighbor_filenames(physical_row)
        return detect_filename_pattern(neighbors)

    def suggest_from_neighbors(self, physical_row: int) -> tuple[str, FilenamePattern]:
        sequence = self._sequence_suggestion(physical_row)
        if sequence is not None:
            return sequence
        pattern = self.pattern_for_row(physical_row)
        if pattern.confidence == "low":
            return self.suggest_from_row_number(physical_row), pattern
        return f"{pattern.prefix}{physical_row:0{pattern.width}d}{pattern.extension}", pattern

    def suggest_from_row_number(self, physical_row: int, template: str = "row-{row:04d}{ext}") -> str:
        pattern = self.pattern_for_row(physical_row)
        extension = pattern.extension or ".mp3"
        return expand_filename_template(
            template,
            row=physical_row,
            index=self._repair_index(physical_row) + 1,
            project=self.project,
            original_stem=_safe_stem(self.state.source_path.stem),
            ext=extension,
        )

    def copy_pattern_from_previous(self, physical_row: int) -> str:
        previous = self._nearest_valid_filename(physical_row, -1)
        return increment_numeric_suffix(previous) if previous else self.suggest_from_row_number(physical_row)

    def copy_pattern_from_next(self, physical_row: int) -> str:
        next_filename = self._nearest_valid_filename(physical_row, 1)
        return decrement_numeric_suffix(next_filename) if next_filename else self.suggest_from_row_number(physical_row)

    def update_repair(self, physical_row: int, *, text: str | None = None, filename: str | None = None, method: str = "manual") -> None:
        repair = self._repair_for_row(physical_row)
        self._push_undo([repair])
        if text is not None:
            repair.text = text
        if filename is not None:
            repair.filename = filename
        repair.method = method
        self.redo_stack.clear()
        self._validate_all()

    def batch_preview(
        self,
        rows: list[int],
        *,
        template: str = "{project}-{index:03d}{ext}",
        start: int = 1,
        prefix: str = "",
        suffix: str = "",
        extension: str = ".mp3",
    ) -> list[BatchPreviewRow]:
        proposed: list[tuple[RejectedRowRepair, str]] = []
        for offset, physical_row in enumerate(rows):
            repair = self._repair_for_row(physical_row)
            filename = expand_filename_template(
                template,
                row=physical_row,
                index=start + offset,
                project=self.project,
                original_stem=_safe_stem(self.state.source_path.stem),
                ext=extension,
            )
            if prefix or suffix:
                stem = Path(filename).stem
                filename = f"{prefix}{stem}{suffix}{extension}"
            proposed.append((repair, filename))
        return self._preview(proposed)

    def apply_batch(
        self,
        rows: list[int],
        *,
        template: str = "{project}-{index:03d}{ext}",
        start: int = 1,
        prefix: str = "",
        suffix: str = "",
        extension: str = ".mp3",
    ) -> int:
        preview = self.batch_preview(rows, template=template, start=start, prefix=prefix, suffix=suffix, extension=extension)
        conflicts = [row for row in preview if row.conflict]
        if conflicts:
            raise CSVValidationError("; ".join(f"Row {row.physical_row}: {row.conflict}" for row in conflicts))
        repairs = [self._repair_for_row(row) for row in rows]
        self._push_undo(repairs)
        for preview_row in preview:
            repair = self._repair_for_row(preview_row.physical_row)
            repair.filename = preview_row.proposed_filename
            repair.method = "batch"
        self.redo_stack.clear()
        self._validate_all()
        return len(preview)

    def undo(self) -> bool:
        if not self.undo_stack:
            return False
        snapshot = self.undo_stack.pop()
        self.redo_stack.append(self._snapshot(snapshot.keys()))
        self._restore(snapshot)
        return True

    def redo(self) -> bool:
        if not self.redo_stack:
            return False
        snapshot = self.redo_stack.pop()
        self.undo_stack.append(self._snapshot(snapshot.keys()))
        self._restore(snapshot)
        return True

    def save_repaired_csv(self, target: Path | None = None, reports_dir: Path | None = None) -> RepairSaveResult:
        self._validate_all()
        invalid = [repair for repair in self.repairs if not repair.validation.valid]
        if invalid:
            raise CSVValidationError(f"{len(invalid)} rejected row(s) still need repair.")
        target = target or self.state.source_path.with_name(f"{self.state.source_path.stem}.repaired.csv")
        target.parent.mkdir(parents=True, exist_ok=True)
        rows_by_physical: dict[int, dict[str, str]] = {}
        for job in self.state.jobs:
            rows_by_physical[job.row_number] = {"text": job.text, "filename": job.filename}
        for repair in self.repairs:
            rows_by_physical[repair.physical_row] = {"text": repair.text, "filename": repair.filename}
        with target.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["text", "filename"], quoting=csv.QUOTE_ALL)
            writer.writeheader()
            for physical_row in sorted(rows_by_physical):
                writer.writerow(rows_by_physical[physical_row])
        repaired_hash = file_sha256(target)
        diagnostics = diagnose_csv(target)
        audit_dir = self._audit_dir(reports_dir)
        audit_json, audit_csv = self._write_audit(audit_dir, target, repaired_hash)
        return RepairSaveResult(target, repaired_hash, audit_json, audit_csv, diagnostics)

    def _build_repairs(self) -> list[RejectedRowRepair]:
        issue_map: dict[int, list[CsvImportIssue]] = {}
        for issue in self.state.issues:
            if issue.severity == "error" and issue.physical_row is not None:
                issue_map.setdefault(issue.physical_row, []).append(issue)
        repairs: list[RejectedRowRepair] = []
        for physical_row in sorted(issue_map):
            row = self.original_rows.get(physical_row, [])
            filename = _safe_get(row, self.filename_index)
            text = _safe_get(row, self.text_index).replace("\r\n", "\n")
            issues = issue_map[physical_row]
            repairs.append(
                RejectedRowRepair(
                    physical_row=physical_row,
                    raw_row_excerpt=issues[0].raw_row_excerpt,
                    text=text,
                    old_filename=filename,
                    filename=filename,
                    issue_codes=[issue.issue_code for issue in issues],
                )
            )
        return repairs

    def _validate_all(self) -> None:
        used = {Path(job.filename).name.casefold(): job.row_number for job in self.state.jobs}
        proposed: dict[str, int] = {}
        for repair in self.repairs:
            problems = list(validate_repair_fields(repair.text, repair.filename))
            key = Path(repair.filename).name.casefold()
            if key in used:
                problems.append("Duplicate of an existing valid filename.")
            if key in proposed and proposed[key] != repair.physical_row:
                problems.append("Duplicate of another repaired filename.")
            proposed[key] = repair.physical_row
            repair.validation = RepairValidation(not problems, tuple(problems))

    def _preview(self, proposed: list[tuple[RejectedRowRepair, str]]) -> list[BatchPreviewRow]:
        existing = {Path(job.filename).name.casefold() for job in self.state.jobs}
        seen: set[str] = set()
        rows: list[BatchPreviewRow] = []
        for repair, filename in proposed:
            problems = list(validate_repair_fields(repair.text, filename))
            key = Path(filename).name.casefold()
            if key in existing:
                problems.append("Conflicts with an existing valid filename.")
            if key in seen:
                problems.append("Duplicate in batch.")
            seen.add(key)
            rows.append(BatchPreviewRow(repair.physical_row, repair.old_filename, filename, "; ".join(problems)))
        return rows

    def _neighbor_filenames(self, physical_row: int) -> list[str]:
        names: list[str] = []
        for offset in range(1, 8):
            for row_number in (physical_row - offset, physical_row + offset):
                job = self.valid_by_row.get(row_number)
                if job:
                    names.append(job.filename)
        return names

    def _nearest_valid_filename(self, physical_row: int, direction: int) -> str | None:
        for offset in range(1, 50):
            job = self.valid_by_row.get(physical_row + (offset * direction))
            if job:
                return job.filename
        return None

    def _sequence_suggestion(self, physical_row: int) -> tuple[str, FilenamePattern] | None:
        groups: dict[tuple[str, str, int], list[tuple[int, int]]] = {}
        for offset in range(1, 8):
            for row_number in (physical_row - offset, physical_row + offset):
                job = self.valid_by_row.get(row_number)
                parsed = parse_numbered_filename(job.filename) if job else None
                if parsed is None:
                    continue
                prefix, number, width, extension = parsed
                groups.setdefault((prefix, extension, width), []).append((row_number, number))
        candidates: list[tuple[int, str, FilenamePattern]] = []
        for (prefix, extension, width), values in groups.items():
            if len(values) < 2:
                continue
            constants = {number - row_number for row_number, number in values}
            if len(constants) != 1:
                continue
            number = constants.pop() + physical_row
            if number < 0:
                continue
            distance = min(abs(row_number - physical_row) for row_number, _number in values)
            candidates.append((distance, f"{prefix}{number:0{width}d}{extension}", FilenamePattern(prefix, width, extension, "high")))
        if not candidates:
            return None
        _distance, filename, pattern = sorted(candidates, key=lambda item: item[0])[0]
        return filename, pattern

    def _repair_for_row(self, physical_row: int) -> RejectedRowRepair:
        for repair in self.repairs:
            if repair.physical_row == physical_row:
                return repair
        raise CSVValidationError(f"Rejected row not found: {physical_row}")

    def _repair_index(self, physical_row: int) -> int:
        for index, repair in enumerate(self.repairs):
            if repair.physical_row == physical_row:
                return index
        return 0

    def _push_undo(self, repairs: list[RejectedRowRepair]) -> None:
        self.undo_stack.append(self._snapshot(repair.physical_row for repair in repairs))

    def _snapshot(self, rows: object) -> dict[int, tuple[str, str, str]]:
        return {row: (repair.text, repair.filename, repair.method) for row in rows if (repair := self._repair_for_row(row))}

    def _restore(self, snapshot: dict[int, tuple[str, str, str]]) -> None:
        for row, (text, filename, method) in snapshot.items():
            repair = self._repair_for_row(row)
            repair.text = text
            repair.filename = filename
            repair.method = method
        self._validate_all()

    def _audit_dir(self, reports_dir: Path | None) -> Path:
        root = reports_dir or self.state.source_path.parent / "reports"
        report_dir = root / _safe_stem(self.project_name) / "imports" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir

    def _write_audit(self, audit_dir: Path, repaired_path: Path, repaired_hash: str) -> tuple[Path, Path]:
        timestamp = datetime.now().isoformat(timespec="seconds")
        entries = [
            RepairAuditEntry(repair.physical_row, repair.old_filename, repair.filename, repair.method, timestamp)
            for repair in self.repairs
        ]
        payload = {
            "source_path": str(self.state.source_path),
            "repaired_csv_path": str(repaired_path),
            "original_source_hash": self.source_hash,
            "repaired_file_hash": repaired_hash,
            "repaired_physical_rows": [entry.physical_row for entry in entries],
            "entries": [entry.__dict__ for entry in entries],
        }
        json_path = audit_dir / "repair-audit.json"
        csv_path = audit_dir / "repair-audit.csv"
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["physical_row", "old_filename", "new_filename", "repair_method", "timestamp"])
            writer.writeheader()
            for entry in entries:
                writer.writerow(entry.__dict__)
        return json_path, csv_path


def detect_filename_pattern(filenames: list[str]) -> FilenamePattern:
    matches: list[re.Match[str]] = []
    for filename in filenames:
        parsed = NUMBERED_FILENAME.match(Path(filename).name)
        if parsed and FILENAME_EXT.search(filename):
            matches.append(parsed)
    if not matches:
        return FilenamePattern()
    prefixes = [match.group("prefix") for match in matches]
    extensions = [match.group("ext") for match in matches]
    widths = [len(match.group("number")) for match in matches]
    prefix = _mode(prefixes)
    extension = _mode(extensions)
    width = int(_mode([str(width) for width in widths]))
    confidence = "high" if len(matches) >= 2 and prefixes.count(prefix) >= 2 and extensions.count(extension) >= 2 else "medium"
    return FilenamePattern(prefix, width, extension, confidence)


def increment_numeric_suffix(filename: str) -> str:
    return _shift_numeric_suffix(filename, 1)


def decrement_numeric_suffix(filename: str) -> str:
    return _shift_numeric_suffix(filename, -1)


def expand_filename_template(template: str, *, row: int, index: int, project: str, original_stem: str, ext: str) -> str:
    extension = ext if ext.startswith(".") else f".{ext}"
    return template.format(row=row, index=index, project=_safe_stem(project), original_stem=_safe_stem(original_stem), ext=extension)


def validate_repair_fields(text: str, filename: str, *, output_dir: Path | None = None) -> tuple[str, ...]:
    problems: list[str] = []
    value = filename.strip()
    basename = Path(value).name
    stem = Path(basename).stem.upper()
    if not text.strip():
        problems.append("Text is empty.")
    if not value:
        problems.append("Filename is empty.")
    if value != basename:
        problems.append("Filename must be a basename without folders.")
    if ".." in Path(value).parts:
        problems.append("Filename must not contain path traversal.")
    if INVALID_WINDOWS.search(basename):
        problems.append("Filename contains invalid Windows characters.")
    if basename.rstrip(" .") != basename:
        problems.append("Filename must not end with a space or dot.")
    if stem in RESERVED_WINDOWS_NAMES:
        problems.append("Filename uses a reserved Windows name.")
    if not FILENAME_EXT.search(basename):
        problems.append("Filename has an unsupported extension.")
    if output_dir and len(str((output_dir / basename).resolve())) > 240:
        problems.append("Output path is too long.")
    return tuple(problems)


NUMBERED_FILENAME = re.compile(r"^(?P<prefix>.*?)(?P<number>\d+)(?P<ext>\.[^.]+)$")


def parse_numbered_filename(filename: str) -> tuple[str, int, int, str] | None:
    match = NUMBERED_FILENAME.match(Path(filename).name)
    if not match or not FILENAME_EXT.search(filename):
        return None
    number = match.group("number")
    return match.group("prefix"), int(number), len(number), match.group("ext")


def _read_rows(state: CsvImportState) -> tuple[list[str], dict[int, list[str]]]:
    text = _decode_source(state.source_path, state.detected_encoding)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=state.detected_delimiter)
    rows = list(reader)
    headers = [(header or "").strip().lower() for header in rows[0]] if rows else []
    return headers, {index: row for index, row in enumerate(rows[1:], start=2)}


def _decode_source(path: Path, preferred_encoding: str) -> str:
    data = path.read_bytes()
    for encoding in [preferred_encoding, *ENCODINGS]:
        if not encoding:
            continue
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CSVValidationError("CSV could not be decoded.")


def _safe_get(row: list[str], index: int) -> str:
    return row[index] if 0 <= index < len(row) else ""


def _shift_numeric_suffix(filename: str, delta: int) -> str:
    match = re.match(r"^(?P<prefix>.*?)(?P<number>\d+)(?P<ext>\.[^.]+)$", Path(filename).name)
    if not match:
        return filename
    number = max(0, int(match.group("number")) + delta)
    return f"{match.group('prefix')}{number:0{len(match.group('number'))}d}{match.group('ext')}"


def _mode(values: list[str]) -> str:
    return max(set(values), key=values.count)


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', "-", value).strip("- .")
    return cleaned or "project"
