from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "scripts" / "migrate_local_engines_to_portable.ps1"


def test_h422_preserves_h11_fallback_and_new_state_source_authority() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    engine_legacy = 'Copy-Tree (Join-Path $SourceData "offline-voices")'
    state_legacy = "Copy-Tree $LegacyVoiceSource $CanonicalVoiceDestination"
    state_canonical = "Copy-Tree $CanonicalVoiceSource $CanonicalVoiceDestination"

    assert engine_legacy in source
    assert state_legacy in source
    assert state_canonical in source
    assert source.index(engine_legacy) < source.index(state_legacy)
    assert source.index(state_legacy) < source.index(state_canonical)


def test_h422_preserves_official_runtime_and_separate_frozen_gates() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "BootstrapPiperRuntimeRoot" in source
    assert "Official standalone Piper runtime" in source
    assert "--local-engines-runtime-verify" in source
    assert "& $PortableExe --local-engines-piper-synthesis-smoke" in source
    assert "LOCAL_ENGINES_RUNTIME_VERIFY=PASS" in source
    assert "LOCAL_ENGINES_PIPER_SYNTHESIS_SMOKE=PASS" in source
