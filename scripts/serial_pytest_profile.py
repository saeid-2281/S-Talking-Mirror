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
DEFAULT_REPORT = (
    ROOT
    / "artifacts"
    / "quality-gate-performance"
    / "serial-latest.json"
)


@dataclass(frozen=True)
class JunitSummary:
    tests: int
    passed: int
    skipped: int
    failures: int
    errors: int
    aggregate_test_seconds: float
    slowest: tuple[tuple[float, str], ...]


def _terminate_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return

    if os.name == "nt":
        subprocess.run(
            [
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def parse_junit(paths: Iterable[Path]) -> JunitSummary:
    tests = 0
    skipped = 0
    failures = 0
    errors = 0
    aggregate = 0.0
    slowest: list[tuple[float, str]] = []

    for path in paths:
        root = ET.parse(path).getroot()

        for case in root.findall(".//testcase"):
            tests += 1
            seconds = float(case.attrib.get("time", "0") or 0)
            aggregate += seconds

            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "unknown")
            slowest.append(
                (
                    seconds,
                    f"{classname}::{name}".strip(":"),
                )
            )

            if case.find("skipped") is not None:
                skipped += 1
            elif case.find("failure") is not None:
                failures += 1
            elif case.find("error") is not None:
                errors += 1

    passed = tests - skipped - failures - errors
    slowest.sort(
        key=lambda item: (
            -item[0],
            item[1],
        )
    )

    return JunitSummary(
        tests=tests,
        passed=passed,
        skipped=skipped,
        failures=failures,
        errors=errors,
        aggregate_test_seconds=aggregate,
        slowest=tuple(slowest[:25]),
    )


def _default_run_dir(report_path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return report_path.parent / "serial-runs" / stamp


def run_serial_profiled_pytest(
    *,
    root: Path = ROOT,
    report_path: Path = DEFAULT_REPORT,
) -> int:
    started_wall = time.perf_counter()
    started_at = datetime.now(timezone.utc)

    run_dir = _default_run_dir(report_path)
    run_dir.mkdir(parents=True, exist_ok=True)

    junit_path = run_dir / "pytest.xml"

    command = [
        sys.executable,
        "-m",
        "pytest",
        "--junitxml",
        str(junit_path),
        "--durations=25",
        "--durations-min=0.5",
    ]

    print(
        "Serial profiled pytest: stable default full-suite lane",
        flush=True,
    )
    print(
        f"JUnit evidence: {junit_path}",
        flush=True,
    )

    creationflags = 0
    if (
        os.name == "nt"
        and hasattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
        )
    ):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    test_env = os.environ.copy()
    test_env.setdefault("S_TALKING_TEST_FAST_PATH", "1")

    process = subprocess.Popen(
        command,
        cwd=root,
        env=test_env,
        creationflags=creationflags,
    )

    try:
        return_code = process.wait()
    except KeyboardInterrupt:
        print(
            "Serial profiled pytest interrupted; "
            "terminating pytest process tree...",
            flush=True,
        )
        _terminate_process_tree(process)
        raise

    elapsed = time.perf_counter() - started_wall
    finished_at = datetime.now(timezone.utc)

    if junit_path.is_file():
        summary = parse_junit([junit_path])
    else:
        summary = JunitSummary(
            tests=0,
            passed=0,
            skipped=0,
            failures=0,
            errors=1 if return_code else 0,
            aggregate_test_seconds=0.0,
            slowest=(),
        )

    payload = {
        "schema_version": 1,
        "mode": "serial_profiled",
        "success": (
            return_code == 0
            and summary.failures == 0
            and summary.errors == 0
        ),
        "exit_code": return_code,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_seconds": round(elapsed, 3),
        "tests": summary.tests,
        "passed": summary.passed,
        "skipped": summary.skipped,
        "failures": summary.failures,
        "errors": summary.errors,
        "aggregate_test_seconds": round(
            summary.aggregate_test_seconds,
            3,
        ),
        "slowest": [
            {
                "seconds": round(seconds, 6),
                "node": node,
            }
            for seconds, node in summary.slowest
        ],
        "run_directory": str(run_dir),
        "junit_path": str(junit_path),
        "parallelism": "disabled_by_default",
        "test_fast_path": test_env.get("S_TALKING_TEST_FAST_PATH") == "1",
        "experimental_parallel_runner": "scripts/parallel_pytest.py",
    }

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    report_path.write_text(
        json.dumps(
            payload,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("")
    print(
        "SERIAL_PROFILE_SUMMARY: "
        f"{summary.passed} passed, "
        f"{summary.skipped} skipped, "
        f"{summary.failures} failed, "
        f"{summary.errors} errors "
        f"in {elapsed:.2f}s",
        flush=True,
    )
    print(
        f"Performance report: {report_path}",
        flush=True,
    )

    if summary.slowest:
        print(
            "Slowest tests from JUnit evidence:",
            flush=True,
        )
        for seconds, node in summary.slowest[:10]:
            print(
                f"  {seconds:8.3f}s  {node}",
                flush=True,
            )

    return 0 if payload["success"] else (return_code or 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the full pytest suite serially while preserving "
            "machine-readable timing evidence."
        )
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
    )

    args = parser.parse_args(argv)

    return run_serial_profiled_pytest(
        report_path=args.report,
    )


if __name__ == "__main__":
    raise SystemExit(main())
