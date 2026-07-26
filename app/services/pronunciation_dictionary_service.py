from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from app.models.pronunciation_dictionary import (
    PronunciationDictionary,
    PronunciationDictionarySummary,
    PronunciationRule,
)


class PronunciationDictionaryService:
    """Stores pronunciation dictionary metadata and local editable rules."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def list_dictionaries(self, *, language_code: str | None = None) -> list[PronunciationDictionarySummary]:
        result: list[PronunciationDictionarySummary] = []
        for path in sorted(self.directory.glob("*.json")):
            dictionary = self.load(path.stem)
            if language_code and dictionary.language_code.lower() != language_code.lower():
                continue
            result.append(
                PronunciationDictionarySummary(
                    dictionary_id=dictionary.dictionary_id,
                    name=dictionary.name,
                    provider=dictionary.provider,
                    language_code=dictionary.language_code,
                    model_compatibility=dictionary.model_compatibility,
                    version_id=dictionary.version_id,
                    fingerprint=dictionary.fingerprint,
                    rule_count=len(dictionary.rules),
                    active=dictionary.active,
                    last_refreshed_at=dictionary.last_refreshed_at,
                    source=dictionary.source,
                )
            )
        return result

    def create(
        self,
        name: str,
        *,
        language_code: str = "da",
        version_id: str | None = None,
        rules: list[PronunciationRule] | None = None,
    ) -> PronunciationDictionary:
        dictionary = PronunciationDictionary(
            dictionary_id=uuid.uuid4().hex,
            name=name.strip() or "Pronunciation dictionary",
            language_code=language_code,
            version_id=version_id,
            rules=list(rules or []),
        )
        self.validate_rules(dictionary)
        self.save(dictionary)
        return dictionary

    def refresh_remote_metadata(
        self,
        provider: object,
        *,
        provider_name: str = "elevenlabs",
    ) -> list[PronunciationDictionarySummary]:
        method = getattr(provider, "list_pronunciation_dictionaries", None)
        if not callable(method):
            return self.list_dictionaries()
        now = datetime.now(timezone.utc).isoformat()
        for item in method():
            dictionary_id = str(item.get("dictionary_id") or item.get("id") or "").strip()
            if not dictionary_id:
                continue
            dictionary = PronunciationDictionary(
                dictionary_id=dictionary_id,
                name=str(item.get("name") or dictionary_id),
                language_code=str(item.get("language_code") or item.get("language") or "da"),
                version_id=str(item.get("version_id") or item.get("version") or "") or None,
                provider=provider_name,
                model_compatibility=str(item.get("model_compatibility") or "provider_catalog"),
                rules=[],
                source="Remote",
                last_refreshed_at=now,
            )
            self.save(dictionary)
        return self.list_dictionaries()

    def sync_remote(
        self,
        provider: object,
        dictionary: PronunciationDictionary,
        *,
        model_id: str | None = None,
    ) -> PronunciationDictionary:
        self.validate_rules(dictionary, model_id=model_id)
        if dictionary.source_path and dictionary.source in {"Imported", "Local metadata"}:
            method = getattr(provider, "create_pronunciation_dictionary_from_file", None)
            if not callable(method):
                raise RuntimeError("Provider does not support pronunciation dictionary file upload.")
            metadata = method(dictionary.source_path, name=dictionary.name)
        elif dictionary.source in {"Remote", "Synced", "Stale"} and dictionary.dictionary_id:
            method = getattr(provider, "set_pronunciation_dictionary_rules", None)
            if not callable(method):
                raise RuntimeError("Provider does not support pronunciation dictionary rule updates.")
            metadata = method(dictionary.dictionary_id, dictionary.rules)
        else:
            method = getattr(provider, "create_pronunciation_dictionary_from_rules", None)
            if not callable(method):
                raise RuntimeError("Provider does not support pronunciation dictionary creation from rules.")
            metadata = method(name=dictionary.name, rules=dictionary.rules)
        return self._apply_remote_metadata(dictionary, metadata, source="Synced")

    def add_remote_rule(self, provider: object, dictionary_id: str, rule: PronunciationRule, *, model_id: str | None = None) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        candidate = PronunciationDictionary(**{**dictionary.__dict__, "rules": [*dictionary.rules, rule]})
        self.validate_rules(candidate, model_id=model_id)
        method = getattr(provider, "add_pronunciation_dictionary_rules", None)
        if not callable(method):
            raise RuntimeError("Provider does not support adding pronunciation dictionary rules.")
        metadata = method(dictionary.dictionary_id, [rule])
        dictionary.rules.append(rule)
        return self._apply_remote_metadata(dictionary, metadata, source="Synced")

    def set_remote_rules(self, provider: object, dictionary_id: str, rules: list[PronunciationRule], *, model_id: str | None = None) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        candidate = PronunciationDictionary(**{**dictionary.__dict__, "rules": list(rules)})
        self.validate_rules(candidate, model_id=model_id)
        method = getattr(provider, "set_pronunciation_dictionary_rules", None)
        if not callable(method):
            raise RuntimeError("Provider does not support setting pronunciation dictionary rules.")
        metadata = method(dictionary.dictionary_id, rules)
        dictionary.rules = list(rules)
        return self._apply_remote_metadata(dictionary, metadata, source="Synced")

    def remove_remote_rules(self, provider: object, dictionary_id: str, rule_strings: list[str]) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        method = getattr(provider, "remove_pronunciation_dictionary_rules", None)
        if not callable(method):
            raise RuntimeError("Provider does not support removing pronunciation dictionary rules.")
        metadata = method(dictionary.dictionary_id, rule_strings)
        dictionary.rules = [rule for rule in dictionary.rules if rule.source not in set(rule_strings)]
        return self._apply_remote_metadata(dictionary, metadata, source="Synced")

    def verify_remote_version(self, provider: object, dictionary_id: str, version_id: str | None) -> tuple[bool, str]:
        method = getattr(provider, "get_pronunciation_dictionary", None)
        if not callable(method):
            return False, "Provider cannot verify pronunciation dictionary versions."
        metadata = method(dictionary_id)
        latest = str(metadata.get("version_id") or "") or None
        if version_id and latest and latest != version_id:
            try:
                dictionary = self.load(dictionary_id)
                dictionary.version_id = latest
                dictionary.source = "Stale"
                dictionary.last_refreshed_at = datetime.now(timezone.utc).isoformat()
                self.save(dictionary)
            except Exception:
                pass
            return False, f"Dictionary version changed from {version_id} to {latest}."
        return True, "Dictionary version is current."

    def import_pls(self, path: Path, *, name: str | None = None, version_id: str | None = None) -> PronunciationDictionary:
        tree = ElementTree.parse(path)
        root = tree.getroot()
        language_code = root.attrib.get("{http://www.w3.org/XML/1998/namespace}lang") or root.attrib.get("lang") or "da"
        rules: list[PronunciationRule] = []
        for lexeme in root.findall(".//{*}lexeme"):
            grapheme = (lexeme.findtext("{*}grapheme") or "").strip()
            alias = (lexeme.findtext("{*}alias") or "").strip()
            phoneme_node = lexeme.find("{*}phoneme")
            phoneme = (phoneme_node.text if phoneme_node is not None and phoneme_node.text else "").strip()
            if grapheme and alias:
                rules.append(PronunciationRule(grapheme, alias, "alias", language_code))
            elif grapheme and phoneme:
                alphabet = phoneme_node.attrib.get("alphabet", "") if phoneme_node is not None else ""
                rules.append(PronunciationRule(grapheme, phoneme, "phoneme", language_code, alphabet=alphabet))
        dictionary = PronunciationDictionary(
            dictionary_id=uuid.uuid4().hex,
            name=name or path.stem,
            language_code=language_code,
            version_id=version_id,
            source_path=path,
            source="Imported",
            rules=rules,
        )
        self.validate_rules(dictionary)
        self.save(dictionary)
        return dictionary

    def add_rule(self, dictionary_id: str, rule: PronunciationRule) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        dictionary.rules.append(rule)
        self.validate_rules(dictionary)
        self.save(dictionary)
        return dictionary

    def update_rule(self, dictionary_id: str, index: int, rule: PronunciationRule) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        dictionary.rules[index] = rule
        self.validate_rules(dictionary)
        self.save(dictionary)
        return dictionary

    def delete_rule(self, dictionary_id: str, index: int) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        del dictionary.rules[index]
        self.save(dictionary)
        return dictionary

    def duplicate_rule(self, dictionary_id: str, index: int) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        rule = dictionary.rules[index]
        dictionary.rules.insert(index + 1, PronunciationRule(**rule.__dict__))
        self.validate_rules(dictionary)
        self.save(dictionary)
        return dictionary

    def rename(self, dictionary_id: str, name: str) -> PronunciationDictionary:
        dictionary = self.load(dictionary_id)
        dictionary.name = name.strip() or dictionary.name
        self.save(dictionary)
        return dictionary

    def set_active(self, dictionary_id: str | None, *, provider: str = "elevenlabs", language_code: str | None = None) -> None:
        for summary in self.list_dictionaries(language_code=language_code):
            dictionary = self.load(summary.dictionary_id)
            if dictionary.provider == provider:
                dictionary.active = dictionary.dictionary_id == dictionary_id
                self.save(dictionary)

    def delete_metadata(self, dictionary_id: str) -> None:
        self._path(dictionary_id).unlink(missing_ok=True)

    def export_metadata(self, dictionary_id: str, path: Path) -> Path:
        dictionary = self.load(dictionary_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._to_payload(dictionary), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def export_pls(self, dictionary_id: str, path: Path) -> Path:
        dictionary = self.load(dictionary_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<lexicon version="1.0" xml:lang="{dictionary.language_code}" xmlns="http://www.w3.org/2005/01/pronunciation-lexicon">',
        ]
        for rule in dictionary.rules:
            if not rule.enabled:
                continue
            lines.append("  <lexeme>")
            lines.append(f"    <grapheme>{self._xml(rule.source)}</grapheme>")
            if rule.rule_type == "phoneme":
                alphabet = f' alphabet="{self._xml(rule.alphabet or "ipa")}"'
                lines.append(f"    <phoneme{alphabet}>{self._xml(rule.replacement)}</phoneme>")
            else:
                lines.append(f"    <alias>{self._xml(rule.replacement)}</alias>")
            lines.append("  </lexeme>")
        lines.append("</lexicon>")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def save(self, dictionary: PronunciationDictionary) -> None:
        path = self._path(dictionary.dictionary_id)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._to_payload(dictionary), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def load(self, dictionary_id: str) -> PronunciationDictionary:
        data = json.loads(self._path(dictionary_id).read_text(encoding="utf-8"))
        return PronunciationDictionary(
            dictionary_id=str(data.get("dictionary_id") or dictionary_id),
            name=str(data.get("name") or "Pronunciation dictionary"),
            language_code=str(data.get("language_code") or "da"),
            version_id=data.get("version_id"),
            provider=str(data.get("provider") or "elevenlabs"),
            source_path=Path(data["source_path"]) if data.get("source_path") else None,
            active=bool(data.get("active", False)),
            model_compatibility=str(data.get("model_compatibility") or "all_tts"),
            source=str(data.get("source") or "Local"),
            last_refreshed_at=data.get("last_refreshed_at"),
            rules=[
                PronunciationRule(
                    source=str(rule.get("source") or ""),
                    replacement=str(rule.get("replacement") or ""),
                    rule_type=str(rule.get("rule_type") or "alias"),
                    language_code=str(rule.get("language_code") or data.get("language_code") or "da"),
                    alphabet=str(rule.get("alphabet") or ""),
                    case_sensitive=bool(rule.get("case_sensitive", False)),
                    word_boundaries=bool(rule.get("word_boundaries", True)),
                    enabled=bool(rule.get("enabled", True)),
                    notes=str(rule.get("notes") or ""),
                )
                for rule in data.get("rules", [])
                if rule.get("source") and rule.get("replacement")
            ],
        )

    def locators_for(self, dictionary_ids: list[str]) -> list[dict[str, str]]:
        locators: list[dict[str, str]] = []
        for dictionary_id in dictionary_ids:
            dictionary = self.load(dictionary_id)
            locators.append(dictionary.locator)
        return locators

    def alias_warning_for(self, dictionary: PronunciationDictionary) -> str | None:
        if dictionary.language_code.lower().startswith("en"):
            return None
        if any(rule.rule_type == "phoneme" for rule in dictionary.rules):
            return "Non-English phoneme rules may be unsupported by the selected provider/model; use explicit aliases when needed."
        return None

    def validate_rules(self, dictionary: PronunciationDictionary, *, model_id: str | None = None) -> list[str]:
        issues: list[str] = []
        seen: dict[tuple[str, str, bool], PronunciationRule] = {}
        phoneme_supported = self.phoneme_supported(dictionary.provider, model_id or "", dictionary.language_code)
        for rule in dictionary.rules:
            if not rule.source.strip():
                issues.append("Rule grapheme cannot be empty.")
            if not rule.replacement.strip():
                issues.append(f"Rule replacement cannot be empty for {rule.source!r}.")
            if rule.rule_type not in {"alias", "phoneme"}:
                issues.append(f"Unsupported rule type: {rule.rule_type}.")
            if rule.rule_type == "phoneme" and not phoneme_supported:
                issues.append(f"Phoneme rule is not supported for {dictionary.language_code}/{model_id or 'selected model'}.")
            key = (rule.source if rule.case_sensitive else rule.source.casefold(), rule.language_code.lower(), rule.case_sensitive)
            existing = seen.get(key)
            if existing and existing.replacement != rule.replacement:
                issues.append(f"Conflicting pronunciation rules for {rule.source!r}.")
            seen[key] = rule
        if issues:
            raise ValueError("\n".join(dict.fromkeys(issues)))
        return []

    @staticmethod
    def phoneme_supported(provider: str, model_id: str, language_code: str) -> bool:
        if provider != "elevenlabs":
            return False
        if model_id == "eleven_v3":
            return True
        if model_id == "eleven_flash_v2" and language_code.lower().startswith("en"):
            return True
        return language_code.lower().startswith("en")

    def _apply_remote_metadata(
        self,
        dictionary: PronunciationDictionary,
        metadata: dict[str, object],
        *,
        source: str,
    ) -> PronunciationDictionary:
        old_id = dictionary.dictionary_id
        new_id = str(metadata.get("dictionary_id") or old_id).strip() or old_id
        dictionary.dictionary_id = new_id
        dictionary.name = str(metadata.get("name") or dictionary.name)
        dictionary.version_id = str(metadata.get("version_id") or dictionary.version_id or "") or None
        dictionary.language_code = str(metadata.get("language_code") or dictionary.language_code)
        dictionary.model_compatibility = str(metadata.get("model_compatibility") or dictionary.model_compatibility)
        dictionary.provider = "elevenlabs"
        dictionary.source = source
        dictionary.last_refreshed_at = datetime.now(timezone.utc).isoformat()
        self.save(dictionary)
        if old_id != new_id:
            self.delete_metadata(old_id)
        return dictionary

    def _to_payload(self, dictionary: PronunciationDictionary) -> dict[str, object]:
        return {
            "schema_version": 1,
            "dictionary_id": dictionary.dictionary_id,
            "name": dictionary.name,
            "language_code": dictionary.language_code,
            "version_id": dictionary.version_id,
            "provider": dictionary.provider,
            "source_path": str(dictionary.source_path) if dictionary.source_path else None,
            "active": dictionary.active,
            "model_compatibility": dictionary.model_compatibility,
            "source": dictionary.source,
            "last_refreshed_at": dictionary.last_refreshed_at,
            "rules": [rule.__dict__ for rule in dictionary.rules],
        }

    def _path(self, dictionary_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", dictionary_id).strip("._") or "dictionary"
        return self.directory / f"{safe}.json"

    @staticmethod
    def _xml(value: str) -> str:
        return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
