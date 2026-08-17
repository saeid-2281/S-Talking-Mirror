from __future__ import annotations

import inspect
from pathlib import Path

from app.gui.runtime_font_support import ensure_readable_runtime_font


ROOT = Path(__file__).resolve().parents[1]


def test_hotfix2_runtime_font_helper_preserves_existing_typography_metrics() -> None:
    source = inspect.getsource(ensure_readable_runtime_font)

    assert "current = QFont(application.font())" in source
    assert "replacement = QFont(current)" in source
    assert "replacement.setFamily(preferred)" in source
    assert "int(round(point_size))" not in source


def test_hotfix2_runtime_font_helper_is_idempotent_for_selected_family() -> None:
    source = inspect.getsource(ensure_readable_runtime_font)

    assert "current.family().strip().casefold() == preferred.casefold()" in source
    assert "return True, preferred" in source


def test_hotfix2_shared_qapplication_fixture_restores_certifier_font_state() -> None:
    source = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")

    assert "original_application_font" in source
    assert "QFont(application_before.font())" in source
    assert "app.setFont(original_application_font)" in source

    fixture_start = source.index("def isolate_qsettings_between_tests")
    fixture_yield = source.index("\n    yield\n", fixture_start)
    restore_font = source.index("app.setFont(original_application_font)", fixture_yield)
    post_test_settings_clear = source.index("settings.clear()", fixture_yield)

    # Scope the ordering check to the autouse isolation fixture itself.  The
    # session-scoped qt_app fixture has an earlier ``yield app`` and must not be
    # mistaken for the teardown boundary of this fixture.
    assert fixture_yield < restore_font < post_test_settings_clear
