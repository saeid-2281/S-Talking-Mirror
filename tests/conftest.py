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
def isolate_qsettings_between_tests():
    """Prevent persistent desktop preferences from leaking between tests.

    QSettings is process/global-user scoped rather than tied to RuntimeConfig's
    temporary root. Without isolation, a test that stores an ElevenLabs provider
    can make a later, unrelated CSV-repair test run Preflight with stale cloud
    credentials and report false blocking errors.
    """
    settings = QSettings("S Talking", "S Talking")
    settings.clear()
    settings.sync()
    yield
    settings = QSettings("S Talking", "S Talking")
    settings.clear()
    settings.sync()
