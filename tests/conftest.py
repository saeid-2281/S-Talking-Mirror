from __future__ import annotations

import gc
import os
import sys

# The full suite validates logical persistence and UI behavior against disposable
# test roots. Test-only fast-paths avoid Windows fsync and background startup work;
# production processes never receive this flag.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("S_TALKING_TEST_FAST_PATH", "1")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtGui import QFont
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

    # Visual certifiers intentionally install/register a readable runtime font.
    # The QApplication is session-scoped, so preserve its incoming font and
    # restore it after every test; otherwise typography metrics leak into later
    # geometry tests and can make dock widths depend on test ordering.
    application_before = QApplication.instance()
    original_application_font = (
        QFont(application_before.font()) if application_before is not None else None
    )

    settings = QSettings("S Talking", "S Talking")
    settings.clear()
    settings.sync()
    yield

    # Keep the session-scoped QApplication fast and deterministic. Closing and
    # deleting top-level widgets prevents stale windows, timers, styles and
    # media backends from accumulating across hundreds of GUI tests.
    app = QApplication.instance()
    if app is not None:
        for widget in list(app.topLevelWidgets()):
            try:
                widget.close()
                widget.deleteLater()
            except RuntimeError:
                pass
        player_module = sys.modules.get("app.services.audio_player_service")
        player_type = getattr(player_module, "AudioPlayerService", None)
        shared_player = getattr(player_type, "_shared_instance", None)
        if shared_player is not None:
            try:
                shared_player.unload()
            except RuntimeError:
                pass
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        if original_application_font is not None:
            app.setFont(original_application_font)
        gc.collect()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()

    settings.clear()
    settings.sync()
