from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.evidence_integrity import EvidenceIntegrityMixin
from app.services.evidence_refresh_service import EvidenceRefreshService
from app.services.operational_readiness_service import (
    OperationalReadinessCertificationService,
)
from app.services.operations_command_center_service import OperationsCommandCenterService


class _ExampleIntegrityService(EvidenceIntegrityMixin):
    _SECRET_RE = re.compile(r"(?i)(api[_-]?key|secret|token)")
    _ABSOLUTE_PATH_RE = re.compile(r"(?i)(?:[a-z]:[\\/]|/(?:home|users|tmp)/)")

    def __init__(self, now: datetime) -> None:
        self._now_provider = lambda: now

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "read_only": True,
            "automatic_publish": False,
            "private_data_included": False,
        }


def test_phase83_sha256_uses_shared_stream_safe_contract(tmp_path: Path) -> None:
    path = tmp_path / "artifact.bin"
    data = b"phase-83-evidence\x00\x01"
    path.write_bytes(data)
    assert _ExampleIntegrityService._sha256(path) == hashlib.sha256(data).hexdigest()


def test_phase83_payload_digest_is_deterministic_and_order_independent() -> None:
    first = {"b": 2, "a": [1, {"z": True}]}
    second = {"a": [1, {"z": True}], "b": 2}
    assert _ExampleIntegrityService._payload_digest(first) == _ExampleIntegrityService._payload_digest(second)


def test_phase83_json_round_trip_preserves_dictionary_payload(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "evidence.json"
    payload = {"schema_version": 1, "status": "certified", "value": "æøå"}
    _ExampleIntegrityService._write_json(path, payload)
    assert _ExampleIntegrityService._read_json(path) == payload


def test_phase83_json_reader_rejects_invalid_and_non_dictionary_payloads(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    sequence = tmp_path / "sequence.json"
    sequence.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert _ExampleIntegrityService._read_json(invalid) is None
    assert _ExampleIntegrityService._read_json(sequence) is None
    assert _ExampleIntegrityService._read_json(tmp_path / "missing.json") is None


def test_phase83_archive_name_guard_rejects_escape_and_absolute_paths() -> None:
    assert _ExampleIntegrityService._safe_archive_name("evidence/manifest.json") is True
    assert _ExampleIntegrityService._safe_archive_name("../secret.txt") is False
    assert _ExampleIntegrityService._safe_archive_name("/absolute/file.json") is False
    assert _ExampleIntegrityService._safe_archive_name(r"folder\windows.json") is False


def test_phase83_privacy_scan_uses_subclass_policy() -> None:
    assert _ExampleIntegrityService._contains_private_payload({"status": "safe"}) is False
    assert _ExampleIntegrityService._contains_private_payload({"api_key": "abc"}) is True
    assert _ExampleIntegrityService._contains_private_payload({"path": r"C:\Users\name\file"}) is True
    assert _ExampleIntegrityService._contains_private_payload({"path": "/tmp/private/file"}) is True


def test_phase83_safety_contract_verification_remains_service_owned() -> None:
    valid = _ExampleIntegrityService._safety_contract()
    assert _ExampleIntegrityService._verify_safety_contract(valid) is True
    unsafe = dict(valid)
    unsafe["automatic_publish"] = True
    assert _ExampleIntegrityService._verify_safety_contract(unsafe) is False


def test_phase83_utc_helpers_normalize_naive_and_aware_datetimes() -> None:
    naive = _ExampleIntegrityService(datetime(2026, 8, 7, 20, 0, 0))
    assert naive._now().tzinfo == timezone.utc
    assert naive._now_iso().endswith("+00:00")

    cest = timezone(timedelta(hours=2))
    aware = _ExampleIntegrityService(datetime(2026, 8, 7, 20, 0, 0, tzinfo=cest))
    assert aware._now() == datetime(2026, 8, 7, 18, 0, 0, tzinfo=timezone.utc)
    assert aware._now_timestamp() == aware._now().timestamp()


def test_phase83_phase80_to_82_services_inherit_shared_primitives_without_overrides() -> None:
    migrated = (
        OperationsCommandCenterService,
        EvidenceRefreshService,
        OperationalReadinessCertificationService,
    )
    shared_names = {
        "_sha256",
        "_payload_digest",
        "_read_json",
        "_write_json",
        "_verify_safety_contract",
    }
    for service in migrated:
        assert issubclass(service, EvidenceIntegrityMixin)
        assert not shared_names.intersection(service.__dict__)
        for name in shared_names:
            assert callable(getattr(service, name))
