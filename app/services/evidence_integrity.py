from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


class EvidenceIntegrityMixin:
    """Shared tamper-evident evidence primitives for operational services.

    Phase 83 centralizes the deterministic JSON, SHA-256, privacy, archive-name,
    and UTC timestamp helpers that had been duplicated across the Phase 80-82
    operational services.  Subclasses retain their own safety contracts and
    privacy regexes, while this mixin supplies the common implementation.
    """

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    @classmethod
    def _payload_digest(cls, payload: Mapping[str, object]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _write_json(path: Path, payload: Mapping[str, object]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def _verify_safety_contract(cls, payload: Mapping[str, object]) -> bool:
        contract = cls._safety_contract()
        return all(payload.get(key) == value for key, value in contract.items())

    @classmethod
    def _contains_private_text(cls, text: str) -> bool:
        secret_pattern = getattr(cls, "_SECRET_RE", None)
        path_pattern = getattr(cls, "_ABSOLUTE_PATH_RE", None)
        if secret_pattern is not None and secret_pattern.search(text):
            return True
        return bool(path_pattern is not None and path_pattern.search(text))

    @classmethod
    def _contains_private_payload(cls, payload: object) -> bool:
        text = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
        return cls._contains_private_text(text)

    @staticmethod
    def _safe_archive_name(name: str) -> bool:
        pure = PurePosixPath(name)
        return (
            bool(name)
            and not pure.is_absolute()
            and ".." not in pure.parts
            and "\\" not in name
        )

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _now_iso(self) -> str:
        return self._now().isoformat()

    def _now_timestamp(self) -> float:
        return self._now().timestamp()
