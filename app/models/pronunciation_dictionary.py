from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PronunciationRule:
    source: str
    replacement: str
    rule_type: str = "alias"
    language_code: str = "da"
    alphabet: str = ""
    case_sensitive: bool = False
    word_boundaries: bool = True
    enabled: bool = True
    notes: str = ""


@dataclass
class PronunciationDictionary:
    dictionary_id: str
    name: str
    language_code: str = "da"
    version_id: str | None = None
    provider: str = "elevenlabs"
    source_path: Path | None = None
    active: bool = False
    model_compatibility: str = "all_tts"
    source: str = "Local"
    last_refreshed_at: str | None = None
    rules: list[PronunciationRule] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        payload = "\n".join(
            f"{rule.language_code}\t{rule.rule_type}\t{rule.source}\t{rule.replacement}"
            for rule in self.rules
            if rule.enabled
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def locator(self) -> dict[str, str]:
        value = {"pronunciation_dictionary_id": self.dictionary_id}
        if self.version_id:
            value["version_id"] = self.version_id
        return value


@dataclass(frozen=True)
class PronunciationDictionarySummary:
    dictionary_id: str
    name: str
    provider: str
    language_code: str
    model_compatibility: str
    version_id: str | None
    fingerprint: str
    rule_count: int
    active: bool = False
    last_refreshed_at: str | None = None
    source: str = "Local"
