from __future__ import annotations

import inspect
from pathlib import Path

import app.gui.main as main_module
from app.gui.main import MainWindow
from app.services.intelligent_tts_operations_intelligence_service import (
    IntelligentTTSOperationsIntelligenceService,
)


def _source() -> str:
    return Path(main_module.__file__).read_text(encoding="utf-8")


def test_b6_main_installs_operations_service_and_handles() -> None:
    source = _source()
    assert "IntelligentTTSOperationsIntelligenceService" in source
    assert "self.intelligent_tts_operations_intelligence_service=" in source
    assert "self.last_intelligent_tts_operations_snapshot=None" in source
    assert "self.last_intelligent_tts_operations_rollup=None" in source


def test_b6_tracks_current_binding_separately_from_last_binding() -> None:
    source = _source()
    assert "self.current_intelligent_tts_execution=None" in source
    assert "self.current_intelligent_tts_execution=execution_binding" in source
    assert "self.last_intelligent_tts_execution=execution_binding" in source


def test_b6_operations_snapshot_is_after_artifact_before_ledger() -> None:
    source = inspect.getsource(MainWindow.finish_execution_session)
    artifact = source.index(
        "artifact_receipt=self.finalize_intelligent_tts_artifacts("
    )
    operations = source.index(
        "operations_snapshot=self.finalize_intelligent_tts_operations("
    )
    ledger = source.index(
        "self.finalize_intelligent_tts_run_ledger("
    )
    assert artifact < operations < ledger


def test_b6_operations_uses_current_resume_assessment_not_stale_last() -> None:
    source = inspect.getsource(
        MainWindow.finalize_intelligent_tts_operations
    )
    assert (
        "recovery_assessment="
        "self.current_intelligent_tts_recovery_assessment"
        in source
    )
    begin = inspect.getsource(
        MainWindow.begin_intelligent_tts_run_ledger
    )
    assert "self.current_intelligent_tts_recovery_assessment=None" in begin
    assert "self.current_intelligent_tts_recovery_assessment=assessment" in begin


def test_b6_ledger_final_event_links_operations_snapshot() -> None:
    source = inspect.getsource(
        MainWindow.finalize_intelligent_tts_run_ledger
    )
    assert (
        "operations_snapshot_path="
        "getattr(operations_snapshot,'path',None)"
        in source
    )


def test_b6_failure_path_still_creates_operations_evidence() -> None:
    source = inspect.getsource(
        MainWindow.finish_execution_session
    )
    assert source.count(
        "operations_snapshot=self.finalize_intelligent_tts_operations("
    ) >= 2


def test_b6_service_has_no_execution_or_output_mutation_authority() -> None:
    source = inspect.getsource(
        IntelligentTTSOperationsIntelligenceService
    )
    for token in (
        "generation_controller.start",
        "run_preflight",
        "apply_smart_routing",
        "retry_failed",
        "detect_language",
        "unlink(",
        "rename(",
        "replace_output",
    ):
        assert token not in source


def test_b6_project_close_clears_current_not_historical_operations() -> None:
    source = _source()
    assert "self.current_intelligent_tts_execution=None;" in source
    assert "self.current_intelligent_tts_recovery_assessment=None;" in source
    assert "self.last_intelligent_tts_operations_snapshot=None" in source
    assert "self.last_intelligent_tts_operations_rollup=None" in source
