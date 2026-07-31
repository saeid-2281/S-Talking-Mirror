from __future__ import annotations

import os

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qt_app():
    """Provide one shared QApplication for GUI tests.

    Several older test modules define this fixture locally, but new UI rewrite
    tests rely on a project-wide fixture. QApplication must be a singleton, so
    reuse an existing instance when one has already been created.
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()


@pytest.fixture(autouse=True)
def isolate_qsettings_between_tests(tmp_path):
    """Use per-test INI settings instead of the Windows registry.

    This prevents desktop preferences from leaking between tests and avoids
    registry cleanup failures when Qt still has a settings handle open.
    """
    settings_root = tmp_path / "qsettings"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(settings_root))
    settings = QSettings("S Talking", "S Talking")
    settings.clear()
    settings.sync()
    yield
    settings.clear()
    settings.sync()
