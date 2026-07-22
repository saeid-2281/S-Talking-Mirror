from __future__ import annotations

import csv
from pathlib import Path

from app.exceptions import CSVValidationError
from app.models import TTSJob

REQUIRED_COLUMNS = {"text", "filename"}


def load_jobs(csv_path: Path) -> list[TTSJob]:
    if not csv_path.exists():
        raise CSVValidationError(f"CSV file not found: {csv_path}")

    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = {header.strip().lower() for header in (reader.fieldnames or [])}
            missing = REQUIRED_COLUMNS - headers
            if missing:
                raise CSVValidationError(
                    f"CSV is missing required columns: {', '.join(sorted(missing))}"
                )

            jobs: list[TTSJob] = []
            errors: list[str] = []

            for row_number, row in enumerate(reader, start=2):
                normalized = {
                    (key or "").strip().lower(): (value or "")
                    for key, value in row.items()
                }
                try:
                    jobs.append(
                        TTSJob(
                            row_number=row_number,
                            text=normalized["text"],
                            filename=normalized["filename"],
                        )
                    )
                except Exception as exc:
                    errors.append(f"row {row_number}: {exc}")

    except UnicodeDecodeError as exc:
        raise CSVValidationError("CSV must be UTF-8 encoded.") from exc
    except OSError as exc:
        raise CSVValidationError(f"Could not read CSV: {exc}") from exc

    if errors:
        preview = "\n".join(errors[:10])
        extra = f"\n... and {len(errors) - 10} more" if len(errors) > 10 else ""
        raise CSVValidationError(f"Invalid CSV rows:\n{preview}{extra}")

    if not jobs:
        raise CSVValidationError("CSV contains no data rows.")

    return jobs
