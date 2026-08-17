from __future__ import annotations
import inspect
from pathlib import Path
import app.gui.main as main_module
from app.gui.main import MainWindow
from app.services.intelligent_tts_artifact_provenance_service import IntelligentTTSArtifactProvenanceService

def _source():
    return Path(main_module.__file__).read_text(encoding='utf-8')

def test_b5_main_installs_artifact_service_and_handles():
    s = _source()
    assert 'IntelligentTTSArtifactProvenanceService' in s
    assert 'self.current_intelligent_tts_artifact_plan=None' in s
    assert 'self.last_intelligent_tts_artifact_receipt=None' in s

def test_b5_plan_is_created_after_b2_verification_before_generation_start():
    s = _source()
    assert s.index('self.intelligent_tts_execution_service.verify_unchanged(') < s.index('self.begin_intelligent_tts_artifact_plan(') < s.index('if not self.generation_controller.start(')

def test_b5_service_has_no_generation_or_provider_authority():
    s = inspect.getsource(IntelligentTTSArtifactProvenanceService)
    for token in ('generation_controller.start', 'start_generation', 'run_preflight', 'create_provider', 'apply_smart_routing', 'detect_language', 'retry_failed'):
        assert token not in s

def test_b5_success_finalizes_artifacts_before_run_ledger():
    s = inspect.getsource(MainWindow.finish_execution_session)
    assert s.index('artifact_receipt=self.finalize_intelligent_tts_artifacts(') < s.index('self.finalize_intelligent_tts_run_ledger(')

def test_b5_execution_receipt_is_passed_to_artifact_receipt():
    s = inspect.getsource(MainWindow.finish_execution_session)
    assert 'receipt=receipt' in s and 'artifact_receipt=artifact_receipt' in s

def test_b5_ledger_final_event_links_artifact_receipt():
    s = inspect.getsource(MainWindow.finalize_intelligent_tts_run_ledger)
    assert "artifact_receipt_path=getattr(artifact_receipt,'path',None)" in s

def test_b5_failure_path_still_finalizes_artifact_evidence():
    s = inspect.getsource(MainWindow.finish_execution_session)
    assert s.count('artifact_receipt=self.finalize_intelligent_tts_artifacts(') >= 2

def test_b5_project_close_clears_current_plan_without_erasing_last_receipt():
    s = _source()
    assert 'self.current_intelligent_tts_artifact_plan=None;' in s
    assert 'self.last_intelligent_tts_artifact_receipt=None' in s
