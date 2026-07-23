from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QProcess

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.developer_tools import DeveloperTools, DevelopmentAssistantDialog
from app.models import AppSettings, DashboardState, ProjectState
from app.services.git_service import GitService
from app.services.task_prompt_service import TASK_STATUSES, TaskPromptService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_complete_diagnostics_bundle_contains_expected_files_and_redacts(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    (runtime.settings_path).write_text(AppSettings(api_key="sk_SECRET").model_dump_json(), encoding="utf-8")
    latest = runtime.artifacts_dir / "dev-check" / "latest"
    latest.mkdir(parents=True)
    (latest / "pytest.txt").write_text("PASSED", encoding="utf-8")
    runtime.log_dir.mkdir(exist_ok=True)
    (runtime.log_dir / "app.log").write_text("Authorization: Bearer SECRET\nTraceback: nope", encoding="utf-8")
    context = create_application_context(create_service_container(runtime))
    context.report_service.latest_report = None
    project = ProjectState(1, "Diag", None, tmp_path / "input.csv", tmp_path / "out", "mock", AppSettings(provider="mock"))

    bundle = context.diagnostics_service.export_bundle(
        project=project,
        dashboard=DashboardState(total_files=2, total_characters=10, completed=1, pending=1),
        queue_state={"active": False, "paused": False},
    )

    assert bundle.exists()
    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        for name in [
            "diagnostics/overview.md",
            "diagnostics/environment.json",
            "diagnostics/application_state.json",
            "diagnostics/git_state.json",
            "diagnostics/latest_dev_check/pytest.txt",
            "diagnostics/latest_report/README.txt",
            "diagnostics/logs/app.log",
            "diagnostics/sanitized_settings.json",
            "diagnostics/file_manifest.txt",
            "diagnostics/errors.txt",
        ]:
            assert name in names
        content = "\n".join(archive.read(name).decode("utf-8", errors="ignore") for name in names)
        app_state = json.loads(archive.read("diagnostics/application_state.json"))
    assert "sk_SECRET" not in content
    assert "Authorization: Bearer SECRET" not in content
    assert app_state["current_project_name"] == "Diag"
    assert app_state["queue_totals"]["total"] == 2


def test_git_service_sanitizes_remote_credentials_and_blocks_destructive_commands(tmp_path: Path) -> None:
    service = GitService(tmp_path)

    assert service.sanitize_text("https://token@example.com/repo.git") == "https://[REDACTED]@example.com/repo.git"
    with pytest.raises(RuntimeError):
        service._run(["push", "--force"])
    with pytest.raises(RuntimeError):
        service._run(["reset", "--hard"])


def test_git_service_refuses_commit_on_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = GitService(tmp_path)
    monkeypatch.setattr(service, "current_branch", lambda: "main")
    monkeypatch.setattr(service, "changed_files", lambda: ["app/gui/main.py"])

    with pytest.raises(RuntimeError, match="main"):
        service.commit("test")


def test_git_service_prepare_commit_blocks_generated_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    service = GitService(tmp_path)
    monkeypatch.setattr(service, "current_branch", lambda: "feature/test")
    monkeypatch.setattr(service, "changed_files", lambda: ["reports/run/summary.json", "app/gui/main.py"])

    preview = service.prepare_commit()

    assert preview["allowed"] is False
    assert preview["blocked_files"] == ["reports/run/summary.json"]


def test_development_assistant_imports_and_constructs(qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    dialog = DevelopmentAssistantDialog(None, context, DeveloperTools(None, context))

    assert dialog.windowTitle() == "Development Assistant"
    dialog.close()


def test_background_self_check_starts_qprocess(monkeypatch: pytest.MonkeyPatch, qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    tools = DeveloperTools(None, context)
    started = {"value": False}

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QProcess, "start", lambda self: started.__setitem__("value", True))

    tools.run_self_check()

    assert started["value"] is True


def test_task_prompt_loading_and_status_update(tmp_path: Path) -> None:
    service = TaskPromptService(tmp_path)
    task = service.tasks_dir / "TASK.md"
    task.write_text(
        "# Task\n\n## Title\nDemo\n\n## Branch\nfeature/demo\n\n## Goal\nShip it\n\n"
        "## Acceptance Criteria\n- Works\n\n## Codex Prompt\nDo the thing\n\n## Status\nDraft\n",
        encoding="utf-8",
    )

    loaded = service.load(task)
    assert loaded.title == "Demo"
    assert loaded.codex_prompt == "Do the thing"

    service.update_status(task, "Review")
    assert service.load(task).status == "Review"
    assert "Review" in TASK_STATUSES
