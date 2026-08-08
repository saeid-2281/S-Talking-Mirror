from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication

from app.gui.developer_tools import DevCheckRunner


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def wait_for(predicate, qt_app, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        qt_app.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_runner_uses_noninteractive_profile_free_powershell(
    monkeypatch: pytest.MonkeyPatch,
    qt_app,
    tmp_path: Path,
) -> None:
    script = tmp_path / "check.ps1"
    script.write_text("exit 0", encoding="utf-8")
    runner = DevCheckRunner(tmp_path, tmp_path / "artifacts")

    monkeypatch.setattr(QProcess, "start", lambda self: None)

    assert runner.start(script) is True
    assert runner.process is not None
    assert Path(runner.process.program()).name.lower() == "powershell.exe"
    arguments = runner.process.arguments()
    assert arguments[:3] == ["-NoLogo", "-NoProfile", "-NonInteractive"]
    assert arguments[-2:] == ["-File", str(script)]


def test_runner_prefers_systemroot_powershell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    powershell = (
        tmp_path
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    powershell.parent.mkdir(parents=True)
    powershell.write_bytes(b"")
    monkeypatch.setenv("SystemRoot", str(tmp_path))

    runner = DevCheckRunner(tmp_path, tmp_path / "artifacts")

    assert Path(runner._powershell_program()) == powershell


def test_runner_reports_failed_to_start_instead_of_silent_timeout(
    monkeypatch: pytest.MonkeyPatch,
    qt_app,
    tmp_path: Path,
) -> None:
    script = tmp_path / "check.ps1"
    script.write_text("exit 0", encoding="utf-8")
    missing = tmp_path / "missing-powershell.exe"
    runner = DevCheckRunner(tmp_path, tmp_path / "artifacts")
    results = []
    runner.finished.connect(results.append)
    monkeypatch.setattr(runner, "_powershell_program", lambda: str(missing))

    assert runner.start(script) is True
    wait_for(lambda: bool(results), qt_app)

    assert results[0].success is False
    assert results[0].stage == "unknown"
    assert results[0].exit_code == -1
    assert "failed to start" in results[0].summary.lower()


def test_runner_completion_is_emitted_only_once(qt_app, tmp_path: Path) -> None:
    runner = DevCheckRunner(tmp_path, tmp_path / "artifacts")
    results = []
    runner.finished.connect(results.append)
    result = runner._unknown_result(-1, "synthetic failure")

    runner._emit_finished(result)
    runner._emit_finished(result)
    qt_app.processEvents()

    assert results == [result]
