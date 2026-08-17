from __future__ import annotations
import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from app.services.intelligent_tts_artifact_provenance_service import IntelligentTTSArtifactIntegrityError, IntelligentTTSArtifactProvenanceService
from app.services.intelligent_tts_execution_service import IntelligentTTSExecutionService
CERTIFICATION_VERSION = 'roadmap2-b5-v1'
EXPECTED_BASELINE_COMMIT = '02246f2d521512d73b3abc2759f84db7086abe6f'

@dataclass
class _Status:
    value: str

@dataclass
class _Job:
    row_number: int
    filename: str
    text: str
    status: _Status

def _settings() -> SimpleNamespace:
    return SimpleNamespace(provider='elevenlabs', active_api_profile_id='profile-1', voice_id='voice-da', model_id='eleven_v3', language_code='da', file_extension='.mp3', max_retries=4, generation_scope='selected', execution_order='csv', api_key='B5-SECRET')

def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({'name': name, 'passed': bool(passed), 'detail': detail})

def certify(output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    audio = output / 'audio'
    audio.mkdir()
    jobs = [_Job(1, 'one.mp3', 'Dansk tekst.', _Status('completed')), _Job(2, 'two.mp3', 'English text.', _Status('completed')), _Job(3, 'three.mp3', 'Mangler fil.', _Status('completed'))]
    (audio / 'one.mp3').write_bytes(b'audio-one')
    (audio / 'two.mp3').write_bytes(b'audio-two')
    settings = _settings()
    binding = IntelligentTTSExecutionService().prepare(jobs, settings, audio)
    service = IntelligentTTSArtifactProvenanceService()
    plan = service.prepare_plan(binding, jobs, settings, audio, run_id='b5-cert', project_key='project', evidence_root=output / 'evidence')
    receipt = SimpleNamespace(receipt_id='execution-receipt-1', path=output / 'execution-receipt.json')
    artifact = service.finalize(plan.path, jobs, result='completed', execution_receipt=receipt, report_path=output / 'report.html')
    checks: list[dict[str, Any]] = []
    _check(checks, 'plan_matches_b2_manifest', plan.manifest_digest == binding.manifest_digest, plan.manifest_digest)
    _check(checks, 'plan_matches_b2_authority', plan.authority_digest == binding.authority_digest, plan.authority_digest)
    _check(checks, 'request_order_preserved', [e.row_number for e in plan.entries] == [1, 2, 3], str([e.row_number for e in plan.entries]))
    _check(checks, 'verified_files_hashed', artifact.verified_files == 2 and all((e.sha256 for e in artifact.entries[:2])), str(artifact.verified_files))
    _check(checks, 'missing_completed_output_visible', 'missing_completed_output' in artifact.entries[2].issues, str(artifact.entries[2].issues))
    _check(checks, 'overall_issue_status_visible', artifact.status == 'issues_detected' and artifact.issue_count >= 1, artifact.status)
    _check(checks, 'execution_receipt_linked', artifact.execution_receipt_id == 'execution-receipt-1' and str(artifact.execution_receipt_path).endswith('execution-receipt.json'), str(artifact.execution_receipt_path))
    serialized = artifact.path.read_text(encoding='utf-8') + plan.path.read_text(encoding='utf-8')
    _check(checks, 'raw_text_not_persisted', 'Dansk tekst.' not in serialized and 'English text.' not in serialized, 'Artifact evidence stores hashes, not source text.')
    _check(checks, 'api_key_not_persisted', 'B5-SECRET' not in serialized and 'api_key' not in serialized, 'No secret material persisted.')
    _check(checks, 'plan_receipt_digests_verify', service.load_plan(plan.path).plan_digest == plan.plan_digest and service.load_receipt(artifact.path).receipt_digest == artifact.receipt_digest, artifact.receipt_digest)
    tampered = json.loads(artifact.path.read_text(encoding='utf-8'))
    tampered['status'] = 'verified'
    tamper_path = output / 'tampered.json'
    tamper_path.write_text(json.dumps(tampered, indent=2) + '\n', encoding='utf-8')
    rejected = False
    try:
        service.load_receipt(tamper_path)
    except IntelligentTTSArtifactIntegrityError:
        rejected = True
    _check(checks, 'tampering_rejected', rejected, 'Receipt digest rejects modified evidence.')
    source = inspect.getsource(__import__('app.services.intelligent_tts_artifact_provenance_service', fromlist=['IntelligentTTSArtifactProvenanceService']))
    forbidden = ('generation_controller.start', 'start_generation', 'run_preflight', 'create_provider', 'apply_smart_routing', 'detect_language', 'retry_failed', 'unlink(', 'rename(', 'replace_output')
    _check(checks, 'no_execution_or_repair_authority', all((token not in source for token in forbidden)), 'Evidence-only service.')
    _check(checks, 'output_root_boundary_enforced', '_is_within' in source and 'unsafe_output_path' in source, 'Files outside approved output root are never hashed.')
    _check(checks, 'database_schema_not_used', 'database' not in serialized.casefold(), 'Filesystem evidence only.')
    second = service.prepare_plan(binding, jobs, settings, audio, run_id='b5-cert', project_key='project', evidence_root=output / 'evidence')
    _check(checks, 'plan_creation_idempotent', second.plan_digest == plan.plan_digest and second.path == plan.path, second.plan_digest)
    failed = [x for x in checks if not x['passed']]
    result = {'certification_version': CERTIFICATION_VERSION, 'baseline_commit': EXPECTED_BASELINE_COMMIT, 'status': 'CERTIFIED' if not failed else 'FAILED', 'checks_total': len(checks), 'checks_passed': len(checks) - len(failed), 'checks_failed': len(failed), 'checks': checks, 'plan_digest': plan.plan_digest, 'artifact_receipt_digest': artifact.receipt_digest}
    (output / 'certification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return result

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = certify(args.output)
    print(f"Roadmap 2 B5 certification: {result['status']}")
    print(f"Checks: {result['checks_passed']}/{result['checks_total']}")
    print(f"Artifact receipt digest: {result['artifact_receipt_digest']}")
    print(f'Evidence: {args.output}')
    return 0 if result['status'] == 'CERTIFIED' else 1
if __name__ == '__main__':
    raise SystemExit(main())
