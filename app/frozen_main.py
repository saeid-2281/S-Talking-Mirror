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


def _handle_incident_resolution_command(argv: list[str]) -> int | None:
    flags = {
        "--incident-resolution-snapshot",
        "--create-incident-resolution",
        "--verify-incident-resolution",
        "--verify-incident-closure",
        "--verify-incident-knowledge",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.incident_resolution_service import IncidentResolutionService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking verified incident resolution and human-controlled closure",
    )
    parser.add_argument("--incident-resolution-snapshot", action="store_true")
    parser.add_argument("--create-incident-resolution", action="store_true")
    parser.add_argument("--verify-incident-resolution", type=Path)
    parser.add_argument("--verify-incident-closure", type=Path)
    parser.add_argument("--verify-incident-knowledge", type=Path)
    parser.add_argument("--incident-resolution-case", type=Path)
    parser.add_argument("--incident-resolution-plan", type=Path)
    parser.add_argument("--incident-resolution-summary", default="")
    parser.add_argument("--incident-customer-impact", default="")
    parser.add_argument(
        "--incident-resolution-type",
        default="code_fix",
        choices=sorted(IncidentResolutionService.RESOLUTION_TYPES),
    )
    parser.add_argument(
        "--incident-resolution-evidence",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--acknowledge-incident-resolution", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    service = IncidentResolutionService(runtime)

    if args.verify_incident_resolution:
        ok, detail = service.verify_resolution(args.verify_incident_resolution)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_incident_closure:
        ok, detail = service.verify_closure(args.verify_incident_closure)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_incident_knowledge:
        ok, detail = service.verify_knowledge(args.verify_incident_knowledge)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    case_path = args.incident_resolution_case or service.default_case_path()
    plan_path = args.incident_resolution_plan or service.default_plan_path(case_path)
    snapshot = service.snapshot(
        case_path=case_path,
        plan_path=plan_path,
        resolution_summary=args.incident_resolution_summary,
        customer_impact=args.incident_customer_impact,
        resolution_type=args.incident_resolution_type,
        evidence_paths=args.incident_resolution_evidence,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Resolution:   {snapshot.resolution_id}")
    print(f"Case:         {snapshot.case_id}")
    print(f"Priority:     {snapshot.priority}")
    print(f"Component:    {snapshot.component}")
    print(f"Type:         {snapshot.resolution_type}")
    print(f"Evidence:     {len(snapshot.evidence)} verified record(s)")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_incident_resolution:
        result = service.create_closure(
            snapshot,
            acknowledge=args.acknowledge_incident_resolution,
        )
        if isinstance(result, dict):
            print(f"Closure:      {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Resolution:   {result.resolution_path}")
        print(f"Closure:      {result.closure_path}")
        print(f"Knowledge:    {result.knowledge_path}")
        return 0

    return 1 if snapshot.blocker_count else 0


def _handle_incident_prevention_command(argv: list[str]) -> int | None:
    flags = {
        "--incident-prevention-snapshot",
        "--create-incident-prevention-baseline",
        "--verify-incident-prevention-baseline",
        "--verify-preventive-action-register",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.incident_prevention_service import IncidentPreventionService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking verified recurrence analysis and preventive actions",
    )
    parser.add_argument("--incident-prevention-snapshot", action="store_true")
    parser.add_argument("--create-incident-prevention-baseline", action="store_true")
    parser.add_argument("--verify-incident-prevention-baseline", type=Path)
    parser.add_argument("--verify-preventive-action-register", type=Path)
    parser.add_argument(
        "--incident-prevention-closure",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--incident-prevention-lookback-days",
        type=int,
        default=IncidentPreventionService.DEFAULT_LOOKBACK_DAYS,
    )
    parser.add_argument(
        "--incident-prevention-recurrence-threshold",
        type=int,
        default=IncidentPreventionService.DEFAULT_RECURRENCE_THRESHOLD,
    )
    parser.add_argument(
        "--incident-prevention-high-risk-threshold",
        type=int,
        default=IncidentPreventionService.DEFAULT_HIGH_RISK_THRESHOLD,
    )
    parser.add_argument("--acknowledge-incident-prevention", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    service = IncidentPreventionService(runtime)

    if args.verify_incident_prevention_baseline:
        ok, detail = service.verify_baseline(args.verify_incident_prevention_baseline)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_preventive_action_register:
        ok, detail = service.verify_register(args.verify_preventive_action_register)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    snapshot = service.snapshot(
        closure_paths=args.incident_prevention_closure,
        lookback_days=args.incident_prevention_lookback_days,
        recurrence_threshold=args.incident_prevention_recurrence_threshold,
        high_risk_threshold=args.incident_prevention_high_risk_threshold,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Closures:     {snapshot.verified_count}/{snapshot.selected_count} verified")
    print(f"Patterns:     {len(snapshot.patterns)}")
    print(f"Recurring:    {snapshot.recurring_pattern_count}")
    print(f"High risk:    {snapshot.high_risk_pattern_count}")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_incident_prevention_baseline:
        result = service.create_baseline(
            snapshot,
            acknowledge=args.acknowledge_incident_prevention,
        )
        if isinstance(result, dict):
            print(f"Baseline:     {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Baseline:     {result.baseline_path}")
        print(f"Register:     {result.register_path}")
        return 0

    path = service.export_snapshot(snapshot)
    print(f"Snapshot:     {path}")
    return 1 if snapshot.blocker_count else 0


def _handle_prevention_effectiveness_command(argv: list[str]) -> int | None:
    flags = {
        "--prevention-effectiveness-snapshot",
        "--create-prevention-effectiveness-review",
        "--record-preventive-action-attestation",
        "--verify-preventive-action-attestation",
        "--verify-prevention-effectiveness-review",
        "--verify-prevention-effectiveness-decision",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.prevention_effectiveness_service import (
        PreventionEffectivenessService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking preventive action effectiveness and residual-risk review",
    )
    parser.add_argument("--prevention-effectiveness-snapshot", action="store_true")
    parser.add_argument("--create-prevention-effectiveness-review", action="store_true")
    parser.add_argument("--record-preventive-action-attestation", action="store_true")
    parser.add_argument("--verify-preventive-action-attestation", type=Path)
    parser.add_argument("--verify-prevention-effectiveness-review", type=Path)
    parser.add_argument("--verify-prevention-effectiveness-decision", type=Path)
    parser.add_argument("--prevention-baseline", type=Path)
    parser.add_argument("--preventive-action-register", type=Path)
    parser.add_argument(
        "--prevention-effectiveness-closure",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--prevention-observation-days",
        type=int,
        default=PreventionEffectivenessService.DEFAULT_OBSERVATION_DAYS,
    )
    parser.add_argument("--preventive-action-code", default="")
    parser.add_argument(
        "--preventive-action-status",
        choices=PreventionEffectivenessService.ACTION_STATUSES,
        default="completed",
    )
    parser.add_argument("--preventive-action-owner", default="")
    parser.add_argument("--preventive-action-evidence", default="")
    parser.add_argument("--preventive-action-reference", default="")
    parser.add_argument(
        "--prevention-review-decision",
        choices=PreventionEffectivenessService.REVIEW_DECISIONS,
        default="continue_monitoring",
    )
    parser.add_argument("--prevention-review-rationale", default="")
    parser.add_argument("--acknowledge-prevention-effectiveness", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    service = PreventionEffectivenessService(runtime)

    if args.verify_preventive_action_attestation:
        ok, detail = service.verify_attestation(args.verify_preventive_action_attestation)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_prevention_effectiveness_review:
        ok, detail = service.verify_review(args.verify_prevention_effectiveness_review)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_prevention_effectiveness_decision:
        ok, detail = service.verify_decision(args.verify_prevention_effectiveness_decision)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    baseline_path = args.prevention_baseline or service.default_baseline_path()
    register_path = args.preventive_action_register or service.default_register_path(
        baseline_path
    )

    if args.record_preventive_action_attestation:
        result = service.create_action_attestation(
            baseline_path=baseline_path,
            register_path=register_path,
            action_code=args.preventive_action_code,
            status=args.preventive_action_status,
            owner=args.preventive_action_owner,
            evidence_summary=args.preventive_action_evidence,
            evidence_reference=args.preventive_action_reference,
            acknowledge=args.acknowledge_prevention_effectiveness,
        )
        if isinstance(result, dict):
            print(f"Attestation:  {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Attestation:  {result}")
        return 0

    snapshot = service.snapshot(
        baseline_path=baseline_path,
        register_path=register_path,
        closure_paths=args.prevention_effectiveness_closure,
        observation_days=args.prevention_observation_days,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Actions:      {snapshot.completed_action_count} completed / {len(snapshot.actions)}")
    print(f"Overdue:      {snapshot.overdue_action_count}")
    print(f"Recurrence:   {snapshot.recurrent_pattern_count}")
    print(f"Ineffective:  {snapshot.ineffective_pattern_count}")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_prevention_effectiveness_review:
        result = service.create_review(
            snapshot,
            decision=args.prevention_review_decision,
            rationale=args.prevention_review_rationale,
            acknowledge=args.acknowledge_prevention_effectiveness,
        )
        if isinstance(result, dict):
            print(f"Review:       {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Review:       {result.review_path}")
        print(f"Decision:     {result.decision_path}")
        return 0

    path = service.export_snapshot(snapshot)
    print(f"Snapshot:     {path}")
    return 1 if snapshot.blocker_count else 0


def _handle_reliability_assurance_command(argv: list[str]) -> int | None:
    flags = {
        "--reliability-assurance-snapshot",
        "--create-reliability-assurance",
        "--verify-reliability-assurance-attestation",
        "--verify-reliability-assurance-pack",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.reliability_assurance_service import ReliabilityAssuranceService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking reliability assurance, exception governance and audit pack",
    )
    parser.add_argument("--reliability-assurance-snapshot", action="store_true")
    parser.add_argument("--create-reliability-assurance", action="store_true")
    parser.add_argument("--verify-reliability-assurance-attestation", type=Path)
    parser.add_argument("--verify-reliability-assurance-pack", type=Path)
    parser.add_argument("--reliability-assurance-receipt", type=Path)
    parser.add_argument(
        "--reliability-assurance-review",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--reliability-assurance-decision",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--reliability-assurance-window-days",
        type=int,
        default=ReliabilityAssuranceService.DEFAULT_ASSURANCE_WINDOW_DAYS,
    )
    parser.add_argument(
        "--reliability-assurance-outcome",
        choices=ReliabilityAssuranceService.ASSURANCE_DECISIONS,
        default="assure",
    )
    parser.add_argument("--reliability-assurance-owner", default="")
    parser.add_argument("--reliability-assurance-statement", default="")
    parser.add_argument("--reliability-assurance-exception-owner", default="")
    parser.add_argument("--reliability-assurance-next-review", default="")
    parser.add_argument("--acknowledge-reliability-assurance", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    service = ReliabilityAssuranceService(runtime)

    if args.verify_reliability_assurance_attestation:
        ok, detail = service.verify_attestation(
            args.verify_reliability_assurance_attestation
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_reliability_assurance_pack:
        if args.reliability_assurance_receipt is None:
            print("Verification: failed — an audit-pack receipt is required.")
            return 1
        ok, detail = service.verify_audit_pack(
            args.verify_reliability_assurance_pack,
            args.reliability_assurance_receipt,
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    snapshot = service.snapshot(
        review_paths=args.reliability_assurance_review,
        decision_paths=args.reliability_assurance_decision,
        assurance_window_days=args.reliability_assurance_window_days,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Pairs:        {snapshot.verified_pair_count}")
    print(f"Exceptions:   {snapshot.open_exception_count}")
    print(f"High/Critical:{snapshot.high_exception_count}")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_reliability_assurance:
        result = service.create_assurance(
            snapshot,
            decision=args.reliability_assurance_outcome,
            owner=args.reliability_assurance_owner,
            statement=args.reliability_assurance_statement,
            exception_owner=args.reliability_assurance_exception_owner,
            next_review_date=args.reliability_assurance_next_review,
            acknowledge=args.acknowledge_reliability_assurance,
        )
        if isinstance(result, dict):
            print(f"Assurance:    {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Attestation:  {result.attestation_path}")
        print(f"Audit pack:   {result.audit_pack_path}")
        print(f"Receipt:      {result.receipt_path}")
        return 0

    path = service.export_snapshot(snapshot)
    print(f"Snapshot:     {path}")
    return 1 if snapshot.blocker_count else 0


def _handle_reliability_assurance_renewal_command(argv: list[str]) -> int | None:
    flags = {
        "--reliability-renewal-snapshot",
        "--create-reliability-renewal",
        "--verify-reliability-renewal",
        "--verify-reliability-renewal-follow-up",
        "--verify-reliability-renewal-pack",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.services.reliability_assurance_renewal_service import (
        ReliabilityAssuranceRenewalService,
    )

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking reliability assurance renewal and exception follow-up",
    )
    parser.add_argument("--reliability-renewal-snapshot", action="store_true")
    parser.add_argument("--create-reliability-renewal", action="store_true")
    parser.add_argument("--verify-reliability-renewal", type=Path)
    parser.add_argument("--verify-reliability-renewal-follow-up", type=Path)
    parser.add_argument("--verify-reliability-renewal-pack", type=Path)
    parser.add_argument("--reliability-renewal-receipt", type=Path)
    parser.add_argument(
        "--reliability-renewal-attestation",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--reliability-renewal-audit-pack",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--reliability-renewal-source-receipt",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--reliability-renewal-validity-days",
        type=int,
        default=ReliabilityAssuranceRenewalService.DEFAULT_VALIDITY_DAYS,
    )
    parser.add_argument(
        "--reliability-renewal-due-soon-days",
        type=int,
        default=ReliabilityAssuranceRenewalService.DEFAULT_DUE_SOON_DAYS,
    )
    parser.add_argument(
        "--reliability-renewal-outcome",
        choices=ReliabilityAssuranceRenewalService.RENEWAL_DECISIONS,
        default="renew",
    )
    parser.add_argument("--reliability-renewal-owner", default="")
    parser.add_argument("--reliability-renewal-statement", default="")
    parser.add_argument("--reliability-renewal-follow-up-owner", default="")
    parser.add_argument("--reliability-renewal-next-review", default="")
    parser.add_argument("--acknowledge-reliability-renewal", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    service = ReliabilityAssuranceRenewalService(runtime)

    if args.verify_reliability_renewal:
        ok, detail = service.verify_renewal(args.verify_reliability_renewal)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_reliability_renewal_follow_up:
        ok, detail = service.verify_follow_up(
            args.verify_reliability_renewal_follow_up
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_reliability_renewal_pack:
        if args.reliability_renewal_receipt is None:
            print("Verification: failed — a renewal audit-pack receipt is required.")
            return 1
        ok, detail = service.verify_audit_pack(
            args.verify_reliability_renewal_pack,
            args.reliability_renewal_receipt,
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    snapshot = service.snapshot(
        attestation_paths=args.reliability_renewal_attestation,
        audit_pack_paths=args.reliability_renewal_audit_pack,
        receipt_paths=args.reliability_renewal_source_receipt,
        validity_days=args.reliability_renewal_validity_days,
        due_soon_days=args.reliability_renewal_due_soon_days,
    )
    print(f"Status:       {snapshot.status}")
    print(f"Triplets:     {snapshot.verified_triplet_count}")
    print(f"Current:      {snapshot.current_count}")
    print(f"Due soon:     {snapshot.due_soon_count}")
    print(f"Overdue:      {snapshot.overdue_count}")
    print(f"Withheld:     {snapshot.withheld_count}")
    print(f"Follow-up:    {snapshot.open_exception_count}")
    print(f"Blockers:     {snapshot.blocker_count}")
    print(f"Warnings:     {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_reliability_renewal:
        result = service.create_renewal(
            snapshot,
            decision=args.reliability_renewal_outcome,
            owner=args.reliability_renewal_owner,
            statement=args.reliability_renewal_statement,
            follow_up_owner=args.reliability_renewal_follow_up_owner,
            next_review_date=args.reliability_renewal_next_review,
            acknowledge=args.acknowledge_reliability_renewal,
        )
        if isinstance(result, dict):
            print(f"Renewal:      {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Renewal:      {result.renewal_path}")
        print(f"Follow-up:    {result.follow_up_path}")
        print(f"Audit pack:   {result.audit_pack_path}")
        print(f"Receipt:      {result.receipt_path}")
        return 0

    path = service.export_snapshot(snapshot)
    print(f"Snapshot:     {path}")
    return 1 if snapshot.blocker_count else 0


def _handle_service_continuity_command(argv: list[str]) -> int | None:
    flags = {
        "--service-continuity-snapshot",
        "--create-service-continuity-plan",
        "--record-service-continuity-result",
        "--verify-service-continuity-plan",
        "--verify-service-continuity-result",
        "--verify-service-continuity-attestation",
        "--verify-service-continuity-pack",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.database.connection import Database
    from app.services.reliability_assurance_renewal_service import (
        ReliabilityAssuranceRenewalService,
    )
    from app.services.service_continuity_service import ServiceContinuityService
    from app.services.upgrade_recovery_service import UpgradeRecoveryService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking service continuity, backup recovery and RTO/RPO evidence",
    )
    parser.add_argument("--service-continuity-snapshot", action="store_true")
    parser.add_argument("--create-service-continuity-plan", action="store_true")
    parser.add_argument("--record-service-continuity-result", action="store_true")
    parser.add_argument("--verify-service-continuity-plan", type=Path)
    parser.add_argument("--verify-service-continuity-result", type=Path)
    parser.add_argument("--verify-service-continuity-attestation", type=Path)
    parser.add_argument("--verify-service-continuity-pack", type=Path)
    parser.add_argument("--service-continuity-receipt", type=Path)
    parser.add_argument(
        "--service-continuity-renewal",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--service-continuity-follow-up",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--service-continuity-audit-pack",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--service-continuity-source-receipt",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--service-continuity-backup",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--service-continuity-rto-minutes",
        type=int,
        default=ServiceContinuityService.DEFAULT_RTO_MINUTES,
    )
    parser.add_argument(
        "--service-continuity-rpo-minutes",
        type=int,
        default=ServiceContinuityService.DEFAULT_RPO_MINUTES,
    )
    parser.add_argument(
        "--service-continuity-window-days",
        type=int,
        default=ServiceContinuityService.DEFAULT_DRILL_WINDOW_DAYS,
    )
    parser.add_argument(
        "--service-continuity-environment",
        choices=ServiceContinuityService.ENVIRONMENTS,
        default="isolated_sandbox",
    )
    parser.add_argument("--service-continuity-owner", default="")
    parser.add_argument("--service-continuity-notes", default="")
    parser.add_argument("--service-continuity-plan", type=Path)
    parser.add_argument("--service-continuity-actual-restore-minutes", type=int, default=0)
    parser.add_argument("--service-continuity-observed-data-loss-minutes", type=int, default=0)
    parser.add_argument(
        "--service-continuity-database-check",
        choices=("ok", "not_applicable", "failed"),
        default="not_applicable",
    )
    parser.add_argument("--service-continuity-manifest-verified", action="store_true")
    parser.add_argument("--service-continuity-regression-tests", type=int, default=1)
    parser.add_argument("--service-continuity-failed-tests", type=int, default=0)
    parser.add_argument("--service-continuity-conclusion", default="")
    parser.add_argument("--acknowledge-service-continuity", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    database = Database(runtime.database_path)
    database.initialize()
    renewal_service = ReliabilityAssuranceRenewalService(runtime)
    upgrade_service = UpgradeRecoveryService(runtime, database)
    service = ServiceContinuityService(
        runtime,
        renewal_service,
        upgrade_service,
    )

    if args.verify_service_continuity_plan:
        ok, detail = service.verify_plan(args.verify_service_continuity_plan)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_service_continuity_result:
        ok, detail = service.verify_result(args.verify_service_continuity_result)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_service_continuity_attestation:
        ok, detail = service.verify_attestation(
            args.verify_service_continuity_attestation
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_service_continuity_pack:
        if args.service_continuity_receipt is None:
            print("Verification: failed — a continuity audit-pack receipt is required.")
            return 1
        ok, detail = service.verify_audit_pack(
            args.verify_service_continuity_pack,
            args.service_continuity_receipt,
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    if args.record_service_continuity_result:
        if args.service_continuity_plan is None:
            print("Result:        blocked — a verified continuity plan is required.")
            return 1
        result = service.record_drill_result(
            args.service_continuity_plan,
            actual_restore_minutes=args.service_continuity_actual_restore_minutes,
            observed_data_loss_minutes=(
                args.service_continuity_observed_data_loss_minutes
            ),
            database_quick_check=args.service_continuity_database_check,
            manifest_verified=args.service_continuity_manifest_verified,
            regression_test_count=args.service_continuity_regression_tests,
            failed_test_count=args.service_continuity_failed_tests,
            owner=args.service_continuity_owner,
            conclusion=args.service_continuity_conclusion,
            acknowledge=args.acknowledge_service_continuity,
        )
        if isinstance(result, dict):
            print(f"Result:        {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Outcome:       {result.outcome}")
        print(f"Result:        {result.result_path}")
        print(f"Attestation:   {result.attestation_path}")
        print(f"Audit pack:    {result.audit_pack_path}")
        print(f"Receipt:       {result.receipt_path}")
        return 0 if result.outcome == "passed" else 2

    snapshot = service.snapshot(
        renewal_paths=args.service_continuity_renewal,
        follow_up_paths=args.service_continuity_follow_up,
        audit_pack_paths=args.service_continuity_audit_pack,
        receipt_paths=args.service_continuity_source_receipt,
        backup_dirs=args.service_continuity_backup,
        rto_target_minutes=args.service_continuity_rto_minutes,
        rpo_target_minutes=args.service_continuity_rpo_minutes,
        drill_window_days=args.service_continuity_window_days,
    )
    print(f"Status:        {snapshot.status}")
    print(f"Renewals:      {snapshot.verified_renewal_count}")
    print(f"Backups:       {snapshot.verified_backup_count}")
    print(f"Stale backups: {snapshot.stale_backup_count}")
    print(f"Open follow-up:{snapshot.open_follow_up_count}")
    print(f"RTO target:    {snapshot.rto_target_minutes} min")
    print(f"RPO target:    {snapshot.rpo_target_minutes} min")
    print(f"Blockers:      {snapshot.blocker_count}")
    print(f"Warnings:      {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_service_continuity_plan:
        result = service.create_drill_plan(
            snapshot,
            owner=args.service_continuity_owner,
            environment=args.service_continuity_environment,
            notes=args.service_continuity_notes,
            acknowledge=args.acknowledge_service_continuity,
        )
        if isinstance(result, dict):
            print(f"Plan:          {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Plan:          {result.plan_path}")
        return 0

    path = service.export_snapshot(snapshot)
    print(f"Snapshot:      {path}")
    return 1 if snapshot.blocker_count else 0


def _handle_service_level_objectives_command(argv: list[str]) -> int | None:
    flags = {
        "--slo-snapshot",
        "--create-slo-observation",
        "--create-slo-decision",
        "--verify-slo-observation",
        "--verify-slo-snapshot",
        "--verify-slo-decision",
        "--verify-slo-pack",
    }
    if not any(flag in argv for flag in flags):
        return None

    import argparse

    from app.database.connection import Database
    from app.services.reliability_assurance_renewal_service import (
        ReliabilityAssuranceRenewalService,
    )
    from app.services.reliability_assurance_service import ReliabilityAssuranceService
    from app.services.service_continuity_service import ServiceContinuityService
    from app.services.service_level_objectives_service import (
        ServiceLevelObjectivesService,
    )
    from app.services.upgrade_recovery_service import UpgradeRecoveryService

    parser = argparse.ArgumentParser(
        prog="S-Talking.exe",
        description="S Talking service-level objectives and error-budget evidence",
    )
    parser.add_argument("--slo-snapshot", action="store_true")
    parser.add_argument("--create-slo-observation", action="store_true")
    parser.add_argument("--create-slo-decision", action="store_true")
    parser.add_argument("--verify-slo-observation", type=Path)
    parser.add_argument("--verify-slo-snapshot", type=Path)
    parser.add_argument("--verify-slo-decision", type=Path)
    parser.add_argument("--verify-slo-pack", type=Path)
    parser.add_argument("--slo-receipt", type=Path)
    parser.add_argument(
        "--slo-observation",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--slo-continuity-result",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--slo-continuity-attestation",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--slo-continuity-pack",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--slo-continuity-receipt",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--slo-window-days",
        type=int,
        default=ServiceLevelObjectivesService.DEFAULT_WINDOW_DAYS,
    )
    parser.add_argument(
        "--slo-availability-target",
        type=float,
        default=ServiceLevelObjectivesService.DEFAULT_AVAILABILITY_TARGET,
    )
    parser.add_argument(
        "--slo-success-target",
        type=float,
        default=ServiceLevelObjectivesService.DEFAULT_SUCCESS_TARGET,
    )
    parser.add_argument(
        "--slo-p95-latency-target-ms",
        type=int,
        default=ServiceLevelObjectivesService.DEFAULT_P95_LATENCY_TARGET_MS,
    )
    parser.add_argument("--slo-window-start", default="")
    parser.add_argument("--slo-window-end", default="")
    parser.add_argument("--slo-total-operations", type=int, default=0)
    parser.add_argument("--slo-successful-operations", type=int, default=0)
    parser.add_argument("--slo-failed-operations", type=int, default=0)
    parser.add_argument("--slo-unavailable-minutes", type=int, default=0)
    parser.add_argument("--slo-observed-p95-latency-ms", type=int, default=0)
    parser.add_argument(
        "--slo-decision",
        choices=ServiceLevelObjectivesService.DECISIONS,
        default="hold",
    )
    parser.add_argument("--slo-owner", default="")
    parser.add_argument("--slo-notes", default="")
    parser.add_argument("--slo-statement", default="")
    parser.add_argument("--acknowledge-slo", action="store_true")
    args = parser.parse_args(argv[1:])

    runtime = (
        RuntimeConfig.from_frozen()
        if getattr(sys, "frozen", False)
        else RuntimeConfig.from_root()
    )
    runtime.ensure_directories()
    database = Database(runtime.database_path)
    database.initialize()
    assurance_service = ReliabilityAssuranceService(runtime)
    renewal_service = ReliabilityAssuranceRenewalService(
        runtime,
        assurance_service,
    )
    upgrade_service = UpgradeRecoveryService(runtime, database)
    continuity_service = ServiceContinuityService(
        runtime,
        renewal_service,
        upgrade_service,
    )
    service = ServiceLevelObjectivesService(runtime, continuity_service)

    if args.verify_slo_observation:
        ok, detail = service.verify_observation(args.verify_slo_observation)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_slo_snapshot:
        ok, detail = service.verify_snapshot(args.verify_slo_snapshot)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_slo_decision:
        ok, detail = service.verify_decision(args.verify_slo_decision)
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1
    if args.verify_slo_pack:
        if args.slo_receipt is None:
            print("Verification: failed — an SLO audit-pack receipt is required.")
            return 1
        ok, detail = service.verify_audit_pack(
            args.verify_slo_pack,
            args.slo_receipt,
        )
        print(f"Verification: {'passed' if ok else 'failed'} — {detail}")
        return 0 if ok else 1

    if args.create_slo_observation:
        result = service.create_observation(
            window_start=args.slo_window_start,
            window_end=args.slo_window_end,
            total_operations=args.slo_total_operations,
            successful_operations=args.slo_successful_operations,
            failed_operations=args.slo_failed_operations,
            unavailable_minutes=args.slo_unavailable_minutes,
            p95_latency_ms=args.slo_observed_p95_latency_ms,
            owner=args.slo_owner,
            notes=args.slo_notes,
            acknowledge=args.acknowledge_slo,
        )
        if isinstance(result, dict):
            print(f"Observation:   {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Observation:   {result.observation_path}")
        return 0

    snapshot = service.snapshot(
        observation_paths=args.slo_observation,
        continuity_result_paths=args.slo_continuity_result,
        continuity_attestation_paths=args.slo_continuity_attestation,
        continuity_pack_paths=args.slo_continuity_pack,
        continuity_receipt_paths=args.slo_continuity_receipt,
        window_days=args.slo_window_days,
        availability_target_percent=args.slo_availability_target,
        success_target_percent=args.slo_success_target,
        p95_latency_target_ms=args.slo_p95_latency_target_ms,
    )
    print(f"Status:        {snapshot.status}")
    print(f"Release gate:  {snapshot.release_gate}")
    print(f"Availability:  {snapshot.availability_percent:.4f}%")
    print(f"Success:       {snapshot.success_percent:.4f}%")
    print(f"P95 latency:   {snapshot.p95_latency_ms} ms")
    print(f"Budget burn:   {snapshot.error_budget_burn_rate:.3f}")
    print(f"Blockers:      {snapshot.blocker_count}")
    print(f"Warnings:      {snapshot.warning_count}")
    for gate in snapshot.gates:
        if gate.status in {"warn", "block"}:
            print(f" - {gate.label} [{gate.status}]: {gate.detail}")

    if args.create_slo_decision:
        result = service.create_release_decision(
            snapshot,
            decision=args.slo_decision,
            owner=args.slo_owner,
            statement=args.slo_statement,
            acknowledge=args.acknowledge_slo,
        )
        if isinstance(result, dict):
            print(f"Decision:      {result.get('status')} — {result.get('detail')}")
            return 1
        print(f"Decision:      {result.decision_path}")
        print(f"Audit pack:    {result.audit_pack_path}")
        print(f"Receipt:       {result.receipt_path}")
        return 0

    path = service.export_snapshot(snapshot)
    print(f"Snapshot:      {path}")
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
        incident_resolution_exit = _handle_incident_resolution_command(sys.argv)
        if incident_resolution_exit is not None:
            return incident_resolution_exit
        incident_prevention_exit = _handle_incident_prevention_command(sys.argv)
        if incident_prevention_exit is not None:
            return incident_prevention_exit
        prevention_effectiveness_exit = _handle_prevention_effectiveness_command(sys.argv)
        if prevention_effectiveness_exit is not None:
            return prevention_effectiveness_exit
        reliability_assurance_exit = _handle_reliability_assurance_command(sys.argv)
        if reliability_assurance_exit is not None:
            return reliability_assurance_exit
        reliability_renewal_exit = _handle_reliability_assurance_renewal_command(
            sys.argv
        )
        if reliability_renewal_exit is not None:
            return reliability_renewal_exit
        continuity_exit = _handle_service_continuity_command(sys.argv)
        if continuity_exit is not None:
            return continuity_exit
        slo_exit = _handle_service_level_objectives_command(sys.argv)
        if slo_exit is not None:
            return slo_exit

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
