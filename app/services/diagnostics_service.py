from __future__ import annotations

import importlib.metadata
import json
import locale
import os
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6 import QtCore

import app
from app.config import load_settings
from app.config.runtime import RuntimeConfig
from app.models import DashboardState, ProjectState
from app.services.git_service import GitService
from app.services.report_service import ReportService


class DiagnosticsService:
    def __init__(self, runtime: RuntimeConfig, report_service: ReportService, git_service: GitService) -> None:
        self.runtime = runtime
        self.report_service = report_service
        self.git_service = git_service
        self.latest_bundle: Path | None = None

    def export_bundle(
        self,
        *,
        project: ProjectState | None = None,
        dashboard: DashboardState | None = None,
        queue_state: dict[str, Any] | None = None,
    ) -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        bundle_dir = self.runtime.artifacts_dir / "diagnostics"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle = bundle_dir / f"S-Talking-Diagnostics-{timestamp}.zip"
        files: dict[str, bytes] = {}
        files["diagnostics/environment.json"] = self._json_bytes(self.environment())
        files["diagnostics/application_state.json"] = self._json_bytes(
            self.application_state(project=project, dashboard=dashboard, queue_state=queue_state)
        )
        files["diagnostics/git_state.json"] = self._json_bytes(self.git_state())
        files["diagnostics/sanitized_settings.json"] = self._json_bytes(self.sanitized_settings())
        files["diagnostics/errors.txt"] = self._errors_text().encode("utf-8")
        files["diagnostics/overview.md"] = self._overview(
            project=project,
            dashboard=dashboard,
            files=files,
        ).encode("utf-8")
        self._copy_latest_dev_check(files)
        self._copy_latest_report(files)
        self._copy_logs(files)
        files["diagnostics/file_manifest.txt"] = b""
        files["diagnostics/file_manifest.txt"] = self._manifest(files).encode("utf-8")
        with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in files.items():
                archive.writestr(name, self.report_service.sanitize_text(content.decode("utf-8", errors="ignore")).encode("utf-8"))
        self.latest_bundle = bundle
        return bundle

    def environment(self) -> dict[str, Any]:
        packages = {}
        for name in ["PySide6", "pydantic", "httpx", "loguru", "pytest", "ruff"]:
            try:
                packages[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                packages[name] = None
        return {
            "os": platform.platform(),
            "os_version": platform.version(),
            "python_version": sys.version,
            "pyside_version": QtCore.__version__,
            "qt_version": QtCore.qVersion(),
            "application_version": app.__version__,
            "executable_path": sys.executable,
            "repository_root": str(self.runtime.app_root),
            "virtual_environment_path": os.environ.get("VIRTUAL_ENV") or str(self.runtime.app_root / ".venv"),
            "locale": locale.getlocale(),
            "timezone": datetime.now().astimezone().tzname(),
            "packages": packages,
        }

    def application_state(
        self,
        *,
        project: ProjectState | None,
        dashboard: DashboardState | None,
        queue_state: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_dashboard = dashboard or DashboardState()
        return {
            "current_project_name": project.name if project else None,
            "project_file_path": str(project.project_file) if project and project.project_file else None,
            "csv_path": str(project.csv_path) if project and project.csv_path else None,
            "output_path": str(project.output_path) if project and project.output_path else None,
            "provider": project.provider if project else None,
            "model_id": project.settings.model_id if project else None,
            "voice_id": project.settings.voice_id if project else None,
            "queue_totals": {
                "total": current_dashboard.total_files,
                "completed": current_dashboard.completed,
                "failed": current_dashboard.failed,
                "skipped": current_dashboard.skipped,
                "pending": current_dashboard.pending,
            },
            "dashboard_state": current_dashboard.__dict__,
            "latest_report_path": str(self.report_service.latest_report_dir() or ""),
            "runtime_directories": {
                "data": str(self.runtime.data_dir),
                "logs": str(self.runtime.log_dir),
                "cache": str(self.runtime.cache_dir),
                "reports": str(self.runtime.reports_dir),
                "artifacts": str(self.runtime.artifacts_dir),
                "output": str(self.runtime.default_output_dir),
            },
            "generation_active": bool((queue_state or {}).get("active", False)),
            "generation_paused": bool((queue_state or {}).get("paused", False)),
        }

    def git_state(self) -> dict[str, Any]:
        status = self.git_service.status()
        return {
            "current_branch": status.branch,
            "clean": status.clean,
            "changed_file_names": status.changed_files,
            "last_five_commits": self.git_service.recent_commits(5),
            "remote_names": self.git_service.remote_summary(),
            "ahead_behind": self.git_service.ahead_behind(),
        }

    def sanitized_settings(self) -> dict[str, Any]:
        try:
            settings = load_settings(self.runtime.settings_path).model_dump()
        except Exception as exc:
            return {"error": self.report_service.sanitize_text(str(exc))}
        settings["api_key"] = "[REDACTED]" if settings.get("api_key") else ""
        return self.report_service.sanitize(settings)

    def _copy_latest_dev_check(self, files: dict[str, bytes]) -> None:
        latest = self.runtime.artifacts_dir / "dev-check" / "latest"
        if not latest.exists():
            files["diagnostics/latest_dev_check/README.txt"] = b"No latest development check found."
            return
        for path in latest.rglob("*"):
            if path.is_file():
                files[f"diagnostics/latest_dev_check/{path.relative_to(latest).as_posix()}"] = self._read_capped(path)

    def _copy_latest_report(self, files: dict[str, bytes]) -> None:
        latest = self.report_service.latest_report_dir()
        if not latest or not latest.exists():
            files["diagnostics/latest_report/README.txt"] = b"No latest generation report found."
            return
        for path in latest.rglob("*"):
            if path.is_file():
                files[f"diagnostics/latest_report/{path.relative_to(latest).as_posix()}"] = self._read_capped(path)

    def _copy_logs(self, files: dict[str, bytes]) -> None:
        if not self.runtime.log_dir.exists():
            files["diagnostics/logs/README.txt"] = b"No logs directory found."
            return
        logs = sorted(self.runtime.log_dir.rglob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)[:10]
        if not logs:
            files["diagnostics/logs/README.txt"] = b"No recent application logs found."
            return
        for path in logs:
            files[f"diagnostics/logs/{path.name}"] = self._read_capped(path)

    def _errors_text(self) -> str:
        if not self.runtime.log_dir.exists():
            return "No recent application errors recorded."
        lines: list[str] = []
        for path in sorted(self.runtime.log_dir.rglob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
            text = self._read_capped(path).decode("utf-8", errors="ignore")
            for line in text.splitlines():
                if any(marker in line.lower() for marker in ["error", "exception", "traceback"]):
                    lines.append(line)
        return "\n".join(lines) if lines else "No recent application errors recorded."

    def _overview(self, *, project: ProjectState | None, dashboard: DashboardState | None, files: dict[str, bytes]) -> str:
        git = self.git_state()
        latest = self._latest_check_result()
        errors = self._errors_text().splitlines()[0]
        queue = dashboard or DashboardState()
        file_list = "\n".join(f"- {name}" for name in sorted(files))
        return (
            "# S Talking Diagnostics Overview\n\n"
            f"- Branch: {git['current_branch']}\n"
            f"- App version: {app.__version__}\n"
            f"- Project: {(project.name if project else 'None')}\n"
            f"- Provider: {(project.provider if project else 'None')}\n"
            f"- Queue: total={queue.total_files}, completed={queue.completed}, failed={queue.failed}, skipped={queue.skipped}, pending={queue.pending}\n"
            f"- Latest test result: {latest}\n"
            f"- Latest error: {errors}\n\n"
            "## Files Included\n"
            f"{file_list}\n"
        )

    def _latest_check_result(self) -> str:
        summary = self.runtime.artifacts_dir / "dev-check" / "latest" / "summary.txt"
        if not summary.exists():
            return "No development check artifact found."
        lines = summary.read_text(encoding="utf-8", errors="ignore").splitlines()
        failed = [line for line in lines if line.startswith("FAILED")]
        return failed[-1] if failed else "All latest checks passed."

    def _manifest(self, files: dict[str, bytes]) -> str:
        return "\n".join(f"{name}\t{len(content)} bytes" for name, content in sorted(files.items())) + "\n"

    def _json_bytes(self, value: Any) -> bytes:
        return json.dumps(self.report_service.sanitize(value), indent=2, ensure_ascii=False).encode("utf-8")

    def _read_capped(self, path: Path, limit: int = 256_000) -> bytes:
        data = path.read_bytes()[:limit]
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return b"<binary file omitted from sanitized diagnostics>"
        return self.report_service.sanitize_text(text).encode("utf-8")
