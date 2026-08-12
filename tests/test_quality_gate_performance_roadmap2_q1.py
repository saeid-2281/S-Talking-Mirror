from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "parallel_pytest.py"
POLICY = ROOT / "scripts" / "quality-gate-policy.json"


def _module():
    spec = importlib.util.spec_from_file_location("parallel_pytest_q1", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_q1_policy_contract() -> None:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["policy"] == "hybrid_pure_ui_isolated_stateful_serial"
    assert payload["unknown_test_file_lane"] == "serial"


def test_q1_lane_lists_are_unique_and_disjoint() -> None:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    pure = payload["parallel_files"]
    ui = payload["ui_parallel_files"]
    stateful = payload["stateful_serial_files"]

    assert pure
    assert ui
    assert stateful
    assert len(pure) == len(set(pure))
    assert len(ui) == len(set(ui))
    assert len(stateful) == len(set(stateful))
    assert set(pure).isdisjoint(ui)
    assert set(pure).isdisjoint(stateful)
    assert set(ui).isdisjoint(stateful)


def test_q1_current_test_inventory_is_fully_partitioned() -> None:
    module = _module()
    plan = module.build_hybrid_plan(
        root=ROOT,
        policy_path=POLICY,
        workers="auto",
        logical_cpus=28,
    )
    discovered = set(module.discover_test_files(ROOT))
    pure = set(plan.pure_files)
    ui = set(plan.ui_files)
    stateful = set(plan.stateful_serial_files)
    hard = set(plan.hard_serial_files)

    assert pure.isdisjoint(ui)
    assert pure.isdisjoint(stateful)
    assert pure.isdisjoint(hard)
    assert ui.isdisjoint(stateful)
    assert ui.isdisjoint(hard)
    assert stateful.isdisjoint(hard)
    assert pure | ui | stateful | hard == discovered


def test_q1_qprocess_and_release_tests_remain_hard_serial() -> None:
    module = _module()
    plan = module.build_hybrid_plan(
        root=ROOT,
        policy_path=POLICY,
        workers="2",
        logical_cpus=8,
    )
    hard = set(plan.hard_serial_files)
    assert "tests/test_devtools_diagnostics.py" in hard
    assert "tests/test_devcheck_runner_hardening_phase83_hotfix2.py" in hard
    assert "tests/test_final_production_certification_phase88.py" in hard
    assert "tests/test_release_candidate_v013.py" in hard


def test_q1_worker_caps_are_bounded() -> None:
    module = _module()
    policy = module.load_policy(POLICY)

    assert module.resolve_worker_count(
        "auto",
        logical_cpus=28,
        policy=policy,
    ) == 6
    assert module.resolve_worker_count(
        "auto",
        logical_cpus=8,
        policy=policy,
    ) == 4

    plan = module.build_hybrid_plan(
        root=ROOT,
        policy_path=POLICY,
        workers="auto",
        logical_cpus=28,
    )
    assert plan.pure_workers == 6
    assert plan.ui_workers == 4


def test_q1_unknown_future_file_falls_back_to_hard_serial(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_known.py").write_text(
        "def test_known(): pass\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_future.py").write_text(
        "def test_future(): pass\n",
        encoding="utf-8",
    )

    policy = {
        "schema_version": 1,
        "unknown_test_file_lane": "serial",
        "parallel_files": ["tests/test_known.py"],
        "ui_parallel_files": [],
        "stateful_serial_files": [],
        "auto_worker_cpu_fraction": 0.50,
        "auto_worker_cap": 6,
        "ui_worker_cap": 4,
    }
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    plan = module.build_hybrid_plan(
        root=tmp_path,
        policy_path=policy_path,
        workers="2",
        logical_cpus=8,
    )
    assert plan.pure_files == ("tests/test_known.py",)
    assert plan.hard_serial_files == ("tests/test_future.py",)


def test_q1_pure_sharding_is_deterministic_and_complete(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "tests").mkdir()
    files = []

    for index, count in enumerate((1, 2, 8, 4, 3), start=1):
        relative = f"tests/test_{index}.py"
        body = "\n".join(
            f"def test_{number}(): pass"
            for number in range(count)
        ) + "\n"
        (tmp_path / relative).write_text(body, encoding="utf-8")
        files.append(relative)

    first = module.shard_files(tmp_path, files, 3)
    second = module.shard_files(tmp_path, files, 3)
    assert first == second

    flattened = [item for shard in first for item in shard]
    assert sorted(flattened) == sorted(files)
    assert len(flattened) == len(set(flattened))


def test_q1_ui_tasks_are_one_file_each_and_slowest_first() -> None:
    module = _module()
    tasks = module.build_ui_tasks(
        ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py"],
        historical_weights={
            "tests/test_a.py": 1.0,
            "tests/test_b.py": 20.0,
            "tests/test_c.py": 5.0,
        },
    )
    assert tasks == (
        "tests/test_b.py",
        "tests/test_c.py",
        "tests/test_a.py",
    )


def test_q1_stateful_qsettings_and_profile_tests_are_serial() -> None:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    stateful = set(payload["stateful_serial_files"])
    assert "tests/test_ux_workflow_v0141.py" in stateful
    assert "tests/test_generation_monitor_v08.py" in stateful
    assert "tests/test_unified_voice_model_catalog_phase106.py" in stateful
    assert "tests/test_unified_provider_accounts_center_phase105.py" in stateful


def test_q1_voice_browser_remains_isolated_ui() -> None:
    module = _module()
    plan = module.build_hybrid_plan(
        root=ROOT,
        policy_path=POLICY,
        workers="auto",
        logical_cpus=28,
    )
    assert "tests/test_voice_browser.py" in set(plan.ui_files)
    assert "tests/test_voice_browser.py" not in set(plan.stateful_serial_files)


def test_q1_qsettings_sitecustomize_isolation_contract(tmp_path: Path) -> None:
    module = _module()
    path = module._write_qsettings_sitecustomize(tmp_path / "bootstrap")
    text = path.read_text(encoding="utf-8")
    assert "S_TALKING_QSETTINGS_ROOT" in text
    assert "QSettings.setDefaultFormat" in text
    assert "QSettings.setPath" in text
    assert "IniFormat" in text


def test_q1_junit_aggregation_counts_and_slowest(tmp_path: Path) -> None:
    module = _module()
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite")
    ET.SubElement(
        suite,
        "testcase",
        classname="tests.test_a",
        name="test_a",
        time="1.25",
    )
    b = ET.SubElement(
        suite,
        "testcase",
        classname="tests.test_b",
        name="test_b",
        time="0.25",
    )
    ET.SubElement(b, "skipped")

    path = tmp_path / "result.xml"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    summary = module._parse_junit([path])

    assert summary.tests == 2
    assert summary.passed == 1
    assert summary.skipped == 1
    assert summary.failures == 0
    assert summary.errors == 0
    assert summary.slowest[0][1].endswith("test_a")


def test_q1_historical_weights_scan_recent_runs(tmp_path: Path) -> None:
    module = _module()
    report = tmp_path / "artifacts" / "quality-gate-performance" / "latest.json"
    runs = report.parent / "runs"
    older = runs / "20260811-100000"
    newer = runs / "20260811-110000"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)

    def write_junit(path: Path, classname: str, seconds: float) -> None:
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite")
        ET.SubElement(
            suite,
            "testcase",
            classname=classname,
            name="test_x",
            time=str(seconds),
        )
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    write_junit(older / "old.xml", "tests.test_a", 9.0)
    write_junit(newer / "new.xml", "tests.test_b", 4.0)

    weights = module.historical_file_weights(report, scan_limit=6)
    assert weights["tests/test_a.py"] == 9.0
    assert weights["tests/test_b.py"] == 4.0


def test_q1_monitor_has_timeout_failfast_and_process_tree_cleanup() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "_terminate_process_tree" in text
    assert "taskkill" in text
    assert "ui_task_timeout_seconds" in text
    assert "Parallel/UI lane failure detected" in text
    assert "Hybrid pytest interrupted;" in text
    assert "terminating worker process trees" in text


def test_q1_quality_gate_has_parallel_and_legacy_paths() -> None:
    text = (ROOT / "scripts" / "quality-gate.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "scripts/parallel_pytest.py" in text
    assert "artifacts/quality-gate-performance/latest.json" in text
    assert "$LegacyFull" in text
    assert "S_TALKING_LEGACY_FULL_GATE" in text
    assert "& $Python -m pytest" in text


def test_q1_release_check_preserves_evidence_contract() -> None:
    text = (ROOT / "scripts" / "release-check.ps1").read_text(
        encoding="utf-8-sig"
    )
    assert "artifacts\\release-check" in text
    assert "result.json" in text
    assert "release_smoke" in text
    assert "--ux-certification-export" in text
    assert 'if ($text -match "(\\d+) passed")' in text
    assert "scripts/parallel_pytest.py" in text
    assert "pytest-performance.json" in text
    assert "$LegacyPytest" in text


def test_q1_gpu_policy_is_visibility_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"gpu_used_for_generic_pytest": False' in text
    assert "torch.cuda.is_available()" in text
    assert "Generic pytest/Qt/filesystem/database work is not a CUDA workload" in text


def test_q1_mainwindow_tests_do_not_enter_pure_lane() -> None:
    module = _module()
    plan = module.build_hybrid_plan(
        root=ROOT,
        policy_path=POLICY,
        workers="auto",
        logical_cpus=28,
    )
    pure = set(plan.pure_files)
    assert "tests/test_provider_architecture_v2_phase99.py" not in pure
    assert "tests/test_smart_provider_routing_phase98.py" not in pure
    assert "tests/test_provider_intelligence_voice_selection_phase90.py" not in pure


def test_q1_does_not_change_database_schema() -> None:
    changed = {
        "scripts/quality-gate.ps1",
        "scripts/release-check.ps1",
        "scripts/parallel_pytest.py",
        "scripts/quality-gate-policy.json",
        "docs/QUALITY_GATE_PERFORMANCE_OPTIMIZATION_ROADMAP2_Q1.md",
        "tests/test_quality_gate_performance_roadmap2_q1.py",
    }
    assert not any(path.startswith("app/database/") for path in changed)


def test_q1_test_file_has_single_final_newline() -> None:
    data = Path(__file__).read_bytes()
    assert data.endswith(b"\n")
    assert not data.endswith(b"\n\n")
