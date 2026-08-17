from __future__ import annotations
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from app.services.intelligent_tts_execution_service import IntelligentTTSExecutionBinding
from app.services.intelligent_tts_production_service import IntelligentTTSProductionService, ProductionJobLike
ARTIFACT_PLAN_SCHEMA_VERSION = 1
ARTIFACT_RECEIPT_SCHEMA_VERSION = 1
_COMPLETED_STATUSES = frozenset({'completed', 'complete', 'done', 'success', 'succeeded'})
_NONCOMPLETED_STATUSES = frozenset({'failed', 'skipped', 'cancelled', 'canceled'})

class IntelligentTTSArtifactProvenanceError(RuntimeError):
    """Base error for B5 artifact provenance evidence."""

class IntelligentTTSArtifactIntegrityError(IntelligentTTSArtifactProvenanceError):
    """Raised when persisted B5 evidence no longer verifies."""

def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'), sort_keys=True)

def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode('utf-8')).hexdigest()

def _safe_component(value: str, fallback: str) -> str:
    normalized = re.sub('[^A-Za-z0-9._-]+', '-', str(value).strip()).strip('.-_')
    return (normalized or fallback)[:96]

def _job_status(job: Any) -> str:
    value = getattr(job, 'status', '')
    value = getattr(value, 'value', value)
    return str(value or 'unknown').strip().casefold() or 'unknown'

def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False

@dataclass(frozen=True)
class IntelligentTTSArtifactPlanEntry:
    request_id: str
    row_number: int
    filename: str
    output_path: str
    text_sha256: str
    character_count: int

    def to_dict(self) -> dict[str, Any]:
        return {'request_id': self.request_id, 'row_number': self.row_number, 'filename': self.filename, 'output_path': self.output_path, 'text_sha256': self.text_sha256, 'character_count': self.character_count}

@dataclass(frozen=True)
class IntelligentTTSArtifactPlan:
    schema_version: int
    run_id: str
    project_key: str
    manifest_digest: str
    authority_digest: str
    output_root: str
    entries: tuple[IntelligentTTSArtifactPlanEntry, ...]
    plan_digest: str
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {'schema_version': self.schema_version, 'run_id': self.run_id, 'project_key': self.project_key, 'manifest_digest': self.manifest_digest, 'authority_digest': self.authority_digest, 'output_root': self.output_root, 'entries': [entry.to_dict() for entry in self.entries], 'plan_digest': self.plan_digest}

@dataclass(frozen=True)
class IntelligentTTSArtifactResult:
    request_id: str
    row_number: int
    filename: str
    output_path: str
    job_status: str
    exists: bool
    size_bytes: int | None
    sha256: str | None
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {'request_id': self.request_id, 'row_number': self.row_number, 'filename': self.filename, 'output_path': self.output_path, 'job_status': self.job_status, 'exists': self.exists, 'size_bytes': self.size_bytes, 'sha256': self.sha256, 'issues': list(self.issues)}

@dataclass(frozen=True)
class IntelligentTTSArtifactReceipt:
    schema_version: int
    run_id: str
    project_key: str
    result: str
    plan_digest: str
    manifest_digest: str
    authority_digest: str
    execution_receipt_id: str | None
    execution_receipt_path: str | None
    report_path: str | None
    entries: tuple[IntelligentTTSArtifactResult, ...]
    verified_files: int
    issue_count: int
    status: str
    receipt_digest: str
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {'schema_version': self.schema_version, 'run_id': self.run_id, 'project_key': self.project_key, 'result': self.result, 'plan_digest': self.plan_digest, 'manifest_digest': self.manifest_digest, 'authority_digest': self.authority_digest, 'execution_receipt_id': self.execution_receipt_id, 'execution_receipt_path': self.execution_receipt_path, 'report_path': self.report_path, 'entries': [entry.to_dict() for entry in self.entries], 'verified_files': self.verified_files, 'issue_count': self.issue_count, 'status': self.status, 'receipt_digest': self.receipt_digest}

class IntelligentTTSArtifactProvenanceService:
    """Persist planned request identity and verify final output artifacts.

    B5 is evidence-only. It never generates, retries, deletes, renames, moves,
    repairs or replaces an output. It cannot run Preflight, select a provider,
    change account/voice/model/language, apply Smart Routing, or start/restart
    Generation.
    """

    def __init__(self, production_service: IntelligentTTSProductionService | None=None) -> None:
        self.production_service = production_service or IntelligentTTSProductionService()

    def prepare_plan(self, binding: IntelligentTTSExecutionBinding, jobs: Sequence[ProductionJobLike], settings: Any, output_dir: Path, *, run_id: str, project_key: str, evidence_root: Path, job_language_overrides: Mapping[int, str] | None=None) -> IntelligentTTSArtifactPlan:
        manifest = self.production_service.compile_manifest(jobs, settings, Path(output_dir), job_language_overrides=job_language_overrides)
        if manifest.manifest_digest != binding.manifest_digest:
            raise IntelligentTTSArtifactProvenanceError('Artifact plan manifest does not match B2 execution binding')
        if manifest.authority.digest != binding.authority_digest:
            raise IntelligentTTSArtifactProvenanceError('Artifact plan authority does not match B2 execution binding')
        if tuple((item.request_id for item in manifest.requests)) != binding.request_ids:
            raise IntelligentTTSArtifactProvenanceError('Artifact plan request identity does not match B2 execution binding')
        entries = tuple((IntelligentTTSArtifactPlanEntry(request_id=request.request_id, row_number=request.row_number, filename=request.filename, output_path=request.output_path, text_sha256=request.text_sha256, character_count=request.character_count) for request in manifest.requests))
        material = {'schema_version': ARTIFACT_PLAN_SCHEMA_VERSION, 'run_id': str(run_id), 'project_key': str(project_key), 'manifest_digest': binding.manifest_digest, 'authority_digest': binding.authority_digest, 'output_root': str(Path(output_dir)), 'entries': [entry.to_dict() for entry in entries]}
        plan_digest = _digest(material)
        path = self.plan_path(evidence_root, project_key, run_id)
        payload = dict(material)
        payload['plan_digest'] = plan_digest
        self._write_idempotent(path, payload, 'plan_digest')
        return self.load_plan(path)

    def finalize(self, plan_path: Path, jobs: Sequence[Any], *, result: str, execution_receipt: Any | None=None, report_path: str | Path | None=None) -> IntelligentTTSArtifactReceipt:
        plan = self.load_plan(Path(plan_path))
        jobs_by_row: dict[int, Any] = {}
        for job in jobs:
            try:
                row_number = int(getattr(job, 'row_number'))
            except (TypeError, ValueError, AttributeError):
                continue
            jobs_by_row.setdefault(row_number, job)
        normalized_result = str(result or 'unknown').strip().casefold() or 'unknown'
        collision_counts: dict[str, int] = {}
        for entry in plan.entries:
            key = str(Path(entry.output_path)).replace('\\', '/').casefold()
            collision_counts[key] = collision_counts.get(key, 0) + 1
        output_root = Path(plan.output_root)
        results: list[IntelligentTTSArtifactResult] = []
        for entry in plan.entries:
            job = jobs_by_row.get(entry.row_number)
            status = _job_status(job) if job is not None else 'job_missing'
            path = Path(entry.output_path)
            issues: list[str] = []
            exists = False
            size_bytes: int | None = None
            file_digest: str | None = None
            safe = _is_within(path, output_root)
            if not safe:
                issues.append('unsafe_output_path')
            else:
                exists = path.is_file()
                if exists:
                    try:
                        size_bytes = path.stat().st_size
                        file_digest = _file_sha256(path)
                    except OSError:
                        issues.append('output_unreadable')
                    if size_bytes == 0:
                        issues.append('empty_output')
            collision_key = str(path).replace('\\', '/').casefold()
            if collision_counts.get(collision_key, 0) > 1:
                issues.append('duplicate_planned_output')
            if status in _COMPLETED_STATUSES and (not exists):
                issues.append('missing_completed_output')
            elif status in _NONCOMPLETED_STATUSES and exists:
                issues.append('existing_output_for_noncompleted_job')
            elif status in {'pending', 'running', 'unknown', 'job_missing'} and normalized_result == 'completed':
                issues.append('nonterminal_status_after_completed_run')
            results.append(IntelligentTTSArtifactResult(request_id=entry.request_id, row_number=entry.row_number, filename=entry.filename, output_path=entry.output_path, job_status=status, exists=exists, size_bytes=size_bytes, sha256=file_digest, issues=tuple(sorted(set(issues)))))
        verified_files = sum((1 for item in results if item.exists and item.sha256 and (not item.issues)))
        issue_count = sum((len(item.issues) for item in results))
        status = 'verified' if issue_count == 0 else 'issues_detected'
        execution_receipt_id = getattr(execution_receipt, 'receipt_id', None) if execution_receipt is not None else None
        execution_receipt_path = getattr(execution_receipt, 'path', None) if execution_receipt is not None else None
        material = {'schema_version': ARTIFACT_RECEIPT_SCHEMA_VERSION, 'run_id': plan.run_id, 'project_key': plan.project_key, 'result': normalized_result, 'plan_digest': plan.plan_digest, 'manifest_digest': plan.manifest_digest, 'authority_digest': plan.authority_digest, 'execution_receipt_id': None if execution_receipt_id is None else str(execution_receipt_id), 'execution_receipt_path': None if execution_receipt_path is None else str(execution_receipt_path), 'report_path': None if report_path is None else str(report_path), 'entries': [item.to_dict() for item in results], 'verified_files': verified_files, 'issue_count': issue_count, 'status': status}
        receipt_digest = _digest(material)
        payload = dict(material)
        payload['receipt_digest'] = receipt_digest
        path = self.receipt_path(plan.path)
        self._write_idempotent(path, payload, 'receipt_digest')
        return self.load_receipt(path)

    @staticmethod
    def plan_path(evidence_root: Path, project_key: str, run_id: str) -> Path:
        return Path(evidence_root) / _safe_component(project_key, 'project') / (_safe_component(run_id, 'run') + '.intelligent-tts-artifact-plan.json')

    @staticmethod
    def receipt_path(plan_path: Path) -> Path:
        name = plan_path.name.replace('.intelligent-tts-artifact-plan.json', '.intelligent-tts-artifact-receipt.json')
        return plan_path.with_name(name)

    def load_plan(self, path: Path) -> IntelligentTTSArtifactPlan:
        payload = self._load_verified(path, 'plan_digest', ARTIFACT_PLAN_SCHEMA_VERSION)
        entries = tuple((IntelligentTTSArtifactPlanEntry(**item) for item in payload.get('entries') or []))
        return IntelligentTTSArtifactPlan(schema_version=int(payload['schema_version']), run_id=str(payload['run_id']), project_key=str(payload['project_key']), manifest_digest=str(payload['manifest_digest']), authority_digest=str(payload['authority_digest']), output_root=str(payload['output_root']), entries=entries, plan_digest=str(payload['plan_digest']), path=Path(path))

    def load_receipt(self, path: Path) -> IntelligentTTSArtifactReceipt:
        payload = self._load_verified(path, 'receipt_digest', ARTIFACT_RECEIPT_SCHEMA_VERSION)
        entries = tuple((IntelligentTTSArtifactResult(request_id=str(item['request_id']), row_number=int(item['row_number']), filename=str(item['filename']), output_path=str(item['output_path']), job_status=str(item['job_status']), exists=bool(item['exists']), size_bytes=None if item.get('size_bytes') is None else int(item['size_bytes']), sha256=None if item.get('sha256') is None else str(item['sha256']), issues=tuple((str(value) for value in item.get('issues') or []))) for item in payload.get('entries') or []))
        return IntelligentTTSArtifactReceipt(schema_version=int(payload['schema_version']), run_id=str(payload['run_id']), project_key=str(payload['project_key']), result=str(payload['result']), plan_digest=str(payload['plan_digest']), manifest_digest=str(payload['manifest_digest']), authority_digest=str(payload['authority_digest']), execution_receipt_id=None if payload.get('execution_receipt_id') is None else str(payload['execution_receipt_id']), execution_receipt_path=None if payload.get('execution_receipt_path') is None else str(payload['execution_receipt_path']), report_path=None if payload.get('report_path') is None else str(payload['report_path']), entries=entries, verified_files=int(payload['verified_files']), issue_count=int(payload['issue_count']), status=str(payload['status']), receipt_digest=str(payload['receipt_digest']), path=Path(path))

    @staticmethod
    def _load_verified(path: Path, digest_field: str, schema_version: int) -> dict[str, Any]:
        try:
            payload = json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntelligentTTSArtifactIntegrityError(f'Unable to read artifact evidence: {exc}') from exc
        if int(payload.get('schema_version', 0)) != schema_version:
            raise IntelligentTTSArtifactIntegrityError('Unsupported artifact evidence schema version')
        material = dict(payload)
        actual = str(material.pop(digest_field, ''))
        if not actual or actual != _digest(material):
            raise IntelligentTTSArtifactIntegrityError('Artifact evidence digest mismatch')
        return payload

    @staticmethod
    def _write_idempotent(path: Path, payload: Mapping[str, Any], digest_field: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError) as exc:
                raise IntelligentTTSArtifactIntegrityError(f'Existing artifact evidence is unreadable: {exc}') from exc
            if existing.get(digest_field) == payload.get(digest_field):
                return
            raise IntelligentTTSArtifactProvenanceError('Artifact evidence path already contains different evidence')
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        temporary.replace(path)
