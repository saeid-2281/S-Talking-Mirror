from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
QUALITY_GATE = ROOT / "scripts" / "quality-gate.ps1"
RELEASE_CHECK = ROOT / "scripts" / "release-check.ps1"
SERIAL_PROFILER = ROOT / "scripts" / "serial_pytest_profile.py"
PARALLEL_RUNNER = ROOT / "scripts" / "parallel_pytest.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "serial_pytest_profile_q11",
        SERIAL_PROFILER,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_q11_default_full_gate_is_serial_profiled() -> None:
    text = QUALITY_GATE.read_text(encoding="utf-8-sig")
    assert "pytest (full / stable serial profiled)" in text
    assert "scripts/serial_pytest_profile.py" in text
    assert "serial-latest.json" in text


def test_q11_parallel_gate_is_explicit_opt_in_only() -> None:
    text = QUALITY_GATE.read_text(encoding="utf-8-sig")
    assert "[switch]$ExperimentalParallel" in text
    assert "S_TALKING_EXPERIMENTAL_PARALLEL_GATE" in text
    assert "pytest (full / experimental isolated hybrid)" in text
    assert "scripts/parallel_pytest.py" in text


def test_q11_legacy_raw_serial_fallback_is_preserved() -> None:
    text = QUALITY_GATE.read_text(encoding="utf-8-sig")
    assert "[switch]$LegacyFull" in text
    assert "S_TALKING_LEGACY_FULL_GATE" in text
    assert "pytest (full / legacy raw serial)" in text
    assert "& $Python -m pytest" in text


def test_q11_release_check_defaults_to_serial_profiled() -> None:
    text = RELEASE_CHECK.read_text(encoding="utf-8-sig")
    assert "[switch]$ExperimentalParallel" in text
    assert "scripts/serial_pytest_profile.py" in text
    assert "pytest-performance.json" in text
    assert "scripts/parallel_pytest.py" in text
    assert "$LegacyPytest" in text


def test_q11_release_check_result_contract_is_preserved() -> None:
    text = RELEASE_CHECK.read_text(encoding="utf-8-sig")
    assert 'if ($text -match "(\\d+) passed")' in text
    assert "artifacts\\release-check" in text
    assert "result.json" in text
    assert "release_smoke" in text
    assert "--ux-certification-export" in text


def test_q11_serial_profiler_junit_aggregation(tmp_path: Path) -> None:
    module = _module()

    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")

    ET.SubElement(
        suite,
        "testcase",
        classname="tests.test_a",
        name="test_a",
        time="1.5",
    )

    skipped = ET.SubElement(
        suite,
        "testcase",
        classname="tests.test_b",
        name="test_b",
        time="0.25",
    )
    ET.SubElement(skipped, "skipped")

    failed = ET.SubElement(
        suite,
        "testcase",
        classname="tests.test_c",
        name="test_c",
        time="2.0",
    )
    ET.SubElement(failed, "failure")

    path = tmp_path / "pytest.xml"
    ET.ElementTree(root).write(
        path,
        encoding="utf-8",
        xml_declaration=True,
    )

    summary = module.parse_junit([path])

    assert summary.tests == 3
    assert summary.passed == 1
    assert summary.skipped == 1
    assert summary.failures == 1
    assert summary.errors == 0
    assert summary.aggregate_test_seconds == 3.75
    assert summary.slowest[0][1].endswith("test_c")


def test_q11_serial_profiler_preserves_slow_test_evidence() -> None:
    text = SERIAL_PROFILER.read_text(encoding="utf-8")
    assert "--durations=25" in text
    assert "--durations-min=0.5" in text
    assert "slowest" in text
    assert "aggregate_test_seconds" in text
    assert '"mode": "serial_profiled"' in text


def test_q11_serial_profiler_emits_release_parser_compatible_summary() -> None:
    text = SERIAL_PROFILER.read_text(encoding="utf-8")
    assert "SERIAL_PROFILE_SUMMARY:" in text
    assert 'f"{summary.passed} passed, "' in text


def test_q11_parallel_runner_is_retained_as_experimental_asset() -> None:
    assert PARALLEL_RUNNER.is_file()
    text = PARALLEL_RUNNER.read_text(encoding="utf-8")
    assert "Isolated hybrid pytest plan" in text
    assert "ui_one_file_per_process" in text


def test_q11_does_not_change_database_or_production_app() -> None:
    changed = {
        "scripts/quality-gate.ps1",
        "scripts/release-check.ps1",
        "scripts/serial_pytest_profile.py",
        "docs/QUALITY_GATE_PERFORMANCE_RECOVERY_ROADMAP2_Q11.md",
        "tests/test_quality_gate_performance_recovery_roadmap2_q11.py",
    }

    assert not any(path.startswith("app/") for path in changed)
    assert not any(path.startswith("app/database/") for path in changed)


def test_q11_files_have_single_final_newline() -> None:
    for path in (
        QUALITY_GATE,
        RELEASE_CHECK,
        SERIAL_PROFILER,
        ROOT / "docs" / "QUALITY_GATE_PERFORMANCE_RECOVERY_ROADMAP2_Q11.md",
        Path(__file__),
    ):
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")
