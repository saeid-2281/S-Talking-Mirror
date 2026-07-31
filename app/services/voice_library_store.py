from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class VoiceLibraryStore:
    """Persist recent-use, pin, and collection metadata per provider profile."""

    VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def scope_key(provider: str, profile_id: str | None) -> str:
        return f"{provider.strip().casefold()}|{(profile_id or 'temporary').strip()}"

    def list_collections(self, provider: str, profile_id: str | None) -> list[str]:
        scope = self._scope(provider, profile_id)
        collections = scope.get("collections", {})
        if not isinstance(collections, dict):
            return []
        return sorted((str(name) for name in collections), key=str.casefold)

    def collections_for_voice(self, provider: str, profile_id: str | None, voice_id: str) -> tuple[str, ...]:
        record = self._voice_record(provider, profile_id, voice_id)
        values = record.get("collections", [])
        if not isinstance(values, list):
            return ()
        return tuple(sorted({str(value) for value in values if str(value).strip()}, key=str.casefold))

    def add_to_collection(
        self,
        provider: str,
        profile_id: str | None,
        voice_id: str,
        collection: str,
    ) -> None:
        name = collection.strip()
        if not name:
            raise ValueError("Collection name cannot be empty.")
        payload = self._load()
        scope = self._mutable_scope(payload, provider, profile_id)
        collections = scope.setdefault("collections", {})
        collections.setdefault(name, {"created_at": self._now()})
        voices = scope.setdefault("voices", {})
        record = voices.setdefault(str(voice_id), {})
        current = {str(value) for value in record.get("collections", []) if str(value).strip()}
        current.add(name)
        record["collections"] = sorted(current, key=str.casefold)
        self._save(payload)

    def remove_from_collection(
        self,
        provider: str,
        profile_id: str | None,
        voice_id: str,
        collection: str,
    ) -> None:
        payload = self._load()
        scope = self._mutable_scope(payload, provider, profile_id)
        record = scope.setdefault("voices", {}).setdefault(str(voice_id), {})
        current = {str(value) for value in record.get("collections", []) if str(value).strip()}
        current.discard(collection)
        record["collections"] = sorted(current, key=str.casefold)
        self._save(payload)

    def delete_collection(self, provider: str, profile_id: str | None, collection: str) -> None:
        payload = self._load()
        scope = self._mutable_scope(payload, provider, profile_id)
        collections = scope.setdefault("collections", {})
        collections.pop(collection, None)
        for record in scope.setdefault("voices", {}).values():
            if not isinstance(record, dict):
                continue
            values = {str(value) for value in record.get("collections", []) if str(value).strip()}
            values.discard(collection)
            record["collections"] = sorted(values, key=str.casefold)
        self._save(payload)

    def set_pinned(self, provider: str, profile_id: str | None, voice_id: str, pinned: bool) -> None:
        payload = self._load()
        record = self._mutable_voice_record(payload, provider, profile_id, voice_id)
        record["pinned"] = bool(pinned)
        self._save(payload)

    def is_pinned(self, provider: str, profile_id: str | None, voice_id: str) -> bool:
        return bool(self._voice_record(provider, profile_id, voice_id).get("pinned", False))

    def mark_used(self, provider: str, profile_id: str | None, voice_id: str) -> None:
        payload = self._load()
        record = self._mutable_voice_record(payload, provider, profile_id, voice_id)
        record["last_used_at"] = self._now()
        record["use_count"] = max(0, self._as_int(record.get("use_count"))) + 1
        self._save(payload)

    def last_used_at(self, provider: str, profile_id: str | None, voice_id: str) -> str:
        return str(self._voice_record(provider, profile_id, voice_id).get("last_used_at") or "")

    def use_count(self, provider: str, profile_id: str | None, voice_id: str) -> int:
        return max(0, self._as_int(self._voice_record(provider, profile_id, voice_id).get("use_count")))

    def voice_ids_in_collection(
        self,
        provider: str,
        profile_id: str | None,
        collection: str | None = None,
    ) -> set[str]:
        scope = self._scope(provider, profile_id)
        voices = scope.get("voices", {})
        if not isinstance(voices, dict):
            return set()
        result: set[str] = set()
        for voice_id, record in voices.items():
            if not isinstance(record, dict):
                continue
            values = {str(value) for value in record.get("collections", []) if str(value).strip()}
            if collection is None:
                if values:
                    result.add(str(voice_id))
            elif collection in values:
                result.add(str(voice_id))
        return result

    def recent_voice_ids(self, provider: str, profile_id: str | None) -> set[str]:
        scope = self._scope(provider, profile_id)
        voices = scope.get("voices", {})
        if not isinstance(voices, dict):
            return set()
        return {
            str(voice_id)
            for voice_id, record in voices.items()
            if isinstance(record, dict) and str(record.get("last_used_at") or "")
        }

    def _voice_record(self, provider: str, profile_id: str | None, voice_id: str) -> dict[str, Any]:
        scope = self._scope(provider, profile_id)
        voices = scope.get("voices", {})
        if not isinstance(voices, dict):
            return {}
        record = voices.get(str(voice_id), {})
        return record if isinstance(record, dict) else {}

    def _scope(self, provider: str, profile_id: str | None) -> dict[str, Any]:
        payload = self._load()
        scopes = payload.get("scopes", {})
        if not isinstance(scopes, dict):
            return {}
        scope = scopes.get(self.scope_key(provider, profile_id), {})
        return scope if isinstance(scope, dict) else {}

    def _mutable_scope(
        self,
        payload: dict[str, Any],
        provider: str,
        profile_id: str | None,
    ) -> dict[str, Any]:
        scopes = payload.setdefault("scopes", {})
        scope = scopes.setdefault(self.scope_key(provider, profile_id), {})
        scope.setdefault("voices", {})
        scope.setdefault("collections", {})
        return scope

    def _mutable_voice_record(
        self,
        payload: dict[str, Any],
        provider: str,
        profile_id: str | None,
        voice_id: str,
    ) -> dict[str, Any]:
        scope = self._mutable_scope(payload, provider, profile_id)
        return scope.setdefault("voices", {}).setdefault(str(voice_id), {})

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": self.VERSION, "scopes": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"version": self.VERSION, "scopes": {}}
        if not isinstance(payload, dict) or payload.get("version") != self.VERSION:
            return {"version": self.VERSION, "scopes": {}}
        if not isinstance(payload.get("scopes"), dict):
            payload["scopes"] = {}
        return payload

    def _save(self, payload: dict[str, Any]) -> None:
        payload["version"] = self.VERSION
        payload.setdefault("scopes", {})
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
