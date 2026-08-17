from __future__ import annotations
import json
from dataclasses import dataclass
from types import SimpleNamespace
import pytest
from app.services.intelligent_tts_artifact_provenance_service import IntelligentTTSArtifactIntegrityError, IntelligentTTSArtifactProvenanceError, IntelligentTTSArtifactProvenanceService
from app.services.intelligent_tts_execution_service import IntelligentTTSExecutionService
from scripts.certify_intelligent_tts_artifact_provenance_roadmap2_b5 import CERTIFICATION_VERSION, EXPECTED_BASELINE_COMMIT, certify

@dataclass
class _Status:
    value: str

@dataclass
class _Job:
    row_number: int
    filename: str
    text: str
    status: _Status

def _settings(**updates):
    values = dict(provider='elevenlabs', active_api_profile_id='profile-1', voice_id='voice-1', model_id='model-1', language_code='da', file_extension='.mp3', max_retries=4, generation_scope='selected', execution_order='csv', api_key='SECRET')
    values.update(updates)
    return SimpleNamespace(**values)

def _jobs():
    return [_Job(1, 'a.mp3', 'Dansk', _Status('completed')), _Job(2, 'b.mp3', 'English', _Status('completed'))]

def _binding(tmp_path, jobs=None, settings=None):
    return IntelligentTTSExecutionService().prepare(jobs or _jobs(), settings or _settings(), tmp_path / 'audio')

def test_b5_locks_to_b4_certified_baseline():
    assert EXPECTED_BASELINE_COMMIT == '02246f2d521512d73b3abc2759f84db7086abe6f'
    assert CERTIFICATION_VERSION == 'roadmap2-b5-v1'

def test_b5_plan_preserves_b2_request_identity(tmp_path):
    jobs = _jobs()
    settings = _settings()
    binding = _binding(tmp_path, jobs, settings)
    plan = IntelligentTTSArtifactProvenanceService().prepare_plan(binding, jobs, settings, tmp_path / 'audio', run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    assert plan.manifest_digest == binding.manifest_digest
    assert plan.authority_digest == binding.authority_digest
    assert tuple((e.request_id for e in plan.entries)) == binding.request_ids

def test_b5_plan_is_privacy_safe(tmp_path):
    jobs = _jobs()
    settings = _settings(api_key='TOPSECRET')
    binding = _binding(tmp_path, jobs, settings)
    plan = IntelligentTTSArtifactProvenanceService().prepare_plan(binding, jobs, settings, tmp_path / 'audio', run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    text = plan.path.read_text()
    assert 'TOPSECRET' not in text and 'Dansk' not in text and ('api_key' not in text)

def test_b5_plan_rejects_binding_mismatch(tmp_path):
    jobs = _jobs()
    settings = _settings()
    binding = _binding(tmp_path, jobs, settings)
    changed = _settings(model_id='other')
    with pytest.raises(IntelligentTTSArtifactProvenanceError):
        IntelligentTTSArtifactProvenanceService().prepare_plan(binding, jobs, changed, tmp_path / 'audio', run_id='run', project_key='p', evidence_root=tmp_path / 'e')

def test_b5_hashes_completed_artifacts(tmp_path):
    jobs = _jobs()
    audio = tmp_path / 'audio'
    audio.mkdir()
    (audio / 'a.mp3').write_bytes(b'a')
    (audio / 'b.mp3').write_bytes(b'b')
    settings = _settings()
    binding = IntelligentTTSExecutionService().prepare(jobs, settings, audio)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, audio, run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    r = svc.finalize(plan.path, jobs, result='completed')
    assert r.status == 'verified' and r.verified_files == 2 and all((x.sha256 for x in r.entries))

def test_b5_missing_completed_output_is_issue(tmp_path):
    jobs = _jobs()
    audio = tmp_path / 'audio'
    audio.mkdir()
    (audio / 'a.mp3').write_bytes(b'a')
    settings = _settings()
    binding = IntelligentTTSExecutionService().prepare(jobs, settings, audio)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, audio, run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    r = svc.finalize(plan.path, jobs, result='completed')
    assert 'missing_completed_output' in r.entries[1].issues and r.status == 'issues_detected'

def test_b5_duplicate_planned_output_is_visible(tmp_path):
    jobs = [_Job(1, 'same.mp3', 'A', _Status('completed')), _Job(2, 'same.mp3', 'B', _Status('completed'))]
    audio = tmp_path / 'audio'
    audio.mkdir()
    (audio / 'same.mp3').write_bytes(b'x')
    settings = _settings()
    binding = IntelligentTTSExecutionService().prepare(jobs, settings, audio)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, audio, run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    r = svc.finalize(plan.path, jobs, result='completed')
    assert all(('duplicate_planned_output' in x.issues for x in r.entries))

def test_b5_noncompleted_existing_output_is_not_deleted(tmp_path):
    jobs = [_Job(1, 'a.mp3', 'A', _Status('failed'))]
    audio = tmp_path / 'audio'
    audio.mkdir()
    path = audio / 'a.mp3'
    path.write_bytes(b'preexisting')
    settings = _settings()
    binding = IntelligentTTSExecutionService().prepare(jobs, settings, audio)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, audio, run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    r = svc.finalize(plan.path, jobs, result='failed')
    assert path.read_bytes() == b'preexisting' and 'existing_output_for_noncompleted_job' in r.entries[0].issues

def test_b5_unsafe_output_path_is_never_hashed(tmp_path):
    jobs = [_Job(1, '../outside.mp3', 'A', _Status('completed'))]
    outside = tmp_path / 'outside.mp3'
    outside.write_bytes(b'outside')
    audio = tmp_path / 'audio'
    audio.mkdir()
    settings = _settings()
    binding = IntelligentTTSExecutionService().prepare(jobs, settings, audio)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, audio, run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    r = svc.finalize(plan.path, jobs, result='completed')
    assert 'unsafe_output_path' in r.entries[0].issues and r.entries[0].sha256 is None

def test_b5_execution_receipt_and_report_are_linked(tmp_path):
    jobs = _jobs()
    audio = tmp_path / 'audio'
    audio.mkdir()
    settings = _settings()
    binding = IntelligentTTSExecutionService().prepare(jobs, settings, audio)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, audio, run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    receipt = SimpleNamespace(receipt_id='rid', path=tmp_path / 'receipt.json')
    r = svc.finalize(plan.path, jobs, result='cancelled', execution_receipt=receipt, report_path=tmp_path / 'report.html')
    assert r.execution_receipt_id == 'rid' and r.execution_receipt_path.endswith('receipt.json') and r.report_path.endswith('report.html')

def test_b5_plan_creation_is_idempotent(tmp_path):
    jobs = _jobs()
    settings = _settings()
    binding = _binding(tmp_path, jobs, settings)
    svc = IntelligentTTSArtifactProvenanceService()
    a = svc.prepare_plan(binding, jobs, settings, tmp_path / 'audio', run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    b = svc.prepare_plan(binding, jobs, settings, tmp_path / 'audio', run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    assert a.plan_digest == b.plan_digest

def test_b5_tampered_receipt_is_rejected(tmp_path):
    jobs = _jobs()
    settings = _settings()
    binding = _binding(tmp_path, jobs, settings)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, tmp_path / 'audio', run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    r = svc.finalize(plan.path, jobs, result='cancelled')
    payload = json.loads(r.path.read_text())
    payload['status'] = 'verified'
    r.path.write_text(json.dumps(payload) + '\n')
    with pytest.raises(IntelligentTTSArtifactIntegrityError):
        svc.load_receipt(r.path)

def test_b5_service_does_not_mutate_jobs_or_settings(tmp_path):
    jobs = _jobs()
    settings = _settings()
    before = [(j.row_number, j.filename, j.text, j.status.value) for j in jobs]
    before_settings = dict(vars(settings))
    binding = _binding(tmp_path, jobs, settings)
    svc = IntelligentTTSArtifactProvenanceService()
    plan = svc.prepare_plan(binding, jobs, settings, tmp_path / 'audio', run_id='run', project_key='p', evidence_root=tmp_path / 'e')
    svc.finalize(plan.path, jobs, result='cancelled')
    assert before == [(j.row_number, j.filename, j.text, j.status.value) for j in jobs] and before_settings == vars(settings)

def test_b5_certification_is_machine_verifiable(tmp_path):
    result = certify(tmp_path / 'cert')
    assert result['status'] == 'CERTIFIED' and result['checks_failed'] == 0 and (result['checks_total'] == 15)
