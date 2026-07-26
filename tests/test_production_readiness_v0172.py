from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.config.runtime import RuntimeConfig
from app.gui.main import MainWindow
from app.models import AppSettings, TTSJob
from app.services.health_service import HealthService
from app.services.output_validation_service import OutputValidationService
from app.services.preflight_service import PreflightService
from app.services.provider_identity_service import ProviderIdentityService
from app.services.provider_readiness_service import ProviderReadinessService


class Git:
    def status(self):
        from app.services.git_service import GitStatus

        return GitStatus("unknown", True, [])


class Reports:
    def latest_report_dir(self):
        return None


class Diagnostics:
    latest_bundle = None


@pytest.fixture
def qt_app():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_provider_identity_uses_professional_display_names() -> None:
    service = ProviderIdentityService()

    assert service.display_name("aws_polly") == "Amazon Polly"
    assert service.display_name("mock") == "Mock / Test Provider"
    assert service.identity_for("elevenlabs").locality == "Cloud"


def test_readiness_matrix_marks_mock_ready_and_writes_json(tmp_path: Path) -> None:
    service = ProviderReadinessService()

    matrix = service.matrix(AppSettings(provider="mock"))
    path = service.write_matrix(tmp_path, AppSettings(provider="mock"))
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert matrix["mock"]["state"] == "Ready"
    assert payload["providers"]["mock"]["adapter_registered"] is True
    assert "elevenlabs" in payload["providers"]


def test_preflight_blocks_incomplete_optional_provider(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    service = PreflightService(runtime)
    jobs = [TTSJob(row_number=1, filename="one.mp3", text="Hej")]

    state = service.run(jobs=jobs, settings=AppSettings(provider="azure", api_key="placeholder"), output_dir=tmp_path)

    assert state.can_start is False
    assert any(issue.code == "provider_not_production_ready" for issue in state.issues)


def test_output_validation_rejects_text_error_body(tmp_path: Path) -> None:
    result = OutputValidationService.validate_bytes(b'{"error":"bad"}', tmp_path / "bad.mp3")

    assert result.ok is False
    assert "instead of audio" in result.message


def test_output_validation_atomic_finalizes_mock_wav(tmp_path: Path) -> None:
    from app.providers.mock import MockProvider

    audio = MockProvider(AppSettings(provider="mock")).synthesize("Hej", AppSettings(provider="mock"))
    target = tmp_path / "ok.wav"
    result = OutputValidationService.finalize_atomic(target, audio)

    assert result.ok is True
    assert target.read_bytes().startswith(b"RIFF")
    assert not list(tmp_path.glob(".*.tmp"))


def test_packaged_health_treats_development_checks_as_not_applicable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    service = HealthService(runtime, Git(), Reports(), Diagnostics())

    state = service.snapshot()

    assert state.runtime_domain == "packaged"
    assert state.development_available is False
    assert state.score >= 85
    assert any(item.status == "not_applicable" and item.name == "Tests" for item in state.breakdown)


def test_main_window_initial_geometry_is_clamped(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.container import create_service_container

    runtime = RuntimeConfig.from_root(tmp_path)
    window = MainWindow(create_application_context(create_service_container(runtime)))

    assert window.minimumWidth() == 1180
    assert window.minimumHeight() == 700
    assert window.width() <= max(1180, QApplication.primaryScreen().availableGeometry().width())
    assert hasattr(window, "project_context_bar")
    window.close()


def test_selected_row_exposes_resolved_request_without_secrets(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.container import create_service_container

    runtime = RuntimeConfig.from_root(tmp_path)
    window = MainWindow(create_application_context(create_service_container(runtime)))
    job = TTSJob(row_number=1, filename="d0-l01-a.wav", text="Hej verden")
    summary = window.resolved_request_summary(job, tmp_path / "d0-l01-a.wav")

    assert "Resolved request" in summary
    assert "Mock / Test Provider" in summary
    assert "api" not in summary.lower()
    window.close()
