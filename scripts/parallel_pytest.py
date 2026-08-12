from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "scripts" / "quality-gate-policy.json"
DEFAULT_REPORT = ROOT / "artifacts" / "quality-gate-performance" / "latest.json"


@dataclass(frozen=True)
class LanePlan:
    parallel_files: tuple[str, ...]
    serial_files: tuple[str, ...]
    workers: int
    logical_cpus: int


@dataclass(frozen=True)
class HybridPlan:
    pure_files: tuple[str, ...]
    ui_files: tuple[str, ...]
    stateful_serial_files: tuple[str, ...]
    hard_serial_files: tuple[str, ...]
    pure_workers: int
    ui_workers: int
    logical_cpus: int

    @property
    def serial_files(self) -> tuple[str, ...]:
        return self.stateful_serial_files + self.hard_serial_files


@dataclass(frozen=True)
class JunitSummary:
    tests: int
    passed: int
    skipped: int
    failures: int
    errors: int
    seconds: float
    slowest: tuple[tuple[float, str], ...]


@dataclass
class WorkerProcess:
    lane: str
    index: int
    process: subprocess.Popen
    log_path: Path
    junit_path: Path
    handle: object
    started: float
    files: tuple[str, ...]
    timeout_seconds: float
    finished: bool = False


def load_policy(path: Path = DEFAULT_POLICY) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported quality-gate policy schema.")
    if payload.get("unknown_test_file_lane") != "serial":
        raise ValueError("Unknown tests must default to the serial lane.")
    return payload


def discover_test_files(root: Path = ROOT) -> tuple[str, ...]:
    return tuple(
        path.relative_to(root).as_posix()
        for path in sorted((root / "tests").glob("test_*.py"))
    )


def resolve_worker_count(value: str, *, logical_cpus: int, policy: dict) -> int:
    logical = max(1, int(logical_cpus))
    requested = str(value).strip().lower()
    if requested == "all":
        return logical
    if requested not in {"", "auto"}:
        parsed = int(requested)
        if parsed < 1:
            raise ValueError("Worker count must be auto, all, or a positive integer.")
        return min(parsed, logical)
    fraction = float(policy.get("auto_worker_cpu_fraction", 0.50))
    cap = int(policy.get("auto_worker_cap", 6))
    if logical <= 2:
        return 1
    auto = max(2, int(logical * fraction))
    return max(1, min(logical, cap, auto))


def build_plan(
    *,
    root: Path = ROOT,
    policy_path: Path = DEFAULT_POLICY,
    workers: str = "auto",
    logical_cpus: int | None = None,
) -> LanePlan:
    policy = load_policy(policy_path)
    discovered = set(discover_test_files(root))
    allowed = tuple(str(item).replace("\\", "/") for item in policy["parallel_files"])
    parallel = tuple(path for path in allowed if path in discovered)
    parallel_set = set(parallel)
    serial = tuple(sorted(discovered - parallel_set))
    logical = int(logical_cpus or os.cpu_count() or 1)
    worker_count = resolve_worker_count(workers, logical_cpus=logical, policy=policy)
    worker_count = min(worker_count, max(1, len(parallel)))
    return LanePlan(
        parallel_files=parallel,
        serial_files=serial,
        workers=worker_count,
        logical_cpus=logical,
    )


def build_hybrid_plan(
    *,
    root: Path = ROOT,
    policy_path: Path = DEFAULT_POLICY,
    workers: str = "auto",
    logical_cpus: int | None = None,
) -> HybridPlan:
    policy = load_policy(policy_path)
    discovered = set(discover_test_files(root))

    pure_allowed = tuple(
        str(item).replace("\\", "/")
        for item in policy.get("parallel_files", [])
    )
    ui_allowed = tuple(
        str(item).replace("\\", "/")
        for item in policy.get("ui_parallel_files", [])
    )
    stateful_allowed = tuple(
        str(item).replace("\\", "/")
        for item in policy.get("stateful_serial_files", [])
    )

    pure = tuple(path for path in pure_allowed if path in discovered)
    pure_set = set(pure)

    ui = tuple(
        path
        for path in ui_allowed
        if path in discovered and path not in pure_set
    )
    ui_set = set(ui)

    stateful = tuple(
        path
        for path in stateful_allowed
        if path in discovered
        and path not in pure_set
        and path not in ui_set
    )
    stateful_set = set(stateful)

    hard_serial = tuple(
        sorted(discovered - pure_set - ui_set - stateful_set)
    )

    logical = int(logical_cpus or os.cpu_count() or 1)
    pure_workers = resolve_worker_count(
        workers,
        logical_cpus=logical,
        policy=policy,
    )
    pure_workers = min(pure_workers, max(1, len(pure)))
    ui_workers = min(
        max(1, int(policy.get("ui_worker_cap", 4))),
        logical,
        max(1, len(ui)),
    )

    return HybridPlan(
        pure_files=pure,
        ui_files=ui,
        stateful_serial_files=stateful,
        hard_serial_files=hard_serial,
        pure_workers=pure_workers,
        ui_workers=ui_workers,
        logical_cpus=logical,
    )


def estimate_file_weight(root: Path, relative_path: str) -> float:
    text = (root / relative_path).read_text(
        encoding="utf-8-sig",
        errors="ignore",
    )
    tests = text.count("def test_")
    parametrized = text.count("@pytest.mark.parametrize")
    return float(max(1, tests + (parametrized * 2)))


def _classname_to_file(classname: str) -> str | None:
    if not classname.startswith("tests."):
        return None
    module = classname.split("::", 1)[0]
    return module.replace(".", "/") + ".py"


def historical_file_weights(
    report_path: Path = DEFAULT_REPORT,
    *,
    scan_limit: int = 6,
) -> dict[str, float]:
    runs_root = report_path.parent / "runs"
    if not runs_root.is_dir():
        return {}

    run_dirs = sorted(
        (item for item in runs_root.iterdir() if item.is_dir()),
        key=lambda item: item.name,
        reverse=True,
    )[: max(1, int(scan_limit))]

    weights: dict[str, float] = {}

    for run_dir in run_dirs:
        per_run: dict[str, float] = {}
        for junit in sorted(run_dir.glob("*.xml")):
            try:
                root = ET.parse(junit).getroot()
            except Exception:
                continue

            for case in root.findall(".//testcase"):
                relative = _classname_to_file(case.attrib.get("classname", ""))
                if relative is None:
                    continue
                seconds = float(case.attrib.get("time", "0") or 0)
                per_run[relative] = per_run.get(relative, 0.0) + max(seconds, 0.001)

        for relative, seconds in per_run.items():
            if relative not in weights:
                weights[relative] = seconds

    return weights


def shard_files(
    root: Path,
    files: Iterable[str],
    workers: int,
    *,
    historical_weights: dict[str, float] | None = None,
) -> tuple[tuple[str, ...], ...]:
    worker_count = max(1, int(workers))
    buckets: list[list[str]] = [[] for _ in range(worker_count)]
    weights = [0.0 for _ in range(worker_count)]
    historical = historical_weights or {}

    ranked = []
    for path in files:
        weight = historical.get(path)
        if weight is None or weight <= 0:
            weight = estimate_file_weight(root, path)
        ranked.append((float(weight), path))

    ranked.sort(key=lambda item: (-item[0], item[1]))

    for weight, path in ranked:
        index = min(range(worker_count), key=lambda i: (weights[i], i))
        buckets[index].append(path)
        weights[index] += weight

    return tuple(tuple(bucket) for bucket in buckets if bucket)


def build_ui_tasks(
    files: Iterable[str],
    *,
    historical_weights: dict[str, float] | None = None,
) -> tuple[str, ...]:
    historical = historical_weights or {}
    return tuple(
        sorted(
            files,
            key=lambda path: (-float(historical.get(path, 0.0)), path),
        )
    )


def _write_qsettings_sitecustomize(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "sitecustomize.py"
    path.write_text(
        """from __future__ import annotations

import os
from pathlib import Path

root_text = os.environ.get("S_TALKING_QSETTINGS_ROOT", "").strip()

if root_text:
    from PySide6.QtCore import QSettings

    root = Path(root_text)
    root.mkdir(parents=True, exist_ok=True)

    fmt = getattr(QSettings, "IniFormat", None)
    if fmt is None:
        fmt = QSettings.Format.IniFormat

    user_scope = getattr(QSettings, "UserScope", None)
    if user_scope is None:
        user_scope = QSettings.Scope.UserScope

    system_scope = getattr(QSettings, "SystemScope", None)
    if system_scope is None:
        system_scope = QSettings.Scope.SystemScope

    QSettings.setDefaultFormat(fmt)
    QSettings.setPath(fmt, user_scope, str(root))
    QSettings.setPath(fmt, system_scope, str(root))
""",
        encoding="utf-8",
    )
    return path


def _gpu_info() -> dict:
    result = {
        "cuda_available": False,
        "device": "",
        "gpu_used_for_generic_pytest": False,
        "reason": (
            "Generic pytest/Qt/filesystem/database work is not a CUDA workload; "
            "GPU is reserved for explicit inference tests."
        ),
    }
    try:
        import torch  # type: ignore
        result["cuda_available"] = bool(torch.cuda.is_available())
        if result["cuda_available"]:
            result["device"] = str(torch.cuda.get_device_name(0))
    except Exception as exc:
        result["probe_error"] = f"{type(exc).__name__}: {exc}"
    return result


def _pytest_command(
    *,
    files: tuple[str, ...],
    basetemp: Path,
    junit: Path,
) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-o",
        "addopts=",
        f"--basetemp={basetemp}",
        f"--junitxml={junit}",
        *files,
    ]


def _tail(path: Path, lines: int = 100) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _parse_junit(paths: Iterable[Path]) -> JunitSummary:
    tests = skipped = failures = errors = 0
    test_seconds = 0.0
    slowest: list[tuple[float, str]] = []

    for path in paths:
        root = ET.parse(path).getroot()
        for case in root.findall(".//testcase"):
            tests += 1
            seconds = float(case.attrib.get("time", "0") or 0)
            test_seconds += seconds
            name = case.attrib.get("name", "unknown")
            classname = case.attrib.get("classname", "")
            slowest.append((seconds, f"{classname}::{name}".strip(":")))
            if case.find("skipped") is not None:
                skipped += 1
            elif case.find("failure") is not None:
                failures += 1
            elif case.find("error") is not None:
                errors += 1

    passed = tests - skipped - failures - errors
    slowest.sort(key=lambda item: (-item[0], item[1]))

    return JunitSummary(
        tests=tests,
        passed=passed,
        skipped=skipped,
        failures=failures,
        errors=errors,
        seconds=test_seconds,
        slowest=tuple(slowest[:25]),
    )


def _launch_worker(
    *,
    lane: str,
    index: int,
    root: Path,
    run_dir: Path,
    files: tuple[str, ...],
    env: dict[str, str],
    timeout_seconds: float,
) -> WorkerProcess:
    log = run_dir / f"{lane}-worker-{index}.txt"
    junit = run_dir / f"{lane}-worker-{index}.xml"
    basetemp = run_dir / f"pytest-tmp-{lane}-{index}"
    handle = log.open("w", encoding="utf-8")
    command = _pytest_command(files=files, basetemp=basetemp, junit=junit)

    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        command,
        cwd=root,
        env=env,
        stdout=handle,
        stderr=subprocess.STDOUT,
        text=True,
        creationflags=creationflags,
    )

    return WorkerProcess(
        lane=lane,
        index=index,
        process=process,
        log_path=log,
        junit_path=junit,
        handle=handle,
        started=time.monotonic(),
        files=files,
        timeout_seconds=timeout_seconds,
    )


def _close_worker_handle(worker: WorkerProcess) -> None:
    try:
        worker.handle.close()
    except Exception:
        pass


def _terminate_workers(workers: Iterable[WorkerProcess]) -> None:
    for worker in workers:
        if not worker.finished:
            _terminate_process_tree(worker.process)
        _close_worker_handle(worker)


def _run_pure_and_ui_pool(
    *,
    root: Path,
    run_dir: Path,
    plan: HybridPlan,
    historical: dict[str, float],
    base_env: dict[str, str],
    heartbeat_seconds: float,
    pure_timeout_seconds: float,
    ui_timeout_seconds: float,
) -> tuple[bool, list[Path], float]:
    pure_shards = shard_files(
        root,
        plan.pure_files,
        plan.pure_workers,
        historical_weights=historical,
    )

    ui_queue = list(
        build_ui_tasks(
            plan.ui_files,
            historical_weights=historical,
        )
    )

    bootstrap_dir = run_dir / "ui-worker-bootstrap"
    _write_qsettings_sitecustomize(bootstrap_dir)

    active: list[WorkerProcess] = []
    completed_junit: list[Path] = []

    for index, shard in enumerate(pure_shards, start=1):
        active.append(
            _launch_worker(
                lane="pure",
                index=index,
                root=root,
                run_dir=run_dir,
                files=shard,
                env=base_env.copy(),
                timeout_seconds=pure_timeout_seconds,
            )
        )

    next_ui_index = 1

    def launch_ui_task(relative_path: str, task_index: int) -> WorkerProcess:
        env = base_env.copy()
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(bootstrap_dir)
            if not existing_pythonpath
            else str(bootstrap_dir) + os.pathsep + existing_pythonpath
        )
        qsettings_root = run_dir / "ui-qsettings" / f"task-{task_index}"
        env["S_TALKING_QSETTINGS_ROOT"] = str(qsettings_root)
        env["S_TALKING_TEST_UI_ISOLATED"] = "1"

        return _launch_worker(
            lane="ui-file",
            index=task_index,
            root=root,
            run_dir=run_dir,
            files=(relative_path,),
            env=env,
            timeout_seconds=ui_timeout_seconds,
        )

    for _ in range(min(plan.ui_workers, len(ui_queue))):
        relative = ui_queue.pop(0)
        active.append(launch_ui_task(relative, next_ui_index))
        next_ui_index += 1

    started = time.perf_counter()
    last_heartbeat = time.monotonic()
    failed = False

    try:
        while active:
            now = time.monotonic()

            for worker in list(active):
                code = worker.process.poll()
                elapsed = now - worker.started

                if code is None and elapsed > worker.timeout_seconds:
                    relative = (
                        worker.files[0]
                        if len(worker.files) == 1
                        else f"{len(worker.files)} files"
                    )
                    print(
                        f"  {worker.lane} worker {worker.index}: "
                        f"TIMEOUT after {elapsed:.1f}s [{relative}]",
                        flush=True,
                    )
                    _terminate_process_tree(worker.process)
                    _close_worker_handle(worker)
                    worker.finished = True
                    active.remove(worker)
                    failed = True
                    tail = _tail(worker.log_path)
                    if tail:
                        print(tail, flush=True)
                    break

                if code is not None:
                    _close_worker_handle(worker)
                    worker.finished = True
                    active.remove(worker)
                    elapsed = time.monotonic() - worker.started

                    if worker.junit_path.is_file():
                        completed_junit.append(worker.junit_path)

                    relative = (
                        worker.files[0]
                        if len(worker.files) == 1
                        else f"{len(worker.files)} files"
                    )

                    if code == 0:
                        print(
                            f"  {worker.lane} worker {worker.index}: "
                            f"PASSED in {elapsed:.1f}s [{relative}]",
                            flush=True,
                        )
                    else:
                        print(
                            f"  {worker.lane} worker {worker.index}: "
                            f"FAILED (exit {code}) in {elapsed:.1f}s [{relative}]",
                            flush=True,
                        )
                        failed = True
                        tail = _tail(worker.log_path)
                        if tail:
                            print(tail, flush=True)
                        break

                    if worker.lane == "ui-file" and ui_queue:
                        next_relative = ui_queue.pop(0)
                        active.append(launch_ui_task(next_relative, next_ui_index))
                        next_ui_index += 1

            if failed:
                print(
                    "Parallel/UI lane failure detected; terminating remaining worker process trees.",
                    flush=True,
                )
                _terminate_workers(active)
                active.clear()
                break

            if not active:
                break

            if now - last_heartbeat >= heartbeat_seconds:
                pure_active = sum(worker.lane == "pure" for worker in active)
                ui_active = sum(worker.lane == "ui-file" for worker in active)
                print(
                    f"  heartbeat: pure={pure_active} | "
                    f"ui-files={ui_active} | ui-queued={len(ui_queue)}",
                    flush=True,
                )
                last_heartbeat = now

            time.sleep(0.25)

    except KeyboardInterrupt:
        print(
            "Hybrid pytest interrupted; "
            "terminating worker process trees...",
            flush=True,
        )
        _terminate_workers(active)
        raise

    return failed, completed_junit, time.perf_counter() - started


def _run_serial_lane(
    *,
    root: Path,
    run_dir: Path,
    files: tuple[str, ...],
    env: dict[str, str],
    heartbeat_seconds: float,
) -> tuple[bool, Path | None, float]:
    if not files:
        return False, None, 0.0

    log = run_dir / "serial-sensitive.txt"
    junit = run_dir / "serial-sensitive.xml"
    command = _pytest_command(
        files=files,
        basetemp=run_dir / "pytest-tmp-serial-sensitive",
        junit=junit,
    )

    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    print(f"==> serial-sensitive lane ({len(files)} files)", flush=True)

    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creationflags,
        )
        started = time.monotonic()
        last_heartbeat = started

        try:
            while process.poll() is None:
                now = time.monotonic()
                if now - last_heartbeat >= heartbeat_seconds:
                    print(
                        f"  serial heartbeat: {now - started:.0f}s",
                        flush=True,
                    )
                    last_heartbeat = now
                time.sleep(0.5)
        except KeyboardInterrupt:
            print(
                "Serial pytest interrupted; terminating process tree...",
                flush=True,
            )
            _terminate_process_tree(process)
            raise

    elapsed = time.monotonic() - started

    if process.returncode != 0:
        print(
            f"  serial-sensitive lane: FAILED (exit {process.returncode})",
            flush=True,
        )
        tail = _tail(log)
        if tail:
            print(tail, flush=True)
        return True, junit if junit.is_file() else None, elapsed

    print(f"  serial-sensitive lane: PASSED in {elapsed:.1f}s", flush=True)
    return False, junit if junit.is_file() else None, elapsed


def run_parallel_pytest(
    *,
    root: Path = ROOT,
    policy_path: Path = DEFAULT_POLICY,
    report_path: Path = DEFAULT_REPORT,
    workers: str = "auto",
) -> int:
    started = time.perf_counter()
    policy = load_policy(policy_path)
    plan = build_hybrid_plan(
        root=root,
        policy_path=policy_path,
        workers=workers,
    )

    historical = (
        historical_file_weights(
            report_path,
            scan_limit=int(policy.get("historical_run_scan_limit", 6)),
        )
        if policy.get("use_historical_junit_weights", True)
        else {}
    )

    heartbeat_seconds = float(policy.get("heartbeat_seconds", 20))
    pure_timeout_seconds = float(policy.get("parallel_worker_timeout_seconds", 1200))
    ui_timeout_seconds = float(policy.get("ui_task_timeout_seconds", 600))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = report_path.parent / "runs" / stamp
    run_dir.mkdir(parents=True, exist_ok=True)

    print(
        "Isolated hybrid pytest plan: "
        f"{len(plan.pure_files)} pure files / "
        f"{len(plan.ui_files)} isolated UI files / "
        f"{len(plan.stateful_serial_files)} stateful serial files / "
        f"{len(plan.hard_serial_files)} hard-serial files",
        flush=True,
    )
    print(
        f"CPU: {plan.logical_cpus} logical processors | "
        f"pure workers={plan.pure_workers} | UI slots={plan.ui_workers}",
        flush=True,
    )
    print(
        f"UI execution: one test file per fresh process | "
        f"QSettings scope: isolated | UI task timeout={ui_timeout_seconds:.0f}s",
        flush=True,
    )
    print(
        f"Historical timing weights: {'loaded' if historical else 'not available'} | "
        f"heartbeat={heartbeat_seconds:.0f}s",
        flush=True,
    )

    gpu = _gpu_info()
    gpu_label = gpu["device"] if gpu["cuda_available"] else "not available"
    print(
        f"GPU/CUDA: {gpu_label} | generic pytest GPU acceleration: disabled",
        flush=True,
    )

    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONHASHSEED"] = "0"
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    parallel_failed, junit_paths, parallel_elapsed = _run_pure_and_ui_pool(
        root=root,
        run_dir=run_dir,
        plan=plan,
        historical=historical,
        base_env=env,
        heartbeat_seconds=heartbeat_seconds,
        pure_timeout_seconds=pure_timeout_seconds,
        ui_timeout_seconds=ui_timeout_seconds,
    )

    serial_elapsed = 0.0

    if not parallel_failed:
        serial_failed, serial_junit, serial_elapsed = _run_serial_lane(
            root=root,
            run_dir=run_dir,
            files=plan.serial_files,
            env=env,
            heartbeat_seconds=heartbeat_seconds,
        )
        if serial_junit is not None:
            junit_paths.append(serial_junit)
    else:
        serial_failed = False

    failed = parallel_failed or serial_failed
    elapsed = time.perf_counter() - started

    summary = (
        _parse_junit(junit_paths)
        if junit_paths
        else JunitSummary(
            tests=0,
            passed=0,
            skipped=0,
            failures=0,
            errors=0,
            seconds=0.0,
            slowest=(),
        )
    )

    payload = {
        "schema_version": 4,
        "success": not failed and summary.failures == 0 and summary.errors == 0,
        "elapsed_seconds": round(elapsed, 3),
        "parallel_overlap_seconds": round(parallel_elapsed, 3),
        "serial_sensitive_seconds": round(serial_elapsed, 3),
        "logical_cpus": plan.logical_cpus,
        "workers": plan.pure_workers + plan.ui_workers,
        "pure_workers": plan.pure_workers,
        "ui_workers": plan.ui_workers,
        "worker_request": workers,
        "pure_file_count": len(plan.pure_files),
        "ui_file_count": len(plan.ui_files),
        "stateful_serial_file_count": len(plan.stateful_serial_files),
        "hard_serial_file_count": len(plan.hard_serial_files),
        "serial_file_count": len(plan.serial_files),
        "ui_one_file_per_process": True,
        "ui_qsettings_isolated": True,
        "historical_weights_loaded": bool(historical),
        "tests": summary.tests,
        "passed": summary.passed,
        "skipped": summary.skipped,
        "failures": summary.failures,
        "errors": summary.errors,
        "aggregate_test_seconds": round(summary.seconds, 3),
        "gpu": gpu,
        "slowest": [
            {"seconds": round(seconds, 6), "node": node}
            for seconds, node in summary.slowest
        ],
        "run_directory": str(run_dir),
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if failed or summary.failures or summary.errors:
        print(
            f"Isolated hybrid pytest failed: {summary.passed} passed, "
            f"{summary.failures} failed, {summary.errors} errors, "
            f"{summary.skipped} skipped",
            flush=True,
        )
        print(f"Performance report: {report_path}", flush=True)
        return 1

    print("")
    print(
        f"================ {summary.passed} passed, {summary.skipped} skipped "
        f"in {elapsed:.2f}s "
        f"(pure={plan.pure_workers}, ui-slots={plan.ui_workers}) ================",
        flush=True,
    )
    print(
        f"Parallel/UI phase: {parallel_elapsed:.2f}s | "
        f"serial-sensitive phase: {serial_elapsed:.2f}s",
        flush=True,
    )
    print(f"Performance report: {report_path}", flush=True)

    if summary.slowest:
        print("Slowest tests:", flush=True)
        for seconds, node in summary.slowest[:10]:
            print(f"  {seconds:8.3f}s  {node}", flush=True)

    return 0


def _print_plan(plan: HybridPlan) -> None:
    print(
        json.dumps(
            {
                "logical_cpus": plan.logical_cpus,
                "pure_workers": plan.pure_workers,
                "ui_workers": plan.ui_workers,
                "pure_file_count": len(plan.pure_files),
                "ui_file_count": len(plan.ui_files),
                "stateful_serial_file_count": len(plan.stateful_serial_files),
                "hard_serial_file_count": len(plan.hard_serial_files),
                "serial_file_count": len(plan.serial_files),
                "pure_files": list(plan.pure_files),
                "ui_files": list(plan.ui_files),
                "stateful_serial_files": list(plan.stateful_serial_files),
                "hard_serial_files": list(plan.hard_serial_files),
            },
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Isolated hybrid monitored pytest orchestrator."
    )
    parser.add_argument(
        "--workers",
        default="auto",
        help="auto, all, or a positive integer for the pure lane",
    )
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)

    plan = build_hybrid_plan(
        policy_path=args.policy,
        workers=args.workers,
    )

    if args.plan_only:
        _print_plan(plan)
        return 0

    return run_parallel_pytest(
        policy_path=args.policy,
        report_path=args.report,
        workers=args.workers,
    )


if __name__ == "__main__":
    raise SystemExit(main())
