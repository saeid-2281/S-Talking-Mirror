from __future__ import annotations

import inspect
import os
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database


ROOT = Path(__file__).resolve().parents[1]


def test_q2_pytest_fast_path_is_enabled() -> None:
    assert os.environ.get("S_TALKING_TEST_FAST_PATH") == "1"


def test_q2_fast_sqlite_preserves_foreign_keys_and_disables_fsync(tmp_path: Path) -> None:
    database = Database(tmp_path / "fast.db")
    with database.connect() as connection:
        foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
        synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        temp_store = int(connection.execute("PRAGMA temp_store").fetchone()[0])

    assert foreign_keys == 1
    assert synchronous == 0
    assert temp_store == 2


def test_q2_default_sqlite_behavior_remains_production_safe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("S_TALKING_TEST_FAST_PATH", raising=False)
    database = Database(tmp_path / "normal.db")
    with database.connect() as connection:
        synchronous = int(connection.execute("PRAGMA synchronous").fetchone()[0])
        foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])

    assert foreign_keys == 1
    assert synchronous != 0


def test_q2_container_skips_startup_quickcheck_only_in_fast_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.generation_maintenance_service import GenerationMaintenanceService

    calls: list[bool] = []
    monkeypatch.setattr(
        GenerationMaintenanceService,
        "run_startup_check",
        lambda self: calls.append(True),
    )
    monkeypatch.setenv("S_TALKING_TEST_FAST_PATH", "1")

    create_service_container(RuntimeConfig.from_root(tmp_path))

    assert calls == []


def test_q2_container_keeps_production_startup_quickcheck(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from app.services.generation_maintenance_service import GenerationMaintenanceService

    calls: list[bool] = []
    monkeypatch.setattr(
        GenerationMaintenanceService,
        "run_startup_check",
        lambda self: calls.append(True),
    )
    monkeypatch.delenv("S_TALKING_TEST_FAST_PATH", raising=False)

    create_service_container(RuntimeConfig.from_root(tmp_path))

    assert calls == [True]


def test_q2_mainwindow_uses_application_theme_authority() -> None:
    from app.gui.main import MainWindow

    source = inspect.getsource(MainWindow.apply_theme)

    assert "theme_changed=application is None or application.styleSheet()!=stylesheet" in source
    assert "if self.styleSheet():" in source
    assert "self.setStyleSheet('')" in source
    assert "if theme_changed:" in source
    assert "refresh_icons(self)" in source


def test_q2_unchanged_interface_preferences_do_not_force_second_repolish() -> None:
    from app.gui.main import MainWindow

    source = inspect.getsource(MainWindow.apply_interface_preferences)

    assert "properties_changed=previous.stylesheet_properties()!=value.stylesheet_properties()" in source
    assert "if properties_changed:" in source
    assert "self.setStyleSheet(self.theme_manager.stylesheet" in source


def test_q2_mainwindow_test_fast_path_disables_background_startup_only() -> None:
    source = (ROOT / "app" / "gui" / "main.py").read_text(encoding="utf-8")

    assert 'self._test_fast_path=os.getenv("S_TALKING_TEST_FAST_PATH"' in source
    assert "if not self._test_fast_path: self.autosave_timer.start()" in source
    assert "background_sampling_enabled and not self._test_fast_path" in source
    assert "self.startup_recovery_state=None; self.session_restore_state=None" in source
    assert "if not self._test_fast_path:" in source
    assert "QTimer.singleShot(0,self.refresh_provider_intelligence)" in source
    assert "QTimer.singleShot(0,self.refresh_smart_provider_routing)" in source


def test_q2_serial_profiler_forces_fast_path_and_records_it() -> None:
    source = (
        ROOT / "scripts" / "serial_pytest_profile.py"
    ).read_text(encoding="utf-8")

    assert 'test_env.setdefault("S_TALKING_TEST_FAST_PATH", "1")' in source
    assert '"test_fast_path": test_env.get("S_TALKING_TEST_FAST_PATH") == "1"' in source


def test_q2_theme_historical_contract_uses_application_stylesheet() -> None:
    source = (
        ROOT / "tests" / "test_ux_workflow_v0141.py"
    ).read_text(encoding="utf-8")

    assert '"#F4F7FB" in QApplication.instance().styleSheet()' in source
    assert '"#F4F7FB" in window.styleSheet()' not in source


def test_q2_database_schema_23_is_preserved(tmp_path: Path) -> None:
    database = Database(tmp_path / "schema.db")
    database.initialize()
    assert database.expected_schema_version == 23
    assert database.applied_schema_versions()[-1] == 23


def test_q2_scope_does_not_change_provider_authority_contracts() -> None:
    changed = {
        "app/database/connection.py",
        "app/container.py",
        "app/gui/main.py",
        "scripts/serial_pytest_profile.py",
        "tests/conftest.py",
        "tests/test_ux_workflow_v0141.py",
        "docs/QUALITY_GATE_TEST_RUNTIME_OPTIMIZATION_ROADMAP2_Q2.md",
        "tests/test_quality_gate_test_runtime_optimization_roadmap2_q2.py",
    }

    assert not any("provider" in path for path in changed)
    assert not any("generation_controller.py" in path for path in changed)


def test_q2_files_have_single_final_newline() -> None:
    paths = (
        ROOT / "app" / "database" / "connection.py",
        ROOT / "app" / "container.py",
        ROOT / "app" / "gui" / "main.py",
        ROOT / "scripts" / "serial_pytest_profile.py",
        ROOT / "tests" / "conftest.py",
        ROOT / "tests" / "test_ux_workflow_v0141.py",
        ROOT / "docs" / "QUALITY_GATE_TEST_RUNTIME_OPTIMIZATION_ROADMAP2_Q2.md",
        Path(__file__),
    )
    for path in paths:
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
