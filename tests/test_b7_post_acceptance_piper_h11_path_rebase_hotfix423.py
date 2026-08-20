from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrate_local_engines_to_portable.ps1"


def test_h423_preserves_h11_source_root_rebase_and_new_state_root_rebase() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    legacy = '.Replace($SourcePortableRoot, $DestinationPortableRoot)'
    modern = '.Replace($StateSourcePortableRoot, $DestinationPortableRoot)'

    assert legacy in source
    assert modern in source
    assert source.count(legacy) >= 3
    assert source.count(modern) >= 3

    # Each compatibility rebase happens first, then the newer state-source rebase.
    for variable in ("SettingsText", "WorkspaceText", "LauncherText"):
        old_line = f"${variable} = ${variable}.Replace($SourcePortableRoot, $DestinationPortableRoot)"
        new_line = f"${variable} = ${variable}.Replace($StateSourcePortableRoot, $DestinationPortableRoot)"
        assert old_line in source
        assert new_line in source
        assert source.index(old_line) < source.index(new_line)


def test_h423_keeps_h11_voice_copy_and_canonical_voice_authority() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert 'Copy-Tree (Join-Path $SourceData "offline-voices")' in source
    assert "Copy-Tree $LegacyVoiceSource $CanonicalVoiceDestination" in source
    assert "Copy-Tree $CanonicalVoiceSource $CanonicalVoiceDestination" in source
    assert 'DestinationRuntimeData = Join-Path $DestinationData "data"' in source
