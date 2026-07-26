from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from app.exceptions import CSVValidationError
from app.models import CsvImportIssue, CsvImportState, TTSJob

REQUIRED_COLUMNS = {"text", "filename"}
DELIMITERS = [",", ";", "\t"]
ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]
FILENAME_EXT = re.compile(r"\.(mp3|wav|ogg|flac|pcm|ulaw|alaw)$", re.IGNORECASE)
INVALID_WINDOWS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def load_jobs(csv_path: Path) -> list[TTSJob]:
    state = diagnose_csv(csv_path)
    if not state.jobs:
        raise CSVValidationError(_summary_error(state) or "CSV contains no importable rows.")
    if state.rejected_rows:
        raise CSVValidationError(_summary_error(state))
    return state.jobs


def load_valid_jobs(csv_path: Path) -> list[TTSJob]:
    state = diagnose_csv(csv_path)
    if not state.jobs:
        raise CSVValidationError(_summary_error(state) or "CSV contains no importable rows.")
    return state.jobs


def diagnose_csv(csv_path: Path) -> CsvImportState:
    if not csv_path.exists():
        raise CSVValidationError(f"CSV file not found: {csv_path}")
    text, encoding = _read_text(csv_path)
    delimiter = _detect_delimiter(text)
    state = CsvImportState(
        source_path=csv_path,
        detected_encoding=encoding,
        detected_delimiter=delimiter,
        total_physical_rows=len(text.splitlines()),
    )
    try:
        reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
        rows = list(reader)
    except csv.Error as exc:
        _issue(state, None, None, "error", "csv_parse_error", "", "", "", str(exc), "Repair quoting or delimiters.")
        return state
    if not rows:
        _issue(state, None, None, "error", "empty_csv", "", "", "", "CSV is empty.", "Choose a CSV with headers and data.")
        return state
    raw_headers = rows[0]
    headers = [(header or "").strip().lower() for header in raw_headers]
    state.header_names = headers
    duplicates = {name for name, count in Counter(headers).items() if name and count > 1}
    for duplicate in duplicates:
        _issue(state, 1, None, "error", "duplicate_header", delimiter.join(raw_headers), "", "", f"Duplicate header: {duplicate}", "Make header names unique.")
    missing_headers = REQUIRED_COLUMNS - set(headers)
    if missing_headers:
        _issue(state, 1, None, "error", "missing_required_columns", delimiter.join(raw_headers), "", "", f"Missing columns: {', '.join(sorted(missing_headers))}", "Add filename and text columns.")
    if duplicates or missing_headers:
        return state
    filename_index = headers.index("filename")
    text_index = headers.index("text")
    expected_count = len(headers)
    seen_output_names: list[tuple[str, int]] = []
    for parsed_row, row in enumerate(rows[1:], start=2):
        physical_row = parsed_row
        raw_excerpt = _excerpt(delimiter.join(row))
        state.parsed_rows += 1
        if len(row) > expected_count:
            state.extra_column_rows.append(physical_row)
            state.malformed_rows.append(physical_row)
            _issue(state, physical_row, parsed_row, "error", "extra_columns", raw_excerpt, _safe_get(row, filename_index), _safe_get(row, text_index), "Row has more fields than the header.", "Quote delimiters inside text or repair the row.")
            continue
        if len(row) < expected_count:
            state.missing_column_rows.append(physical_row)
            state.malformed_rows.append(physical_row)
            _issue(state, physical_row, parsed_row, "error", "missing_columns", raw_excerpt, _safe_get(row, filename_index), _safe_get(row, text_index), "Row has fewer fields than the header.", "Restore missing fields or repair the row.")
            continue
        filename = row[filename_index]
        text_value = row[text_index].replace("\r\n", "\n")
        row_rejected = False
        if not filename.strip() or not text_value.strip():
            state.missing_column_rows.append(physical_row)
            _issue(state, physical_row, parsed_row, "error", "missing_field", raw_excerpt, filename, text_value, "Filename or text is empty.", "Fill both filename and text.")
            row_rejected = True
        if _filename_looks_like_prose(filename):
            state.filename_looks_like_prose_rows.append(physical_row)
            _issue(state, physical_row, parsed_row, "error", "filename_looks_like_prose", raw_excerpt, filename, text_value, "Filename field looks like prose.", "Repair CSV quoting or place a real filename in filename.")
            row_rejected = True
        if _text_looks_like_filename(text_value):
            state.text_looks_like_filename_rows.append(physical_row)
            _issue(state, physical_row, parsed_row, "warning", "text_looks_like_filename", raw_excerpt, filename, text_value, "Text field looks like a filename.", "Verify columns are not swapped.")
        if row_rejected:
            continue
        try:
            job = TTSJob(
                row_number=physical_row,
                filename=filename,
                text=text_value,
                source_physical_row=physical_row,
                import_status="imported",
            )
        except Exception as exc:
            _issue(state, physical_row, parsed_row, "error", "invalid_row", raw_excerpt, filename, text_value, str(exc), "Repair the row.")
            continue
        state.jobs.append(job)
        seen_output_names.append((Path(filename).name.casefold(), physical_row))
    duplicate_names = {name for name, count in Counter(name for name, _row in seen_output_names).items() if count > 1}
    for name, row_number in seen_output_names:
        if name in duplicate_names:
            state.duplicate_filename_rows.append(row_number)
            job = next(job for job in state.jobs if job.row_number == row_number)
            _issue(state, row_number, row_number, "warning", "duplicate_filename", job.filename, job.filename, job.text, "Duplicate output filename.", "Rename one of the duplicate files.")
    state.rejected_rows = sum(1 for issue in state.issues if issue.severity == "error" and issue.physical_row != 1)
    state.valid_rows = len(state.jobs)
    state.can_import = state.valid_rows > 0 and state.rejected_rows == 0
    return state


def generate_repaired_preview(state: CsvImportState) -> tuple[Path, Path | None]:
    target = state.source_path.with_name(f"{state.source_path.stem}.repaired-preview.csv")
    rejected = state.source_path.with_name(f"{state.source_path.stem}.rejected-rows.csv")
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text", "filename"], quoting=csv.QUOTE_ALL)
        writer.writeheader()
        for job in state.jobs:
            writer.writerow({"text": job.text, "filename": job.filename})
    rejected_issues = [issue for issue in state.issues if issue.severity == "error"]
    if rejected_issues:
        with rejected.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["physical_row", "issue_code", "reason", "raw_row_excerpt"])
            writer.writeheader()
            for issue in rejected_issues:
                writer.writerow(
                    {
                        "physical_row": issue.physical_row,
                        "issue_code": issue.issue_code,
                        "reason": issue.problem,
                        "raw_row_excerpt": issue.raw_row_excerpt,
                    }
                )
        state.rejected_rows_path = rejected
    state.repaired_preview_path = target
    return target, state.rejected_rows_path


def save_manual_repair(state: CsvImportState, *, text: str, filename: str) -> TTSJob:
    if not text.strip():
        raise CSVValidationError("Text cannot be empty.")
    if _filename_looks_like_prose(filename):
        raise CSVValidationError("Filename is invalid or looks like prose.")
    existing = {Path(job.filename).name.casefold() for job in state.jobs}
    if Path(filename).name.casefold() in existing:
        raise CSVValidationError("Duplicate filename.")
    row_number = max([job.row_number for job in state.jobs] or [1]) + 1
    job = TTSJob(row_number=row_number, filename=filename, text=text, import_status="repaired")
    state.jobs.append(job)
    state.valid_rows = len(state.jobs)
    generate_repaired_preview(state)
    return job


def write_import_report(state: CsvImportState, reports_dir: Path, project_name: str = "No project") -> Path:
    report_dir = reports_dir / _safe_name(project_name) / "imports" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = _state_json(state)
    (report_dir / "import.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    (report_dir / "import.md").write_text(_markdown(state), encoding="utf-8")
    (report_dir / "import.html").write_text(_html(state), encoding="utf-8")
    with (report_dir / "issues.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["physical_row", "parsed_row", "severity", "issue_code", "parsed_filename", "parsed_text_excerpt", "problem", "suggested_action", "raw_row_excerpt"])
        writer.writeheader()
        for issue in state.issues:
            writer.writerow(issue.__dict__)
    rejected = [issue for issue in state.issues if issue.severity == "error"]
    if rejected:
        with (report_dir / "rejected-rows.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["physical_row", "issue_code", "problem", "raw_row_excerpt"])
            writer.writeheader()
            for issue in rejected:
                writer.writerow({"physical_row": issue.physical_row, "issue_code": issue.issue_code, "problem": issue.problem, "raw_row_excerpt": issue.raw_row_excerpt})
    return report_dir


def _read_text(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise CSVValidationError("CSV must be UTF-8, UTF-8 BOM, cp1252, or latin-1 encoded.")


def _detect_delimiter(text: str) -> str:
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters="".join(DELIMITERS))
        if dialect.delimiter in DELIMITERS:
            return dialect.delimiter
    except csv.Error:
        pass
    first = sample.splitlines()[0] if sample.splitlines() else ""
    counts = {delimiter: first.count(delimiter) for delimiter in DELIMITERS}
    return max(counts, key=counts.get) if any(counts.values()) else ","


def _filename_looks_like_prose(filename: str) -> bool:
    value = filename.strip()
    basename = Path(value).name
    if INVALID_WINDOWS.search(basename):
        return True
    if len(value) > 80:
        return True
    words = [part for part in re.split(r"\s+", value) if part]
    if len(words) > 4:
        return True
    if not FILENAME_EXT.search(value) and (len(words) > 1 or value.endswith((".", "!", "?", ":", ";", ","))):
        return True
    return False


def _text_looks_like_filename(text: str) -> bool:
    value = text.strip()
    return bool(value and len(value) < 120 and FILENAME_EXT.search(value) and not re.search(r"\s", value))


def _issue(
    state: CsvImportState,
    physical_row: int | None,
    parsed_row: int | None,
    severity: str,
    code: str,
    raw: str,
    filename: str,
    text: str,
    problem: str,
    action: str,
) -> None:
    state.issues.append(CsvImportIssue(physical_row, parsed_row, severity, code, _excerpt(raw), _excerpt(filename, 160), _excerpt(text, 220), problem, action))


def _safe_get(row: list[str], index: int) -> str:
    return row[index] if 0 <= index < len(row) else ""


def _excerpt(value: str, limit: int = 240) -> str:
    value = (value or "").replace("\r", "\\r").replace("\n", "\\n")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def _summary_error(state: CsvImportState) -> str:
    if not state.issues:
        return ""
    counts = Counter(issue.issue_code for issue in state.issues)
    parts = ", ".join(f"{code}: {count}" for code, count in counts.items())
    return f"CSV import diagnostics found {len(state.issues)} issue(s): {parts}"


def _state_json(state: CsvImportState) -> dict:
    data = {key: value for key, value in state.__dict__.items() if key not in {"jobs", "issues"}}
    data["source_path"] = str(state.source_path)
    data["repaired_preview_path"] = str(state.repaired_preview_path) if state.repaired_preview_path else None
    data["rejected_rows_path"] = str(state.rejected_rows_path) if state.rejected_rows_path else None
    data["issues"] = [issue.__dict__ for issue in state.issues]
    return data


def _markdown(state: CsvImportState) -> str:
    return (
        "# S Talking CSV Import Report\n\n"
        f"- Source: `{state.source_path}`\n"
        f"- Encoding: {state.detected_encoding}\n"
        f"- Delimiter: `{state.detected_delimiter}`\n"
        f"- Physical rows: {state.total_physical_rows:,}\n"
        f"- Parsed rows: {state.parsed_rows:,}\n"
        f"- Valid rows: {state.valid_rows:,}\n"
        f"- Rejected rows: {state.rejected_rows:,}\n"
        f"- Filename looks like prose: {len(state.filename_looks_like_prose_rows):,}\n\n"
        "## Issues\n"
        + ("\n".join(f"- Row {issue.physical_row}: {issue.issue_code} - {issue.problem}" for issue in state.issues) or "- None")
        + "\n"
    )


def _html(state: CsvImportState) -> str:
    rows = "".join(
        f"<tr><td>{issue.physical_row or ''}</td><td>{html.escape(issue.severity)}</td><td>{html.escape(issue.issue_code)}</td><td>{html.escape(issue.problem)}</td></tr>"
        for issue in state.issues
    ) or "<tr><td colspan='4'>No issues</td></tr>"
    return f"<!doctype html><html><meta charset='utf-8'><title>S Talking CSV Import</title><body><h1>CSV Import Report</h1><p>{html.escape(str(state.source_path))}</p><p>{state.valid_rows:,} valid / {state.rejected_rows:,} rejected</p><table>{rows}</table></body></html>"


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(" .")
    return cleaned or "No project"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
