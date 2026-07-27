from __future__ import annotations

import pytest
from PySide6.QtCore import QSettings


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
