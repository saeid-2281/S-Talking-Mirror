from __future__ import annotations

import json
import os
import zipfile
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.command_palette import CommandPalette, PaletteCommand
from app.gui.developer_tools import DeveloperTools, DevCheckRunner, DevelopmentAssistantDialog, RuntimeInformationDialog
from app.models import AppSettings, DashboardState, ProjectState
from app.services.desktop_service import DesktopService
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


def test_developer_tools_window_is_non_modal(qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    dialog = DevelopmentAssistantDialog(None, context, DeveloperTools(None, context))

    assert dialog.isModal() is False
    dialog.close()


def test_developer_tools_menu_actions_exist_and_script_state(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    window = MainWindow(context)
    menu = window.developer_menu
    actions = {action.text(): action for action in menu.actions()}
    for label in [
        "Run all checks",
        "Export diagnostics",
        "Open diagnostics folder",
        "Open latest report",
        "Open reports folder",
        "Open logs folder",
        "Open repository folder",
        "Open repository in VS Code",
        "Show runtime information",
        "Spinbox visual test",
        "Command Palette",
    ]:
        assert label in actions
    assert actions["Run all checks"].isEnabled() is False
    assert "dev-check.ps1" in actions["Run all checks"].toolTip()
    window.close()


def test_run_all_checks_action_enabled_when_script_exists(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dev-check.ps1").write_text("exit 0", encoding="utf-8")
    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))

    assert window.actions_by_name["Run all checks"].isEnabled() is True
    window.close()


def test_background_self_check_starts_qprocess(monkeypatch: pytest.MonkeyPatch, qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "dev-check.ps1").write_text("exit 0", encoding="utf-8")
    tools = DeveloperTools(None, context)
    started = {"value": False}

    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    monkeypatch.setattr(QProcess, "start", lambda self: started.__setitem__("value", True))

    tools.show_checks()

    assert started["value"] is True


def test_qprocess_runner_captures_success(qt_app, tmp_path: Path) -> None:
    script = tmp_path / "success.ps1"
    script.write_text("Write-Output 'hello'; exit 0", encoding="utf-8")
    runner = DevCheckRunner(tmp_path, tmp_path / "artifacts")
    results = []
    runner.finished.connect(results.append)

    assert runner.start(script) is True
    wait_for(lambda: bool(results), qt_app)

    assert results[0].success is True
    assert results[0].exit_code == 0
    assert "hello" in results[0].stdout_path.read_text(encoding="utf-8")


def test_qprocess_runner_captures_failure(qt_app, tmp_path: Path) -> None:
    script = tmp_path / "failure.ps1"
    script.write_text("Write-Error 'bad'; exit 3", encoding="utf-8")
    runner = DevCheckRunner(tmp_path, tmp_path / "artifacts")
    results = []
    runner.finished.connect(results.append)

    assert runner.start(script) is True
    wait_for(lambda: bool(results), qt_app)

    assert results[0].success is False
    assert results[0].exit_code == 3
    assert "bad" in results[0].stderr_path.read_text(encoding="utf-8")


def test_second_check_cannot_start_while_active(qt_app, tmp_path: Path) -> None:
    script = tmp_path / "slow.ps1"
    script.write_text("Start-Sleep -Milliseconds 800; exit 0", encoding="utf-8")
    runner = DevCheckRunner(tmp_path, tmp_path / "artifacts")

    assert runner.start(script) is True
    assert runner.start(script) is False
    runner.cancel()


def test_command_palette_filter_enter_and_disabled_command(qt_app) -> None:
    called = {"ok": 0, "disabled": 0}
    palette = CommandPalette(
        [
            PaletteCommand("Project: New Project", lambda: called.__setitem__("ok", called["ok"] + 1)),
            PaletteCommand("Developer: Disabled", lambda: called.__setitem__("disabled", 1), lambda: False),
        ]
    )
    palette.show()
    palette.search.setText("new")
    assert palette.list.count() == 1
    QTest.keyClick(palette, Qt.Key_Return)
    assert called["ok"] == 1

    palette = CommandPalette(
        [PaletteCommand("Developer: Disabled", lambda: called.__setitem__("disabled", 1), lambda: False)]
    )
    palette.show()
    QTest.keyClick(palette, Qt.Key_Return)
    assert called["disabled"] == 0
    palette.close()


def test_command_palette_opens_with_shortcut(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))
    window.show()
    QTest.keyClick(window, Qt.Key_P, Qt.ControlModifier | Qt.ShiftModifier)
    qt_app.processEvents()

    assert window.palette is not None
    assert window.palette.isVisible()
    window.close()


def test_runtime_dialog_excludes_secrets(qt_app, tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    dialog = RuntimeInformationDialog(None, context)

    assert "api_key" not in dialog.text.toPlainText().lower()
    assert "secret" not in dialog.text.toPlainText().lower()
    dialog.close()


def test_desktop_service_validates_missing_paths(tmp_path: Path) -> None:
    service = DesktopService()

    with pytest.raises(FileNotFoundError):
        service.open_path(tmp_path / "missing")


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


def wait_for(predicate, qt_app, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert predicate()
