from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, QSettings, Qt
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models import AppSettings, JobStatus, TTSJob
from app.services.pronunciation_service import PronunciationService


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _window(tmp_path: Path):
    _app()
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    return MainWindow(context)


class QuotaProvider:
    def __init__(self, remaining: int | None) -> None:
        self.remaining = remaining

    def list_voices(self):
        return [{"voice_id": "voice", "name": "Danish", "labels": {"language": "da"}, "high_quality_base_model_ids": ["model"]}]

    def list_models(self):
        return [{"model_id": "model", "name": "Model", "can_do_text_to_speech": True, "languages": [{"language_id": "da"}]}]

    def get_subscription(self):
        if self.remaining is None:
            return {"tier": "creator", "status": "active"}
        return {"tier": "creator", "status": "active", "character_count": 1000 - self.remaining, "character_limit": 1000}

    def synthesize(self, _text, _settings):
        return b"RIFF"

    def close(self):
        pass


def test_dashboard_metrics_follow_full_range_and_selected_scope(tmp_path: Path) -> None:
    window = _window(tmp_path)
    jobs = [
        TTSJob(row_number=1, filename="one.wav", text="aaa"),
        TTSJob(row_number=2, filename="two.wav", text="bbbb", status=JobStatus.COMPLETED),
        TTSJob(row_number=3, filename="three.wav", text="ccccc", status=JobStatus.FAILED),
    ]
    window.generation_controller.set_jobs(jobs)

    window.dashboard()
    assert window.cards["files"].value.text() == "3"
    assert window.cards["chars"].value.text() == "12"

    window.range_from.setValue(2)
    window.range_to.setValue(3)
    assert window.cards["files"].value.text() == "2"
    assert window.cards["chars"].value.text() == "9"

    window.generation_controller.set_generation_selection([3])
    window.dashboard()
    assert window.cards["files"].value.text() == "1"
    assert window.cards["chars"].value.text() == "5"

    window.generation_controller.clear_generation_selection()
    window.range_from.setValue(0)
    window.range_to.setValue(0)
    assert window.cards["files"].value.text() == "3"
    window.close()


def test_scoped_quota_sufficient_insufficient_and_unknown(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "out"
    output.mkdir()
    settings = AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model", language_code="da")
    jobs = [TTSJob(row_number=1, filename="one.mp3", text="x" * 10)]

    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: QuotaProvider(remaining=20))
    container = create_service_container(RuntimeConfig.from_root(tmp_path / "ok"))
    container.voice_service.refresh_catalog(settings)
    ok = container.preflight_service.run(jobs=jobs, settings=settings, output_dir=output)
    assert ok.can_start is True
    assert ok.quota_snapshot["remaining"] == 20

    monkeypatch.setattr("app.services.voice_service.create_provider", lambda _settings: QuotaProvider(remaining=5))
    container = create_service_container(RuntimeConfig.from_root(tmp_path / "low"))
    container.voice_service.refresh_catalog(settings)
    low = container.preflight_service.run(jobs=jobs, settings=settings, output_dir=output)
    assert low.can_start is False
    assert any(issue.code == "insufficient_quota" and issue.severity == "hard_error" for issue in low.issues)

    unknown_container = create_service_container(RuntimeConfig.from_root(tmp_path / "unknown"))
    unknown = unknown_container.preflight_service.run(jobs=jobs, settings=settings, output_dir=output)
    assert unknown.can_start is False
    issue = next(issue for issue in unknown.issues if issue.code == "quota_unknown")
    assert issue.overridable is True
    assert unknown.override_all_eligible("Known small test batch") >= 1
    assert unknown.can_start is True


def test_danish_short_pronunciation_aid_and_original_text_preserved() -> None:
    service = PronunciationService()
    settings = AppSettings(provider="elevenlabs", language_code="da", short_text_pronunciation_aid=True)
    short = service.prepare("mad", settings)
    long = service.prepare("Dette er en længere dansk sætning med tydelig kontekst.", settings)
    english = service.prepare("mad", settings.model_copy(update={"language_code": "en"}))
    disabled = service.prepare("mad", settings.model_copy(update={"short_text_pronunciation_aid": False}))
    job = TTSJob(row_number=1, filename="one.mp3", text="tak")

    assert short.aid_applied is False
    assert short.original_text == "mad"
    assert short.provider_text == "mad"
    assert short.strategy == "language_code_da"
    assert long.aid_applied is False
    assert english.provider_text == "mad"
    assert disabled.provider_text == "mad"
    assert service.prepare_job(job, settings).provider_text == job.text
    assert job.text == "tak"


def test_voice_browser_initial_geometry_clamps_and_keeps_bottom_actions(tmp_path: Path) -> None:
    _app()
    from app.gui.voice_browser import VoiceBrowserDialog

    QSettings("S Talking", "S Talking").setValue("voice_browser/size", QSize(240, 180))
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    dialog = VoiceBrowserDialog(service=context.voice_service, settings_provider=lambda: AppSettings(provider="mock"))
    dialog.show()
    _app().processEvents()

    assert dialog.width() >= 960
    assert dialog.height() >= 680
    assert dialog.details_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert not dialog.apply_button.isHidden()
    assert not dialog.audio_settings.isHidden()
    dialog.close()


def test_provider_status_panel_stable_and_elided(tmp_path: Path) -> None:
    window = _window(tmp_path)
    before = window.connection_status.sizeHint()
    long_message = "Network error: " + ("very long provider failure " * 20)

    window.set_provider_status("Testing...")
    testing = window.connection_status.sizeHint()
    window.set_provider_status(long_message)
    failed = window.connection_status.sizeHint()

    assert testing.height() == before.height() == failed.height()
    assert len(window.connection_status.text()) <= 55
    assert long_message in window.connection_status.toolTip()
    window.close()


def test_preflight_override_hard_error_cannot_be_overridden(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    output = tmp_path / "out"
    output.mkdir()
    state = container.preflight_service.run(
        jobs=[TTSJob.model_construct(row_number=1, filename="bad:name.wav", text="", status=JobStatus.PENDING)],
        settings=AppSettings(provider="mock"),
        output_dir=output,
    )

    assert any(issue.severity == "hard_error" and not issue.overridable for issue in state.issues)
    assert state.override_all_eligible("test") == 0
    assert state.can_start is False
