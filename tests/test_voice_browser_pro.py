from __future__ import annotations


from app.models.domain import AppSettings
from app.services.voice_service import AccountUsage, VoiceItem, VoiceService


def test_account_remaining_characters() -> None:
    usage = AccountUsage(tier="free", status="active", character_count=125, character_limit=1000)
    assert usage.remaining_characters == 875


def test_voice_search_text_contains_labels() -> None:
    item = VoiceItem(
        provider="elevenlabs",
        voice_id="voice-1",
        name="Freja",
        language="da",
        category="professional",
        description="Warm educational voice",
        labels={"accent": "Danish", "gender": "female", "age": "young"},
        is_favorite=False,
    )
    assert "danish" in VoiceService._search_text(item)
    assert "educational" in VoiceService._search_text(item)


def test_preview_cache_key_changes_with_model() -> None:
    item = VoiceItem(
        provider="elevenlabs",
        voice_id="voice-1",
        name="Freja",
        language="da",
        category="professional",
        description="",
        labels={},
        is_favorite=False,
    )
    first = VoiceService._preview_cache_key(item, "Hej", AppSettings(model_id="model-a"))
    second = VoiceService._preview_cache_key(item, "Hej", AppSettings(model_id="model-b"))
    assert first != second


def test_voice_browser_module_imports() -> None:
    from app.gui.voice_browser import VoiceBrowserDialog

    assert VoiceBrowserDialog is not None
