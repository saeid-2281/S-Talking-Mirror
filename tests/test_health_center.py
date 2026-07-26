from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.developer_tools import DevCheckDialog, DeveloperTools
from app.gui.health_center import HealthCenterDialog
from app.gui.task_center import TaskCenterDialog
from app.models import AppSettings, DashboardState, ProjectState
from app.services.git_service import GitStatus
from app.services.health_service import HealthService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class FakeGit:
    def __init__(self, clean: bool = True) -> None:
        self.clean = clean

    def status(self) -> GitStatus:
        return GitStatus("feature/health-center", self.clean, [] if self.clean else ["app/gui/main.py"])


class FakeReport:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def latest_report_dir(self) -> Path | None:
        return self.path


class FakeDiagnostics:
    def __init__(self, path: Path | None) -> None:
        self.latest_bundle = path


def test_health_service_builds_ready_snapshot_and_markdown(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    latest = runtime.artifacts_dir / "dev-check" / "latest"
    latest.mkdir(parents=True)
    (latest / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "success": True,
                "summary": "All checks passed",
                "artifact_directory": str(latest),
                "steps": {
                    "compileall": {"success": True, "exit_code": 0},
                    "pytest": {"success": True, "exit_code": 0, "passed": 86, "failed": 0, "errors": 0},
                    "ruff": {"success": True, "exit_code": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    report = runtime.reports_dir / "latest"
    report.mkdir(parents=True)
    diagnostics = runtime.artifacts_dir / "diagnostics" / "S-Talking-Diagnostics-test.zip"
    diagnostics.parent.mkdir(parents=True)
    diagnostics.write_bytes(b"zip")
    service = HealthService(runtime, FakeGit(), FakeReport(report), FakeDiagnostics(diagnostics))
    project = ProjectState(1, "Danish", None, None, None, "mock", AppSettings(provider="mock"))

    state = service.snapshot(
        project=project,
        dashboard=DashboardState(total_files=10, completed=8, failed=1, pending=1),
    )
    markdown = service.markdown_summary(state)

    assert state.level == "healthy"
    assert state.score == 100
    assert state.check.tests_passed == 86
    assert "Danish" in markdown
    assert "feature/health-center" in markdown
    assert "86" in markdown


def test_health_service_reports_missing_result_as_unknown(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    latest = runtime.artifacts_dir / "dev-check" / "latest"
    latest.mkdir(parents=True)
    service = HealthService(runtime, FakeGit(), FakeReport(None), FakeDiagnostics(None))

    check = service.latest_check()

    assert check.available is False
    assert "unknown" in check.summary.lower()


def test_health_service_reports_malformed_result_as_unknown(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    latest = runtime.artifacts_dir / "dev-check" / "latest"
    latest.mkdir(parents=True)
    (latest / "result.json").write_text("{not json", encoding="utf-8")
    service = HealthService(runtime, FakeGit(), FakeReport(None), FakeDiagnostics(None))

    check = service.latest_check()

    assert check.available is False
    assert "malformed" in check.summary.lower()


def test_health_service_reads_failing_pytest_result_json(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    latest = runtime.artifacts_dir / "dev-check" / "latest"
    latest.mkdir(parents=True)
    (latest / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "success": False,
                "exit_code": 1,
                "stage": "pytest",
                "summary": "Checks failed at pytest",
                "artifact_directory": str(latest),
                "steps": {
                    "compileall": {"success": True, "exit_code": 0},
                    "pytest": {"success": False, "exit_code": 1, "passed": 12, "failed": 2, "errors": 1},
                    "ruff": {"success": False, "exit_code": None},
                },
            }
        ),
        encoding="utf-8",
    )
    service = HealthService(runtime, FakeGit(), FakeReport(None), FakeDiagnostics(None))

    check = service.latest_check()

    assert check.available is True
    assert check.success is False
    assert check.tests_passed == 12
    assert check.compile_passed is True
    assert check.ruff_passed is False
    assert "pytest" in check.summary


def test_health_service_does_not_depend_on_text_files(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    latest = runtime.artifacts_dir / "dev-check" / "latest"
    latest.mkdir(parents=True)
    (latest / "pytest.txt").write_text("999 passed", encoding="utf-8")
    (latest / "ruff.txt").write_text("All checks passed!", encoding="utf-8")
    (latest / "compileall.txt").write_text("Listing 'app'...", encoding="utf-8")
    service = HealthService(runtime, FakeGit(), FakeReport(None), FakeDiagnostics(None))

    check = service.latest_check()

    assert check.available is False
    assert check.tests_passed == 0


def test_health_service_warns_when_checks_and_artifacts_are_missing(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    service = HealthService(runtime, FakeGit(clean=False), FakeReport(None), FakeDiagnostics(None))

    state = service.snapshot(dashboard=DashboardState(total_files=2))

    assert state.level in {"warning", "error"}
    assert state.score < 85
    assert state.warnings


def test_health_center_and_task_center_are_non_modal(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    context = create_application_context(create_service_container(runtime))
    task_dir = tmp_path / "docs" / "tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "TASK.md").write_text(
        "# Task\n\n## Title\nTest Task\n\n## Branch\nfeature/test\n\n"
        "## Goal\nTest goal\n\n## Acceptance Criteria\n- Pass\n\n"
        "## Codex Prompt\nDo the task\n\n## Status\nReady\n",
        encoding="utf-8",
    )

    health = HealthCenterDialog(None, context)
    tasks = TaskCenterDialog(None, context)

    assert health.isModal() is False
    assert tasks.isModal() is False
    assert tasks.tasks.count() == 1
    health.close()
    tasks.close()


def test_developer_tools_exposes_health_task_and_smart_copy(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    context = create_application_context(create_service_container(runtime))
    tools = DeveloperTools(None, context)
    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    actions = tools.populate_menu(menu)
    dialog = DevCheckDialog(None, context)

    assert "Health Center" in actions
    assert "Task Center" in actions
    assert dialog.copy_summary_button.text() == "Copy summary"
    assert dialog.copy_chatgpt_button.text() == "Copy for ChatGPT"
    dialog.close()


def test_health_center_and_badge_refresh_after_runner_completion(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    latest = runtime.artifacts_dir / "dev-check" / "latest"
    latest.mkdir(parents=True)
    (latest / "result.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "success": False,
                "exit_code": 1,
                "stage": "pytest",
                "summary": "Checks failed at pytest",
                "artifact_directory": str(latest),
                "steps": {
                    "compileall": {"success": True, "exit_code": 0},
                    "pytest": {"success": False, "exit_code": 1, "passed": 1, "failed": 1, "errors": 0},
                    "ruff": {"success": False, "exit_code": None},
                },
            }
        ),
        encoding="utf-8",
    )
    report = runtime.reports_dir / "Project" / "run"
    report.mkdir(parents=True)
    (report / "report.html").write_text("<html></html>", encoding="utf-8")
    diagnostics = runtime.artifacts_dir / "diagnostics" / "S-Talking-Diagnostics-test.zip"
    diagnostics.parent.mkdir(parents=True)
    diagnostics.write_bytes(b"zip")
    script = scripts / "dev-check.ps1"
    script.write_text(
        f"""
$latest = '{latest.as_posix()}'
@{{
  schema_version = 1
  started_at = '2026-01-01T00:00:00Z'
  finished_at = '2026-01-01T00:00:01Z'
  elapsed_seconds = 1
  success = $true
  exit_code = 0
  stage = 'complete'
  summary = 'All checks passed'
  artifact_directory = $latest
  steps = @{{
    compileall = @{{ success = $true; exit_code = 0 }}
    pytest = @{{ success = $true; exit_code = 0; passed = 98; failed = 0; errors = 0 }}
    ruff = @{{ success = $true; exit_code = 0 }}
  }}
}} | ConvertTo-Json -Depth 6 | Set-Content (Join-Path $latest 'result.json')
Write-Output 'done'
exit 0
""",
        encoding="utf-8",
    )
    context = create_application_context(create_service_container(runtime))
    context.diagnostics_service.latest_bundle = diagnostics
    window = MainWindow(context)
    window.developer_tools.show_health_center()
    health = window.developer_tools.health_dialog
    assert health is not None
    assert "Checks failing" in window.health_button.text()

    window.developer_tools.show_checks()
    wait_for(lambda: not window.developer_tools.check_dialog.runner.is_active, qt_app)

    assert "Ready" in window.health_button.text()
    assert health.state is not None
    assert health.state.check.tests_passed == 98
    assert "98 tests passed" in health.details.toPlainText()
    window.close()


def wait_for(predicate, qt_app, timeout: float = 5.0) -> None:
    import time

    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert predicate()
