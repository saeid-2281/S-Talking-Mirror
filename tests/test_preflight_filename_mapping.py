from __future__ import annotations

from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models import AppSettings, JobStatus, TTSJob


DANISH_TEXT = (
    "Dette er en længere dansk tekst med kommaer, citationstegn, skråstreger / og \\ samt "
    "spørgsmål? Den skal behandles som tekst, ikke som filnavn, selv når den indeholder tegn "
    "som normalt ville være ulovlige i Windows-filnavne."
)


def service(tmp_path: Path):
    return create_service_container(RuntimeConfig.from_root(tmp_path)).preflight_service


def test_valid_filename_ignores_punctuation_and_slashes_in_text(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    job = TTSJob(row_number=2, filename="d0-l01-a.mp3", text=DANISH_TEXT)

    state = service(tmp_path).run(
        jobs=[job],
        settings=AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
        output_dir=output,
    )

    filename_issues = [issue for issue in state.issues if "Filename" in issue.message]
    assert filename_issues == []
    assert state.estimated_characters == len(DANISH_TEXT)


def test_invalid_filename_issue_uses_filename_not_text(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    job = TTSJob(row_number=2, filename="bad:name.mp3", text="Gyldig tekst uden filnavnsproblemer.")

    state = service(tmp_path).run(
        jobs=[job],
        settings=AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
        output_dir=output,
    )

    issue = next(issue for issue in state.issues if issue.message == "Filename is invalid on Windows.")
    assert issue.filename == "bad:name.mp3"
    assert issue.filename == job.filename
    assert job.text not in issue.filename


def test_filename_sanitizer_never_changes_text_and_preserves_unicode_extension_and_collisions(tmp_path: Path) -> None:
    output = tmp_path / "out"
    jobs = [
        TTSJob(row_number=2, filename="dårlig:fil.mp3", text=DANISH_TEXT),
        TTSJob(row_number=3, filename="dårlig:fil.mp3", text="Anden tekst"),
        TTSJob(row_number=4, filename="NUL.mp3", text="Tredje tekst"),
    ]
    original_texts = [job.text for job in jobs]
    preflight = service(tmp_path)
    state = preflight.run(
        jobs=jobs,
        settings=AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
        output_dir=output,
    )

    plan = preflight.filename_fix_plan(
        state,
        jobs,
        AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
        output,
    )
    changed = preflight.apply_safe_fixes(
        state,
        jobs,
        AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
        output,
    )

    assert changed == 3
    assert [job.text for job in jobs] == original_texts
    assert jobs[0].filename == "dårlig_fil.mp3"
    assert jobs[1].filename == "dårlig_fil-2.mp3"
    assert jobs[2].filename == "audio.mp3"
    assert [(fix.row, fix.original_filename, fix.new_filename) for fix in plan] == [
        (2, "dårlig:fil.mp3", "dårlig_fil.mp3"),
        (3, "dårlig:fil.mp3", "dårlig_fil-2.mp3"),
        (4, "NUL.mp3", "audio.mp3"),
    ]
    assert all(DANISH_TEXT not in fix.original_filename and DANISH_TEXT not in fix.new_filename for fix in plan)


def test_existing_output_uses_filename_not_text(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    (output / "d0-l01-a.mp3").write_bytes(b"audio")
    job = TTSJob(row_number=2, filename="d0-l01-a.mp3", text="Tekst med forkert/path? men gyldigt filnavn.")

    state = service(tmp_path).run(
        jobs=[job],
        settings=AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model", skip_existing=True),
        output_dir=output,
    )

    existing = [issue for issue in state.issues if issue.message == "Output file already exists."]
    filename_errors = [issue for issue in state.issues if issue.message == "Filename is invalid on Windows."]
    assert existing and existing[0].filename == "d0-l01-a.mp3"
    assert filename_errors == []


def test_persisted_filename_updated_without_source_csv_or_text_change(tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    project = container.project_controller.new_project("Preflight", None, tmp_path / "out", AppSettings(provider="elevenlabs"))
    csv_path = tmp_path / "input.csv"
    csv_content = f"filename,text\nbad:name.mp3,{DANISH_TEXT}\n"
    csv_path.write_text(csv_content, encoding="utf-8")
    jobs = [TTSJob(row_number=2, filename="bad:name.mp3", text=DANISH_TEXT, status=JobStatus.PENDING)]
    container.generation_controller.set_jobs(
        jobs,
        project_id=project.project_id,
        output_dir=tmp_path / "out",
        settings=AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
    )
    state = container.preflight_service.run(
        jobs=jobs,
        settings=AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
        output_dir=tmp_path / "out",
    )

    container.preflight_service.apply_safe_fixes(
        state,
        jobs,
        AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
        tmp_path / "out",
    )
    container.generation_controller.set_jobs(
        jobs,
        project_id=project.project_id,
        output_dir=tmp_path / "out",
        settings=AppSettings(provider="elevenlabs", api_key="sk_TEST", voice_id="voice", model_id="model"),
    )
    restored = container.job_repository.restore_jobs(project.project_id)

    assert csv_path.read_text(encoding="utf-8") == csv_content
    assert restored[0].filename == "bad_name.mp3"
    assert restored[0].text == DANISH_TEXT
