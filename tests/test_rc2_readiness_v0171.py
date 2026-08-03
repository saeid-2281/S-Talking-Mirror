from __future__ import annotations

from pathlib import Path
from time import perf_counter

import app
from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.models import AppSettings, TTSJob
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.source_import_service import SourceImportService


def test_rc2_version_identity() -> None:
    assert app.__version__ == "0.18.2-rc1"
    assert app.__release_channel__ == "rc"
    assert 'version = "0.18.2rc1"' in Path("pyproject.toml").read_text(encoding="utf-8")
    assert "0.18.2-rc1" in Path("packaging/windows/version_info.txt").read_text(encoding="utf-8")


def test_build_script_writes_installer_result_contract() -> None:
    build = Path("scripts/build.ps1").read_text(encoding="utf-8")
    iss = Path("packaging/windows/S-Talking.iss").read_text(encoding="utf-8")

    assert "installer-result.json" in build
    assert "ISCC.exe" in build
    assert "S-Talking-$version-setup.exe" in build
    assert "Inno Setup not installed" in build
    assert "S-Talking-$version-installer-unavailable.txt" in build
    assert "DefaultDirName={localappdata}\\Programs\\S Talking" in iss
    assert "[UninstallDelete]" not in iss


def test_source_refresh_diff_relocation_and_collision_strategies(tmp_path: Path) -> None:
    first = tmp_path / "first.csv"
    moved = tmp_path / "moved.csv"
    first.write_text("filename,text\nsame.wav,One\n", encoding="utf-8")
    moved.write_text("filename,text\nsame.wav,Two\nextra.wav,Three\n", encoding="utf-8")
    service = SourceImportService()
    source = service.create_sources([first])[0]
    original = service.import_source(source)

    service.relocate_source(source, moved)
    refreshed = service.import_source(source)
    diff = service.refresh_diff(original.jobs, refreshed)

    assert source.source_path == moved
    assert diff.added_rows == 1
    assert diff.changed_rows == 1
    prefixed = service.apply_collision_strategy(refreshed.jobs, strategy="source_prefix")
    assert all(job.filename.startswith("moved-") for job in prefixed)
    routed = service.apply_collision_strategy(refreshed.jobs, strategy="source_subfolder")
    assert {job.output_subfolder for job in routed} == {"moved"}


def test_preflight_blocks_mixed_provider_overrides(tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    service = context.preflight_service
    jobs = [TTSJob(row_number=1, filename="one.wav", text="Hej", provider_override="openai")]

    state = service.run(jobs=jobs, settings=AppSettings(provider="mock"), output_dir=tmp_path / "out")

    assert any(issue.code == "mixed_provider_batch_disabled" for issue in state.issues)
    assert state.status == "Blocked by errors"


def test_optional_provider_absence_is_setup_state_not_startup_crash() -> None:
    cards = {card.provider_id: card for card in ProviderCatalogService().cards(AppSettings(provider="mock"))}

    for provider in ["azure", "google", "aws_polly", "kokoro"]:
        assert provider in cards
        assert cards[provider].setup_state in {"Ready", "Setup required"}
        assert "Traceback" not in cards[provider].message


def test_ten_thousand_job_filter_and_sort_performance(tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    jobs = [
        TTSJob(row_number=index, filename=f"{10_001-index:05d}.wav", text="Hej" * (index % 20 + 1), source_id="a" if index % 2 else "b")
        for index in range(1, 10_001)
    ]
    context.generation_controller.set_jobs(jobs, output_dir=tmp_path / "out", settings=AppSettings(provider="mock"))

    started = perf_counter()
    context.generation_controller.set_source_filter("a")
    source_jobs = context.generation_controller.visible_jobs()
    source_ms = (perf_counter() - started) * 1000
    started = perf_counter()
    context.generation_controller.set_execution_order("filename_asc")
    sorted_jobs = context.generation_controller.visible_jobs()
    sort_ms = (perf_counter() - started) * 1000

    assert len(source_jobs) == 5_000
    assert sorted_jobs[0].filename < sorted_jobs[-1].filename
    assert source_ms < 150
    assert sort_ms < 250
