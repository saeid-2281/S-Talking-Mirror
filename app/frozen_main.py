from __future__ import annotations

import hashlib
import os
import re
import sys
import traceback
from pathlib import Path

import app
from app.config.runtime import RuntimeConfig


def _crash_log_path() -> Path:
    try:
        runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
        runtime.ensure_directories()
        return runtime.log_dir / "startup-crash.log"
    except Exception:
        executable = Path(sys.executable).resolve()
        fallback = executable.parent / "S-Talking-Data" / "logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "startup-crash.log"


def _runtime_diagnostics() -> str:
    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    return "\n".join(
        [
            f"app_version: {app.__version__}",
            f"executable: {sys.executable}",
            f"frozen: {getattr(sys, 'frozen', False)}",
            f"_MEIPASS: {getattr(sys, '_MEIPASS', '')}",
            f"app_root: {runtime.app_root}",
            f"bundled_root: {runtime.bundled_root}",
            f"data_dir: {runtime.data_dir}",
            f"settings_path: {runtime.settings_path}",
            f"log_dir: {runtime.log_dir}",
            f"reports_dir: {runtime.reports_dir}",
            f"artifacts_dir: {runtime.artifacts_dir}",
            f"QT_PLUGIN_PATH: {os.environ.get('QT_PLUGIN_PATH', '')}",
        ]
    )


_STARTUP_AUTHORIZATION_RE = re.compile(
    r"(?i)\bauthorization\b\s*[:=]\s*"
    r"(?:(?:bearer|basic|token)\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_STARTUP_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|cookie|credential)\b"
    r"\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_STARTUP_BEARER_RE = re.compile(
    r"(?i)\bbearer\s+(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_STARTUP_TOKEN_LIKE_RE = re.compile(r"\b(?:sk|xi|pk|rk)[-_][A-Za-z0-9_-]{16,}\b")
_STARTUP_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@")
_STARTUP_LONG_QUOTED_RE = re.compile(r"(['\"])(?:(?!\1).){64,}\1")
_STARTUP_MESSAGE_LIMIT = 600


def _safe_startup_exception_message(exc: BaseException) -> str:
    text = str(exc).replace("\r", " ").replace("\n", " ").strip()
    text = _STARTUP_LONG_QUOTED_RE.sub("[REDACTED-LONG-VALUE]", text)
    text = _STARTUP_AUTHORIZATION_RE.sub("Authorization=[REDACTED]", text)
    text = _STARTUP_SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]",
        text,
    )
    text = _STARTUP_BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _STARTUP_TOKEN_LIKE_RE.sub("[REDACTED-TOKEN]", text)
    text = _STARTUP_URL_CREDENTIAL_RE.sub(r"\1[REDACTED]@", text)
    if len(text) > _STARTUP_MESSAGE_LIMIT:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        text = f"{text[:240]} … [truncated; message-sha256={digest}]"
    return text or exc.__class__.__name__


def _write_crash(exc_type: type[BaseException], exc: BaseException, tb) -> None:
    path = _crash_log_path()
    frames = [
        f"{frame.filename}:{frame.lineno} in {frame.name}"
        for frame in traceback.extract_tb(tb)
    ]
    text = (
        "S Talking startup crash\n\n"
        + _runtime_diagnostics()
        + f"\n\nException type: {getattr(exc_type, '__name__', 'Exception')}"
        + f"\nException message: {_safe_startup_exception_message(exc)}"
        + "\nTraceback frames (source lines and local variables omitted):\n"
        + "\n".join(frames)
    )
    path.write_text(text, encoding="utf-8")


def excepthook(exc_type: type[BaseException], exc: BaseException, tb) -> None:
    try:
        _write_crash(exc_type, exc, tb)
    finally:
        sys.__excepthook__(exc_type, exc, tb)



def _handle_recovery_command(argv: list[str]) -> int | None:
    recovery_flags = {
        "--upgrade-snapshot",
        "--create-upgrade-backup",
        "--validate-upgrade-migration",
        "--verify-backup",
        "--restore-backup",
    }
    if not any(flag in argv for flag in recovery_flags):
        return None

    import argparse

    from app.database.connection import Database
    from app.services.upgrade_recovery_service import UpgradeRecoveryService

    parser = argparse.ArgumentParser(prog="S-Talking.exe", description="S Talking upgrade and recovery tool")
    parser.add_argument("--upgrade-snapshot", action="store_true")
    parser.add_argument("--create-upgrade-backup", action="store_true")
    parser.add_argument("--validate-upgrade-migration", action="store_true")
    parser.add_argument("--verify-backup", type=Path)
    parser.add_argument("--restore-backup", type=Path)
    parser.add_argument("--acknowledge-restore", action="store_true")
    parser.add_argument("--source-version", default="")
    parser.add_argument(
        "--upgrade-mode",
        choices=("auto", "in_place", "portable_to_installed", "installed_to_portable", "rollback"),
        default="auto",
    )
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    service = UpgradeRecoveryService(runtime, Database(runtime.database_path))
    snapshot = service.snapshot(
        source_version=args.source_version or None,
        mode=args.upgrade_mode,
        source_root=args.source_root,
    )
    print(f"Status:   {snapshot.status}")
    print(f"Versions: {snapshot.source_version} -> {snapshot.target_version}")
    print(f"Mode:     {snapshot.mode}")
    print(f"Schema:   {snapshot.current_schema}/{snapshot.target_schema}")
    for gate in snapshot.gates:
        if not gate.passed:
            print(f" - {gate.label} [{gate.severity}]: {gate.detail}")
    if snapshot.blocker_count and not (args.verify_backup or args.restore_backup):
        return 1
    if args.create_upgrade_backup:
        created = service.create_backup(
            source_version=args.source_version or None,
            mode=args.upgrade_mode,
            source_root=args.source_root,
        )
        print(f"Backup:   {created.backup_dir}")
    if args.validate_upgrade_migration:
        result = service.validate_migration(
            source_root=args.source_root,
            source_version=args.source_version or None,
        )
        print(f"Migration: {result.get('status')} — {result.get('detail')}")
        if result.get("status") != "ready":
            return 1
    if args.verify_backup:
        ok, detail = service.verify_backup(args.verify_backup)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        if not ok:
            return 1
    if args.restore_backup:
        result = service.restore_backup(
            args.restore_backup,
            dry_run=not args.acknowledge_restore,
            acknowledge=args.acknowledge_restore,
        )
        print(f"Restore: {result.get('status')} — {result.get('detail')}")
        if not args.acknowledge_restore:
            print("Dry run only. Re-run with --acknowledge-restore after closing the GUI.")
    return 0



def _handle_crash_recovery_command(argv: list[str]) -> int | None:
    flags = {
        "--crash-recovery-snapshot",
        "--export-crash-diagnostics",
        "--acknowledge-crash",
        "--verify-crash-bundle",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.crash_recovery_service import CrashRecoveryService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking crash recovery and privacy-safe diagnostics tool",
    )
    parser.add_argument("--crash-recovery-snapshot", action="store_true")
    parser.add_argument("--export-crash-diagnostics", action="store_true")
    parser.add_argument("--acknowledge-crash", default="")
    parser.add_argument("--verify-crash-bundle", type=Path)
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    service = CrashRecoveryService(runtime)
    if args.crash_recovery_snapshot:
        snapshot = service.snapshot()
        print(f"Status:       {snapshot.status}")
        print(f"Reports:      {snapshot.crash_count}")
        print(f"Unreviewed:   {snapshot.unacknowledged_count}")
        print(f"Integrity:    {snapshot.integrity_failure_count} failure(s)")
        print(f"Database:     {snapshot.database_status}")
        print(f"Safe command: {service.safe_mode_command()}")
    if args.acknowledge_crash:
        record = service.acknowledge(args.acknowledge_crash)
        print(f"Acknowledged: {record.report_id}")
    if args.export_crash_diagnostics:
        receipt = service.export_bundle()
        print(f"Bundle:       {receipt.path}")
        print(f"SHA-256:      {receipt.sha256}")
        print(f"Status:       {receipt.status}")
    if args.verify_crash_bundle:
        ok, detail = service.verify_bundle(args.verify_crash_bundle)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        if not ok:
            return 1
    return 0


def _handle_performance_command(argv: list[str]) -> int | None:
    flags = {
        "--performance-snapshot",
        "--performance-export",
        "--performance-soak-minutes",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.performance_stability_service import PerformanceStabilityService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking performance and long-run stability tool",
    )
    parser.add_argument("--performance-snapshot", action="store_true")
    parser.add_argument("--performance-export", action="store_true")
    parser.add_argument("--performance-soak-minutes", type=float, default=None)
    parser.add_argument("--performance-sample-interval", type=float, default=15.0)
    parser.add_argument("--performance-max-samples", type=int)
    parser.add_argument("--performance-label", default="command-line soak")
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    service = PerformanceStabilityService(runtime)
    service.mark_startup_ready()
    if args.performance_soak_minutes is not None:
        run = service.run_soak(
            duration_seconds=max(0.0, args.performance_soak_minutes * 60.0),
            sample_interval_seconds=args.performance_sample_interval,
            label=args.performance_label,
            max_samples=args.performance_max_samples,
        )
        print(f"Run:          {run.run_id}")
        print(f"Status:       {run.status}")
        print(f"Duration:     {run.duration_seconds:.1f} second(s)")
        print(f"Samples:      {run.sample_count}")
        print(f"Peak RSS:     {run.peak_rss_bytes / 1024**2:.1f} MB")
        print(f"RSS growth:   {run.rss_growth_bytes / 1024**2:+.1f} MB")
        print(f"Growth/hour:  {run.growth_mb_per_hour:.2f} MB/hour")
    if args.performance_snapshot or args.performance_soak_minutes is not None:
        snapshot = service.snapshot()
        print(f"Readiness:    {snapshot.status}")
        print(f"Startup:      {snapshot.current_sample.startup_elapsed_ms} ms")
        print(f"Working set:  {snapshot.current_sample.rss_bytes / 1024**2:.1f} MB")
        for gate in snapshot.gates:
            if gate.status in {"warn", "block"}:
                print(f" - {gate.label} [{gate.status}]: {gate.detail}")
        if snapshot.blocker_count:
            return 1
    if args.performance_export:
        json_path, csv_path = service.export_snapshot()
        print(f"JSON:         {json_path}")
        print(f"CSV:          {csv_path}")
    return 0



def _handle_security_command(argv: list[str]) -> int | None:
    flags = {
        "--security-snapshot",
        "--generate-sbom",
        "--security-audit-package",
        "--security-vulnerability-scan",
        "--security-export",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.secure_credentials import SecureCredentialStore
    from app.services.security_supply_chain_service import SecuritySupplyChainService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking security and supply-chain audit tool",
    )
    parser.add_argument("--security-snapshot", action="store_true")
    parser.add_argument("--generate-sbom", action="store_true")
    parser.add_argument("--security-audit-package", type=Path)
    parser.add_argument("--security-vulnerability-scan", action="store_true")
    parser.add_argument("--security-export", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    credential_store = SecureCredentialStore(runtime.settings_path.parent / "credentials")
    service = SecuritySupplyChainService(runtime, credential_store)
    package = args.security_audit_package
    if args.generate_sbom:
        path = service.generate_sbom()
        print(f"SBOM:         {path}")
        print(f"SHA-256:      {service._sha256(path)}")
    if args.security_vulnerability_scan:
        path = service.run_vulnerability_scan()
        print(f"Vulnerability:{path}")
    if package:
        receipt = service.audit_package(package)
        print(f"Package audit:{receipt.status}")
        print(f"Report:       {receipt.report_path}")
        print(f"Issues:       {receipt.issue_count}")
        if receipt.status != "verified":
            return 1
    if args.security_snapshot or args.generate_sbom or args.security_vulnerability_scan:
        snapshot = service.snapshot(package)
        print(f"Status:       {snapshot.status}")
        print(f"Credentials:  {snapshot.credential_backend}")
        print(f"Components:   {snapshot.component_count}")
        for gate in snapshot.gates:
            if gate.status in {"warn", "block"}:
                print(f" - {gate.label} [{gate.status}]: {gate.detail}")
        if snapshot.blocker_count:
            return 1
    if args.security_export:
        json_path, csv_path = service.export_snapshot(package)
        print(f"JSON:         {json_path}")
        print(f"CSV:          {csv_path}")
    return 0



def _handle_ux_certification_command(argv: list[str]) -> int | None:
    flags = {"--ux-certification", "--ux-certification-export"}
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.gui.theme import DARK_TOKENS, GRAPHITE_TOKENS, LIGHT_TOKENS
    from app.services.ux_accessibility_certification_service import (
        UxAccessibilityCertificationService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking UX, accessibility and theme certification tool",
    )
    parser.add_argument("--ux-certification", action="store_true")
    parser.add_argument("--ux-certification-export", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    service = UxAccessibilityCertificationService(runtime)
    snapshot = service.certification_snapshot(
        themes={"Dark": DARK_TOKENS, "Graphite": GRAPHITE_TOKENS, "Light": LIGHT_TOKENS},
        active_theme="certification-all-themes",
        preference_summary="High contrast · Text 110% · Enhanced focus · Reduced motion · Status announcements on",
        focus_regions=service.CORE_REGIONS,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Themes:       {len(service.REQUIRED_THEME_NAMES)}")
    print(f"Contrast:     {len(snapshot.contrast_results)} checks")
    print(f"Display:      {len(snapshot.display_profiles)} profiles")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")
    if args.ux_certification_export:
        json_path, csv_path = service.export_snapshot(snapshot)
        print(f"JSON:         {json_path}")
        print(f"CSV:          {csv_path}")
    return 1 if snapshot.blocker_count else 0


def _handle_production_certification_command(argv: list[str]) -> int | None:
    flags = {
        "--production-certification",
        "--production-certification-export",
        "--verify-production-attestation",
        "--prepare-production-promotion-plan",
        "--refresh-production-evidence",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.production_release_certification_service import (
        ProductionReleaseCertificationService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking production release certification and promotion guard",
    )
    parser.add_argument("--production-certification", action="store_true")
    parser.add_argument("--production-certification-export", action="store_true")
    parser.add_argument("--verify-production-attestation", type=Path)
    parser.add_argument("--prepare-production-promotion-plan", action="store_true")
    parser.add_argument("--refresh-production-evidence", action="store_true")
    parser.add_argument("--acknowledge-production-plan", action="store_true")
    parser.add_argument("--target-version", default="1.0.0")
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--expected-tests", type=int, default=850)
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    service = ProductionReleaseCertificationService(runtime)
    if args.verify_production_attestation:
        ok, detail = service.verify_attestation(args.verify_production_attestation)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    if args.refresh_production_evidence:
        for evidence_path in service.refresh_runtime_evidence():
            print(f"Refreshed:    {evidence_path}")

    snapshot = service.certify_and_write(
        target_version=args.target_version,
        source_commit=args.source_commit,
        expected_test_count=args.expected_tests,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Source:       {snapshot.source_version}")
    print(f"Target:       {snapshot.target_version}")
    print(f"Commit:       {snapshot.source_commit}")
    print(f"Tests:        {snapshot.observed_test_count}/{snapshot.expected_test_count}")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    print(f"Attestation:  {snapshot.attestation_path}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")
    if args.production_certification_export:
        attestation, summary = service.export_snapshot(snapshot)
        print(f"Evidence:     {attestation}")
        print(f"Summary:      {summary}")
    if args.prepare_production_promotion_plan:
        result = service.create_promotion_plan(
            snapshot,
            acknowledge=args.acknowledge_production_plan,
        )
        print(f"Plan:         {result.get('status')} — {result.get('detail')}")
        if result.get("path"):
            print(f"Plan path:    {result.get('path')}")
        if result.get("status") == "blocked":
            return 1
    return 1 if snapshot.blocker_count else 0



def _handle_stable_promotion_command(argv: list[str]) -> int | None:
    flags = {
        "--stable-promotion-snapshot",
        "--stable-promotion-verify-artifacts",
        "--prepare-stable-rollback",
        "--write-stable-promotion-receipt",
        "--verify-stable-promotion-receipt",
        "--verify-stable-rollback",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.production_release_certification_service import (
        ProductionReleaseCertificationService,
    )
    from app.services.stable_release_promotion_service import (
        StableReleasePromotionService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking stable release promotion, rollback and receipt verification",
    )
    parser.add_argument("--stable-promotion-snapshot", action="store_true")
    parser.add_argument("--stable-promotion-verify-artifacts", action="store_true")
    parser.add_argument("--prepare-stable-rollback", action="store_true")
    parser.add_argument("--write-stable-promotion-receipt", action="store_true")
    parser.add_argument("--verify-stable-promotion-receipt", type=Path)
    parser.add_argument("--verify-stable-rollback", type=Path)
    parser.add_argument("--acknowledge-stable-promotion", action="store_true")
    parser.add_argument("--production-attestation", type=Path)
    parser.add_argument("--rollback-manifest", type=Path)
    parser.add_argument("--stable-rollout", type=int, default=100)
    parser.add_argument("--require-stable-installer", action="store_true")
    parser.add_argument("--require-stable-signatures", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
    runtime.ensure_directories()
    production = ProductionReleaseCertificationService(runtime)
    service = StableReleasePromotionService(runtime, production)

    if args.verify_stable_promotion_receipt:
        ok, detail = service.verify_promotion_receipt(args.verify_stable_promotion_receipt)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_stable_rollback:
        ok, detail = service.verify_rollback_manifest(args.verify_stable_rollback)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    snapshot = service.snapshot(
        attestation_path=args.production_attestation,
        rollout_percentage=args.stable_rollout,
        include_artifact_gates=args.stable_promotion_verify_artifacts or args.write_stable_promotion_receipt,
        require_installer=args.require_stable_installer,
        require_signatures=args.require_stable_signatures,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Version:      {snapshot.version}")
    print(f"Channel:      {snapshot.channel}")
    print(f"Commit:       {snapshot.source_commit}")
    print(f"Attested:     {snapshot.attested_commit}")
    print(f"Rollout:      {snapshot.rollout_percentage}%")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    rollback_manifest = args.rollback_manifest
    if args.prepare_stable_rollback:
        result = service.create_rollback_point(
            snapshot,
            attestation_path=args.production_attestation,
            acknowledge=args.acknowledge_stable_promotion,
        )
        print(f"Rollback:     {result.get('status')} — {result.get('detail')}")
        if result.get("path"):
            rollback_manifest = Path(str(result["path"]))
            print(f"Rollback path:{rollback_manifest}")
        if result.get("status") == "blocked":
            return 1

    if args.write_stable_promotion_receipt:
        if rollback_manifest is None:
            print("Receipt:      blocked — --rollback-manifest is required.")
            return 1
        result = service.write_promotion_receipt(
            snapshot,
            rollback_manifest=rollback_manifest,
            attestation_path=args.production_attestation,
            acknowledge=args.acknowledge_stable_promotion,
            require_installer=args.require_stable_installer,
            require_signatures=args.require_stable_signatures,
        )
        print(f"Receipt:      {result.get('status')} — {result.get('detail')}")
        if result.get("path"):
            print(f"Receipt path: {result.get('path')}")
        return 0 if result.get("status") == "verified" else 1
    return 1 if snapshot.blocker_count else 0



def _handle_post_ga_maintenance_command(argv: list[str]) -> int | None:
    flags = {
        "--post-ga-maintenance-snapshot",
        "--write-post-ga-baseline",
        "--verify-post-ga-baseline",
        "--prepare-post-ga-maintenance-plan",
        "--verify-post-ga-maintenance-plan",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.post_ga_maintenance_service import PostGaMaintenanceService
    from app.services.production_release_certification_service import (
        ProductionReleaseCertificationService,
    )
    from app.services.stable_release_promotion_service import (
        StableReleasePromotionService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking post-GA reliability and maintenance evidence",
    )
    parser.add_argument("--post-ga-maintenance-snapshot", action="store_true")
    parser.add_argument("--write-post-ga-baseline", action="store_true")
    parser.add_argument("--verify-post-ga-baseline", type=Path)
    parser.add_argument("--prepare-post-ga-maintenance-plan", action="store_true")
    parser.add_argument("--verify-post-ga-maintenance-plan", type=Path)
    parser.add_argument("--promotion-receipt", type=Path)
    parser.add_argument("--stable-feed", type=Path)
    parser.add_argument("--rollback-manifest", type=Path)
    parser.add_argument("--post-ga-baseline", type=Path)
    parser.add_argument("--max-evidence-age-days", type=int, default=30)
    parser.add_argument("--minimum-free-space-mb", type=int, default=512)
    parser.add_argument("--expected-stable-rollout", type=int, default=100)
    parser.add_argument("--acknowledge-post-ga-maintenance", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    production = ProductionReleaseCertificationService(runtime)
    stable = StableReleasePromotionService(runtime, production)
    service = PostGaMaintenanceService(runtime, stable)

    if args.verify_post_ga_baseline:
        ok, detail = service.verify_baseline(args.verify_post_ga_baseline)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_post_ga_maintenance_plan:
        ok, detail = service.verify_maintenance_plan(
            args.verify_post_ga_maintenance_plan
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    snapshot = service.snapshot(
        promotion_receipt_path=args.promotion_receipt,
        stable_feed_path=args.stable_feed,
        rollback_manifest_path=args.rollback_manifest,
        max_evidence_age_days=args.max_evidence_age_days,
        minimum_free_space_mb=args.minimum_free_space_mb,
        expected_rollout_percentage=args.expected_stable_rollout,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Version:      {snapshot.version}")
    print(f"Channel:      {snapshot.channel}")
    print(f"Rollout:      {snapshot.rollout_percentage}%")
    print(f"Evidence age: {snapshot.evidence_age_days} day(s)")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    baseline_path = args.post_ga_baseline
    if args.write_post_ga_baseline:
        result = service.write_baseline(
            snapshot,
            acknowledge=args.acknowledge_post_ga_maintenance,
        )
        print(f"Baseline:     {result.get('status')} — {result.get('detail')}")
        if result.get("path"):
            baseline_path = Path(str(result["path"]))
            print(f"Baseline path:{baseline_path}")
        if result.get("status") != "verified":
            return 1

    if args.prepare_post_ga_maintenance_plan:
        baseline = baseline_path or service.default_baseline_path()
        result = service.prepare_maintenance_plan(
            snapshot,
            baseline_path=baseline,
            acknowledge=args.acknowledge_post_ga_maintenance,
        )
        print(f"Plan:         {result.get('status')} — {result.get('detail')}")
        if result.get("path"):
            print(f"Plan path:    {result.get('path')}")
        return 0 if result.get("status") == "prepared" else 1

    return 1 if snapshot.blocker_count else 0



def _handle_incident_support_command(argv: list[str]) -> int | None:
    flags = {
        "--incident-support-snapshot",
        "--create-incident-support-bundle",
        "--verify-incident-support-bundle",
        "--verify-incident-support-receipt",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.crash_recovery_service import CrashRecoveryService
    from app.services.incident_support_service import IncidentSupportService
    from app.services.post_ga_maintenance_service import PostGaMaintenanceService
    from app.services.production_release_certification_service import (
        ProductionReleaseCertificationService,
    )
    from app.services.stable_release_promotion_service import (
        StableReleasePromotionService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking production incident response and privacy-safe support bundle",
    )
    parser.add_argument("--incident-support-snapshot", action="store_true")
    parser.add_argument("--create-incident-support-bundle", action="store_true")
    parser.add_argument("--verify-incident-support-bundle", type=Path)
    parser.add_argument("--verify-incident-support-receipt", type=Path)
    parser.add_argument("--incident-summary", default="")
    parser.add_argument(
        "--incident-severity",
        choices=("low", "medium", "high", "critical"),
        default="medium",
    )
    parser.add_argument("--post-ga-baseline", type=Path)
    parser.add_argument("--exclude-support-logs", action="store_true")
    parser.add_argument("--max-support-log-age-days", type=int, default=14)
    parser.add_argument("--max-support-bundle-mb", type=int, default=16)
    parser.add_argument("--acknowledge-incident-support", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    crash = CrashRecoveryService(runtime)
    production = ProductionReleaseCertificationService(runtime)
    stable = StableReleasePromotionService(runtime, production)
    post_ga = PostGaMaintenanceService(runtime, stable)
    service = IncidentSupportService(runtime, crash, post_ga)

    if args.verify_incident_support_bundle:
        ok, detail = service.verify_bundle(args.verify_incident_support_bundle)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_incident_support_receipt:
        ok, detail = service.verify_receipt(args.verify_incident_support_receipt)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    snapshot = service.snapshot(
        summary=args.incident_summary,
        severity=args.incident_severity,
        baseline_path=args.post_ga_baseline,
        include_logs=not args.exclude_support_logs,
        max_log_age_days=args.max_support_log_age_days,
        max_bundle_mb=args.max_support_bundle_mb,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Incident:     {snapshot.incident_id}")
    print(f"Severity:     {snapshot.severity}")
    print(f"Version:      {snapshot.version}/{snapshot.channel}")
    print(f"Crash reports:{snapshot.crash_count}")
    print(f"Eligible logs:{snapshot.eligible_log_count}")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_incident_support_bundle:
        result = service.create_bundle(
            snapshot,
            baseline_path=args.post_ga_baseline,
            include_logs=not args.exclude_support_logs,
            max_log_age_days=args.max_support_log_age_days,
            acknowledge=args.acknowledge_incident_support,
        )
        if isinstance(result, dict):
            print(f"Bundle:       {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Bundle:       {result.path}")
        print(f"Receipt:      {result.receipt_path}")
        print(f"SHA-256:      {result.sha256}")
        return 0

    return 1 if snapshot.blocker_count else 0


def _handle_incident_triage_command(argv: list[str]) -> int | None:
    flags = {
        "--incident-triage-snapshot",
        "--create-incident-triage-case",
        "--verify-incident-triage-case",
        "--verify-incident-remediation-plan",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.crash_recovery_service import CrashRecoveryService
    from app.services.incident_support_service import IncidentSupportService
    from app.services.incident_triage_service import IncidentTriageService
    from app.services.post_ga_maintenance_service import PostGaMaintenanceService
    from app.services.production_release_certification_service import (
        ProductionReleaseCertificationService,
    )
    from app.services.stable_release_promotion_service import (
        StableReleasePromotionService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking verified support-bundle intake and incident triage",
    )
    parser.add_argument("--incident-triage-snapshot", action="store_true")
    parser.add_argument("--create-incident-triage-case", action="store_true")
    parser.add_argument("--verify-incident-triage-case", type=Path)
    parser.add_argument("--verify-incident-remediation-plan", type=Path)
    parser.add_argument("--incident-triage-bundle", type=Path)
    parser.add_argument("--incident-triage-receipt", type=Path)
    parser.add_argument("--acknowledge-incident-triage", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    crash = CrashRecoveryService(runtime)
    production = ProductionReleaseCertificationService(runtime)
    stable = StableReleasePromotionService(runtime, production)
    post_ga = PostGaMaintenanceService(runtime, stable)
    support = IncidentSupportService(runtime, crash, post_ga)
    service = IncidentTriageService(runtime, support)

    if args.verify_incident_triage_case:
        ok, detail = service.verify_case(args.verify_incident_triage_case)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_incident_remediation_plan:
        ok, detail = service.verify_plan(args.verify_incident_remediation_plan)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    bundle = args.incident_triage_bundle or service.default_bundle_path()
    snapshot = service.snapshot(
        bundle_path=bundle,
        receipt_path=args.incident_triage_receipt,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Case:         {snapshot.case_id}")
    print(f"Incident:     {snapshot.incident_id}")
    print(f"Priority:     {snapshot.priority}")
    print(f"Severity:     {snapshot.reported_severity} -> {snapshot.effective_severity}")
    print(f"Component:    {snapshot.component}")
    print(f"Evidence:     {snapshot.report_count} report(s), {snapshot.log_count} log(s)")
    print(f"Duplicates:   {snapshot.duplicate_count}")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_incident_triage_case:
        result = service.create_case(
            snapshot,
            acknowledge=args.acknowledge_incident_triage,
        )
        if isinstance(result, dict):
            print(f"Case:         {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Case path:    {result.case_path}")
        print(f"Plan path:    {result.plan_path}")
        print(f"Fingerprint:  {result.fingerprint}")
        return 0

    return 1 if snapshot.blocker_count else 0

def main() -> int:
    crash_service = None
    try:
        runtime_for_hardening = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
        from app.security_runtime import harden_windows_dll_search

        hardening_status, hardening_detail = harden_windows_dll_search(runtime_for_hardening)
        if hardening_status == "block":
            raise RuntimeError(hardening_detail)
        recovery_exit = _handle_recovery_command(sys.argv)
        if recovery_exit is not None:
            return recovery_exit
        crash_exit = _handle_crash_recovery_command(sys.argv)
        if crash_exit is not None:
            return crash_exit
        performance_exit = _handle_performance_command(sys.argv)
        if performance_exit is not None:
            return performance_exit
        security_exit = _handle_security_command(sys.argv)
        if security_exit is not None:
            return security_exit
        ux_exit = _handle_ux_certification_command(sys.argv)
        if ux_exit is not None:
            return ux_exit
        production_exit = _handle_production_certification_command(sys.argv)
        if production_exit is not None:
            return production_exit
        stable_promotion_exit = _handle_stable_promotion_command(sys.argv)
        if stable_promotion_exit is not None:
            return stable_promotion_exit
        post_ga_exit = _handle_post_ga_maintenance_command(sys.argv)
        if post_ga_exit is not None:
            return post_ga_exit
        incident_support_exit = _handle_incident_support_command(sys.argv)
        if incident_support_exit is not None:
            return incident_support_exit
        incident_triage_exit = _handle_incident_triage_command(sys.argv)
        if incident_triage_exit is not None:
            return incident_triage_exit

        from PySide6.QtWidgets import QApplication
        from app.bootstrap import create_application_context
        from app.container import create_service_container
        from app.gui.main import MainWindow
        from app.services.crash_recovery_service import CrashRecoveryService

        runtime = RuntimeConfig.from_frozen() if getattr(sys, "frozen", False) else RuntimeConfig.from_root()
        runtime.ensure_directories()
        crash_service = CrashRecoveryService(runtime)
        safe_mode = crash_service.safe_mode_requested(sys.argv)
        crash_service.begin_session(argv=sys.argv, safe_mode=safe_mode)
        crash_service.install_handlers()
        qt_argv = [argument for argument in sys.argv if argument != "--safe-mode"]
        qt_app = QApplication(qt_argv)
        crash_service.install_qt_message_handler()
        container = create_service_container(runtime, crash_recovery_service=crash_service)
        window = MainWindow(create_application_context(container))
        window.show()
        smoke_ms = int(os.environ.get("S_TALKING_SMOKE_EXIT_MS") or "0")
        if smoke_ms > 0:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(smoke_ms, window.close)
            QTimer.singleShot(smoke_ms + 250, qt_app.quit)
        return int(qt_app.exec())
    except Exception as exc:
        report_path = None
        if crash_service is not None:
            try:
                record = crash_service.capture_exception(
                    type(exc),
                    exc,
                    exc.__traceback__,
                    source="startup",
                    severity="fatal",
                )
                report_path = record.report_path if record else None
            except Exception:
                report_path = None
        if report_path is None:
            _write_crash(type(exc), exc, exc.__traceback__)
            report_path = _crash_log_path()
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox

            qt_app = QApplication.instance() or QApplication([])
            QMessageBox.critical(
                None,
                "S Talking could not start",
                "S Talking could not start.\n\n"
                f"Privacy-safe crash evidence was written to:\n{report_path}\n\n"
                "Start with --safe-mode to skip automatic project and update restoration.",
            )
            qt_app.quit()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
