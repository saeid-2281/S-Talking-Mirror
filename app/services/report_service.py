from __future__ import annotations

import csv
import html
import importlib.metadata
import json
import platform
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PySide6 import QtCore

import app
from app.config.runtime import RuntimeConfig
from app.models import AppSettings, GenerationReport, ProjectState, ReportJob, TTSJob

REPORT_SCHEMA_VERSION = 1
SECRET_KEYS = re.compile(r"(api[_-]?key|authorization|token|secret|password)", re.IGNORECASE)
SECRET_VALUE = re.compile(r"(sk_[A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+)", re.IGNORECASE)


class ReportService:
    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime
        self.latest_report: GenerationReport | None = None

    def create_generation_report(
        self,
        *,
        project: ProjectState | None,
        settings: AppSettings,
        jobs: list[TTSJob],
        output_dir: Path,
        summary: dict[str, Any],
        started_at: datetime,
        ended_at: datetime | None = None,
        log_events: list[str] | None = None,
    ) -> GenerationReport:
        ended = ended_at or datetime.now(timezone.utc)
        project_name = self._safe_name(project.name if project else "No project")
        report_dir = self.runtime.reports_dir / project_name / ended.strftime("%Y-%m-%d_%H-%M-%S")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_jobs = self._report_jobs(jobs, output_dir, settings)
        counts = self._counts(report_jobs, summary)
        summary_data = self._summary(
            project=project,
            settings=settings,
            output_dir=output_dir,
            report_dir=report_dir,
            started_at=started_at,
            ended_at=ended,
            counts=counts,
        )
        report = GenerationReport(
            report_dir=report_dir,
            summary=self.sanitize(summary_data),
            jobs=report_jobs,
            log_events=[self.sanitize_text(line) for line in (log_events or [])],
        )
        self._write_all(report)
        self.latest_report = report
        return report

    def latest_report_dir(self) -> Path | None:
        return self.latest_report.report_dir if self.latest_report else self._find_latest_report_dir()

    def export_diagnostics_bundle(self, report_dir: Path | None = None) -> Path:
        source = report_dir or self.latest_report_dir()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target_dir = self.runtime.artifacts_dir / "diagnostics"
        target_dir.mkdir(parents=True, exist_ok=True)
        bundle = target_dir / f"S-Talking-Diagnostics-{timestamp}.zip"
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            if source and source.exists():
                for path in source.rglob("*"):
                    if path.is_file():
                        archive.writestr(f"report/{path.relative_to(source).as_posix()}", self.sanitize_bytes(path))
            if self.runtime.log_dir.exists():
                for path in self.runtime.log_dir.rglob("*.log"):
                    archive.writestr(f"logs/{path.name}", self.sanitize_bytes(path))
            archive.writestr(
                "diagnostics/export.json",
                json.dumps(
                    self.sanitize(
                        {
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "source_report": str(source) if source else None,
                            "platform": platform.platform(),
                            "python": sys.version,
                            "pyside": QtCore.__version__,
                        }
                    ),
                    indent=2,
                    ensure_ascii=False,
                ),
            )
        return bundle

    def sanitize_bytes(self, path: Path) -> bytes:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return b"<binary file omitted from sanitized diagnostics>"
        return self.sanitize_text(text).encode("utf-8")

    def sanitize(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "[REDACTED]" if SECRET_KEYS.search(str(key)) else self.sanitize(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.sanitize(item) for item in value]
        if isinstance(value, str):
            return self.sanitize_text(value)
        return value

    def sanitize_text(self, value: str) -> str:
        return SECRET_VALUE.sub("[REDACTED]", value)

    def _write_all(self, report: GenerationReport) -> None:
        (report.report_dir / "summary.json").write_text(
            json.dumps(report.summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (report.report_dir / "summary.md").write_text(self._markdown(report), encoding="utf-8")
        (report.report_dir / "report.html").write_text(self._html(report), encoding="utf-8")
        (report.report_dir / "generation.log").write_text("\n".join(report.log_events), encoding="utf-8")
        self._write_jobs_csv(report.report_dir / "jobs.csv", report.jobs)
        self._write_jobs_csv(report.report_dir / "failed.csv", [job for job in report.jobs if job.status == "failed"])
        self._write_jobs_csv(report.report_dir / "skipped.csv", [job for job in report.jobs if job.status == "skipped"])
        (report.report_dir / "diagnostics.json").write_text(
            json.dumps(self.sanitize(self._diagnostics(report)), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_jobs_csv(self, path: Path, jobs: list[ReportJob]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "filename",
                    "row_number",
                    "status",
                    "retry_count",
                    "duration",
                    "character_count",
                    "error",
                    "output_path",
                ],
            )
            writer.writeheader()
            for job in jobs:
                writer.writerow(job.__dict__)

    def _summary(
        self,
        *,
        project: ProjectState | None,
        settings: AppSettings,
        output_dir: Path,
        report_dir: Path,
        started_at: datetime,
        ended_at: datetime,
        counts: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "application_version": app.__version__,
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "project_name": project.name if project else "No project",
            "project_id": project.project_id if project else None,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "elapsed_seconds": max(0.0, (ended_at - started_at).total_seconds()),
            "provider": settings.provider,
            "voice_id": settings.voice_id,
            "model_id": settings.model_id,
            "total_files": counts["total"],
            "completed": counts["completed"],
            "failed": counts["failed"],
            "skipped": counts["skipped"],
            "pending": counts["pending"],
            "stopped": counts["stopped"],
            "total_characters": counts["characters"],
            "output_directory": str(output_dir),
            "report_directory": str(report_dir),
            "settings": self._safe_settings(settings),
            "operating_system": platform.platform(),
            "python_version": sys.version,
            "qt_version": QtCore.qVersion(),
            "pyside_version": QtCore.__version__,
        }

    def _safe_settings(self, settings: AppSettings) -> dict[str, Any]:
        raw = settings.model_dump()
        raw.pop("api_key", None)
        return raw

    def _report_jobs(self, jobs: list[TTSJob], output_dir: Path, settings: AppSettings) -> list[ReportJob]:
        extension = ".wav" if settings.provider in {"mock", "piper"} else settings.file_extension
        return [
            ReportJob(
                filename=job.filename,
                row_number=job.row_number,
                status=str(job.status),
                retry_count=job.retry_count,
                duration=job.duration_seconds,
                character_count=len(job.text),
                error=self.sanitize_text(job.error or ""),
                output_path=str(output_dir / job.generated_output_path)
                if job.generated_output_path
                else str(job.output_path(output_dir, extension)),
            )
            for job in jobs
        ]

    def _counts(self, jobs: list[ReportJob], summary: dict[str, Any]) -> dict[str, Any]:
        total = len(jobs)
        completed = sum(job.status == "completed" for job in jobs) or int(summary.get("completed", 0))
        failed = sum(job.status == "failed" for job in jobs) or int(summary.get("failed", 0))
        skipped = sum(job.status == "skipped" for job in jobs) or int(summary.get("skipped", 0))
        pending = max(0, total - completed - failed - skipped)
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "pending": pending,
            "stopped": bool(summary.get("stopped", False)),
            "characters": sum(job.character_count for job in jobs),
        }

    def _markdown(self, report: GenerationReport) -> str:
        summary = report.summary
        failed = [job for job in report.jobs if job.status == "failed"]
        lines = [
            "# S Talking Generation Report",
            "",
            "## Summary",
            f"- Project: {summary['project_name']}",
            f"- Provider: {summary['provider']}",
            f"- Files: {summary['total_files']}",
            f"- Completed: {summary['completed']}",
            f"- Skipped: {summary['skipped']}",
            f"- Failed: {summary['failed']}",
            f"- Elapsed seconds: {summary['elapsed_seconds']:.2f}",
            "",
            "## Troubleshooting Context",
            f"- Output directory: {summary['output_directory']}",
            f"- Report directory: {summary['report_directory']}",
            f"- Python: {summary['python_version'].split()[0]}",
            f"- Qt/PySide: {summary['qt_version']} / {summary['pyside_version']}",
            "",
            "## Failed Jobs",
        ]
        if failed:
            lines.extend(f"- Row {job.row_number} `{job.filename}`: {job.error or 'No error text'}" for job in failed)
        else:
            lines.append("- None")
        return "\n".join(lines) + "\n"

    def _html(self, report: GenerationReport) -> str:
        summary = report.summary
        failed_rows = "\n".join(
            "<tr>"
            f"<td>{job.row_number}</td><td>{html.escape(job.filename)}</td>"
            f"<td>{html.escape(job.error)}</td>"
            "</tr>"
            for job in report.jobs
            if job.status == "failed"
        )
        if not failed_rows:
            failed_rows = "<tr><td colspan='3'>No failed jobs</td></tr>"
        cards = "".join(
            f"<section><strong>{label}</strong><span>{summary[key]}</span></section>"
            for label, key in [
                ("Files", "total_files"),
                ("Completed", "completed"),
                ("Skipped", "skipped"),
                ("Failed", "failed"),
                ("Characters", "total_characters"),
            ]
        )
        return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>S Talking Report</title>
<style>
:root{{color-scheme:dark light;font-family:Segoe UI,Arial,sans-serif}}
body{{margin:2rem;background:#0b1220;color:#e5e7eb}}
main{{max-width:960px;margin:auto}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.75rem}}
section{{border:1px solid #334155;border-radius:8px;padding:1rem;background:#111827}}
section span{{display:block;font-size:1.6rem;margin-top:.35rem;color:#d1a23a}}
table{{width:100%;border-collapse:collapse;margin-top:1rem}}
td,th{{border-bottom:1px solid #334155;padding:.55rem;text-align:left}}
@media (prefers-color-scheme:light){{body{{background:#f8fafc;color:#0f172a}}section{{background:#fff}}}}
</style>
<main>
<h1>S Talking Generation Report</h1>
<p>{html.escape(summary["project_name"])} · {html.escape(summary["provider"])}</p>
<div class="cards">{cards}</div>
<h2>Failed Jobs</h2>
<table><thead><tr><th>Row</th><th>Filename</th><th>Error</th></tr></thead><tbody>{failed_rows}</tbody></table>
</main>
</html>
"""

    def _diagnostics(self, report: GenerationReport) -> dict[str, Any]:
        packages = {}
        for name in ["PySide6", "pydantic", "httpx", "loguru", "pytest", "ruff"]:
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = None
        failed = [job for job in report.jobs if job.status == "failed"]
        return {
            "summary": report.summary,
            "packages": packages,
            "exceptions": [
                {"type": "GenerationJobError", "filename": job.filename, "error": job.error}
                for job in failed
            ],
        }

    def _safe_name(self, value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip().rstrip(" .")
        return cleaned or "No project"

    def _find_latest_report_dir(self) -> Path | None:
        if not self.runtime.reports_dir.exists():
            return None
        candidates = [path for path in self.runtime.reports_dir.glob("*/*") if path.is_dir()]
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None
