from __future__ import annotations

import inspect
from pathlib import Path

import app.gui.main as main_module
from app.gui.main import MainWindow
from app.services.intelligent_tts_run_ledger_service import IntelligentTTSRunLedgerService


def _main_source() -> str:
    return Path(main_module.__file__).read_text(encoding="utf-8")


def test_b3_main_installs_run_ledger_service_and_handles() -> None:
    source = _main_source()
    assert "IntelligentTTSRunLedgerService" in source
    assert "self.intelligent_tts_run_ledger_service=" in source
    assert "self.current_intelligent_tts_ledger=None" in source
    assert "self.last_intelligent_tts_ledger=None" in source


def test_b3_ledger_begins_after_binding_verification_before_generation_start() -> None:
    source = _main_source()
    verify = source.index("self.intelligent_tts_execution_service.verify_unchanged(")
    begin = source.index("self.begin_intelligent_tts_run_ledger(")
    generation_start = source.index("if not self.generation_controller.start(")
    assert verify < begin < generation_start


def test_b3_existing_generation_start_remains_the_only_start_authority() -> None:
    source = inspect.getsource(IntelligentTTSRunLedgerService)
    for token in (
        "generation_controller.start",
        "start_generation",
        "GenerationWorker",
        "run_preflight",
        "create_provider",
        "apply_smart_routing",
        "detect_language",
    ):
        assert token not in source


def test_b3_existing_sync_session_drives_ledger_lifecycle() -> None:
    source = inspect.getsource(MainWindow.sync_execution_session)
    assert "generation_execution_session_service.sync_session" in source
    assert "self.sync_intelligent_tts_run_ledger(status,metrics)" in source


def test_b3_finish_session_links_ledger_after_execution_receipt() -> None:
    source = inspect.getsource(MainWindow.finish_execution_session)
    receipt = source.index("generation_execution_receipt_service.create_receipt(")
    finalize = source.index("self.finalize_intelligent_tts_run_ledger(")
    assert receipt < finalize
    assert "summary=summary" in source
    assert "receipt=receipt" in source


def test_b3_finished_path_passes_real_generation_summary() -> None:
    source = inspect.getsource(MainWindow.finished)
    assert "self.finish_execution_session(result,report.report_html,s)" in source


def test_b3_failed_path_passes_explicit_failure_summary() -> None:
    source = inspect.getsource(MainWindow.failed)
    assert "failure_summary=" in source
    assert "self.finish_execution_session('failed',report.report_html,failure_summary)" in source


def test_b3_project_close_clears_current_ledger_handle() -> None:
    source = _main_source()
    assert "self.pending_resume_receipt=None; self.current_intelligent_tts_ledger=None;" in source
