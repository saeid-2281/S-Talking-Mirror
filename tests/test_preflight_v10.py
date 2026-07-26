from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models import AppSettings, JobStatus, TTSJob
from app.services.preflight_service import PreflightService


@pytest.fixture
def qt_app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def job(row: int = 2, filename: str = "one.wav", text: str = "Hej") -> TTSJob:
    return TTSJob(row_number=row, filename=filename, text=text)


def service(tmp_path: Path) -> PreflightService:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    return container.preflight_service


def test_valid_batch(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()

    state = service(tmp_path).run(jobs=[job()], settings=AppSettings(provider="mock"), output_dir=output)

    assert state.can_start is True
    assert state.status == "Ready"
    assert state.estimated_characters == 3


def test_missing_csv_jobs_and_no_pending(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    completed = job()
    completed.status = JobStatus.COMPLETED

    state = service(tmp_path).run(
        jobs=[completed],
        settings=AppSettings(provider="mock"),
        output_dir=output,
        csv_path=tmp_path / "missing.csv",
    )

    assert state.can_start is False
    assert any("CSV file is missing" in issue.message for issue in state.issues)
    assert any("No pending jobs" in issue.message for issue in state.issues)


def test_empty_text_duplicate_invalid_filename_and_path_traversal(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    empty = TTSJob.model_construct(row_number=2, filename="bad:name.wav", text="", status=JobStatus.PENDING)
    duplicate = job(3, "dup.wav", "same")
    duplicate2 = job(4, "dup.wav", "same")
    traversal = job(5, "../escape.wav", "ok")

    state = service(tmp_path).run(
        jobs=[empty, duplicate, duplicate2, traversal],
        settings=AppSettings(provider="mock"),
        output_dir=output,
    )

    messages = "\n".join(issue.message for issue in state.issues)
    assert state.can_start is False
    assert "Text is empty" in messages
    assert "Duplicate output filename" in messages
    assert "Filename is invalid" in messages
    assert "escapes the output directory" in messages
    assert state.duplicate_texts == [3, 4]


def test_missing_output_directory_and_unwritable_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "new-out"
    state = service(tmp_path).run(jobs=[job()], settings=AppSettings(provider="mock"), output_dir=missing)
    assert state.output_directory_ready is True
    assert any(issue.severity == "warning" and "does not exist" in issue.message for issue in state.issues)
    assert not missing.exists()

    output = tmp_path / "out"
    output.mkdir()

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr("app.services.preflight_service.tempfile.NamedTemporaryFile", denied)
    blocked = service(tmp_path).run(jobs=[job()], settings=AppSettings(provider="mock"), output_dir=output)
    assert blocked.output_directory_ready is False
    assert any("not writable" in issue.message for issue in blocked.issues)


def test_existing_outputs_and_skip_existing(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / "one.wav").write_bytes(b"RIFF")

    state = service(tmp_path).run(jobs=[job()], settings=AppSettings(provider="mock", skip_existing=True), output_dir=output)
    blocked = service(tmp_path).run(jobs=[job()], settings=AppSettings(provider="mock", skip_existing=False), output_dir=output)

    assert state.warnings == 1
    assert state.can_start is True
    assert blocked.blocking_errors == 1
    assert blocked.can_start is False


def test_missing_provider_settings_and_piper_model_validation(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()

    eleven = service(tmp_path).run(jobs=[job()], settings=AppSettings(provider="elevenlabs"), output_dir=output)
    piper = service(tmp_path).run(
        jobs=[job()],
        settings=AppSettings(provider="piper", piper_model_path=str(tmp_path / "missing.onnx")),
        output_dir=output,
    )

    assert any("API key" in issue.message for issue in eleven.issues)
    assert any("voice" in issue.message.lower() for issue in eleven.issues)
    assert any("Piper model" in issue.message for issue in piper.issues)


def test_elevenlabs_voice_model_limit_and_quota_warning(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    output = tmp_path / "out"
    output.mkdir()
    container.voice_repository.upsert(
        provider="elevenlabs",
        voice_id="voice-1",
        name="Voice",
        metadata={"compatible_model_ids": ["model-a"]},
    )

    state = container.preflight_service.run(
        jobs=[job(text="x" * 5001)],
        settings=AppSettings(provider="elevenlabs", api_key="sk_SECRET", voice_id="voice-1", model_id="model-b"),
        output_dir=output,
    )

    assert any("Model is not available" in issue.message for issue in state.issues)
    assert any("Text exceeds model limit" in issue.message for issue in state.issues)
    assert any("quota" in issue.message.lower() or "cost" in issue.message.lower() for issue in state.issues)


def test_unsupported_extension_and_language_metadata_validation(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    output = tmp_path / "out"
    output.mkdir()
    container.voice_repository.upsert(
        provider="elevenlabs",
        voice_id="voice-1",
        name="Voice",
        metadata={
            "compatible_model_ids": ["model-a"],
            "verified_languages": [{"language_id": "da"}],
        },
    )

    state = container.preflight_service.run(
        jobs=[job()],
        settings=AppSettings(
            provider="elevenlabs",
            api_key="sk_SECRET",
            voice_id="voice-1",
            model_id="model-a",
            language_code="sv",
            file_extension=".txt",
        ),
        output_dir=output,
    )

    assert state.can_start is False
    assert any("extension is unsupported" in issue.message for issue in state.issues)
    assert any("Language code is not available" in issue.message for issue in state.issues)


def test_safe_automatic_fixes(tmp_path: Path) -> None:
    output = tmp_path / "out"
    (output / "one.wav").parent.mkdir(parents=True)
    (output / "one.wav").write_bytes(b"RIFF")
    jobs = [
        TTSJob.model_construct(row_number=2, filename="bad:name.wav", text="  hello  ", status=JobStatus.PENDING),
        job(3, "one.wav", "same"),
        job(4, "one.wav", "same"),
    ]
    preflight = service(tmp_path)
    state = preflight.run(jobs=jobs, settings=AppSettings(provider="mock", skip_existing=True), output_dir=output)

    changed = preflight.apply_safe_fixes(state, jobs, AppSettings(provider="mock", skip_existing=True), output)

    assert changed >= 3
    assert jobs[0].filename == "bad_name.wav"
    assert jobs[0].text == "  hello  "
    assert jobs[1].status == JobStatus.SKIPPED
    assert jobs[2].filename == "one-2.wav"


def test_dry_run_makes_no_provider_request_and_writes_reports(qt_app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.gui.main import MainWindow

    called = {"provider": 0}
    monkeypatch.setattr("app.gui.worker.create_provider", lambda _settings: called.__setitem__("provider", called["provider"] + 1))
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    window = MainWindow(context)
    output = tmp_path / "out"
    output.mkdir()
    window.out.setText(str(output))
    window.generation_controller.set_jobs([job()])
    window.show_preflight_dialog = lambda _state: None

    window.dry_run()

    assert called["provider"] == 0
    assert context.preflight_service.latest is not None
    assert context.preflight_service.latest.report_dir is not None
    report = context.preflight_service.latest.report_dir
    assert (report / "preflight.json").exists()
    assert (report / "preflight.md").exists()
    assert (report / "preflight.html").exists()
    assert (report / "issues.csv").exists()


def test_blocking_errors_disable_start_and_settings_changes_invalidate_preflight(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    window = MainWindow(context)
    window.generation_controller.set_jobs([job()])
    window.provider.setCurrentText("elevenlabs")
    window.key.clear()
    window.voice.clear()

    state = window.run_preflight()
    assert state.status == "Blocked by errors"
    assert window.startb.isEnabled() is False

    window.provider.setCurrentText("mock")
    assert context.preflight_service.latest is None
    assert window.preflight_status.text() == "Preflight: Not checked"


def test_generated_reports_are_machine_readable_and_secret_free(tmp_path: Path) -> None:
    preflight = service(tmp_path)
    output = tmp_path / "out"
    output.mkdir()
    state = preflight.run(
        jobs=[job()],
        settings=AppSettings(provider="elevenlabs", api_key="sk_SECRET", voice_id="", model_id="model"),
        output_dir=output,
    )
    report = preflight.write_report(state, "Project")

    payload = json.loads((report / "preflight.json").read_text(encoding="utf-8"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in report.iterdir() if path.is_file())
    assert payload["status"] == "Blocked by errors"
    assert "issues" in payload
    assert "sk_SECRET" not in text
    assert "S Talking Preflight Report" in (report / "preflight.md").read_text(encoding="utf-8")
    assert "<html" in (report / "preflight.html").read_text(encoding="utf-8")
