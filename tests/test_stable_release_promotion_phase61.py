from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.services.production_release_certification_service import (
    ProductionReleaseCertificationService,
)
from app.services.stable_release_promotion_service import StableReleasePromotionService


ATTESTED_COMMIT = "a" * 40
STABLE_COMMIT = "b" * 40


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return runtime


def _write(path: Path, payload: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _packaging_identity(runtime: RuntimeConfig, *, version: str = "1.0.0") -> None:
    (runtime.app_root / "app").mkdir(parents=True, exist_ok=True)
    (runtime.app_root / "app" / "release.py").write_text(
        f'VERSION = "{version}"\nRELEASE_CHANNEL = "stable"\n',
        encoding="utf-8",
    )
    (runtime.app_root / "pyproject.toml").write_text(
        f'[project]\nversion = "{version.replace("-", "")}"\n',
        encoding="utf-8",
    )
    windows = runtime.app_root / "packaging" / "windows"
    windows.mkdir(parents=True, exist_ok=True)
    (windows / "S-Talking.iss").write_text(
        f'#define AppVersion "{version}"\n#define OutputBaseFilename "S-Talking-{version}-setup"\n',
        encoding="utf-8",
    )
    (windows / "version_info.txt").write_text(
        f'StringStruct("FileVersion", "{version}")\nStringStruct("ProductVersion", "{version}")\n',
        encoding="utf-8",
    )


def _attestation(runtime: RuntimeConfig, *, target: str = "1.0.0", source: str = ATTESTED_COMMIT) -> Path:
    service = ProductionReleaseCertificationService(runtime)
    payload = {
        "schema_version": service.SCHEMA_VERSION,
        "target_version": target,
        "source_version": "0.18.2-rc1",
        "source_commit": source,
        "blocker_count": 0,
        "warning_count": 2,
        "promotion_allowed": True,
        "status": "ready_with_warnings",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "attestation_path": "",
        "automatic_publish": False,
        "automatic_version_change": False,
    }
    document = {
        "payload": payload,
        "payload_sha256": service._payload_digest(payload),
    }
    return _write(
        runtime.artifacts_dir
        / "production-certification"
        / "production-release-attestation.json",
        document,
    )


def _service(runtime: RuntimeConfig, *, version: str = "1.0.0", channel: str = "stable") -> StableReleasePromotionService:
    return StableReleasePromotionService(
        runtime,
        ProductionReleaseCertificationService(runtime),
        version=version,
        channel=channel,
    )


def _snapshot(service: StableReleasePromotionService, attestation: Path):
    return service.snapshot(
        attestation_path=attestation,
        source_commit=STABLE_COMMIT,
        parent_commit=ATTESTED_COMMIT,
        working_tree_clean=True,
        rollout_percentage=25,
    )


def _stable_artifacts(runtime: RuntimeConfig, *, unsafe: bool = False) -> tuple[Path, Path, Path]:
    final_dir = runtime.artifacts_dir / "final-release" / "latest"
    final_dir.mkdir(parents=True, exist_ok=True)
    portable = final_dir / "S-Talking-1.0.0-portable.zip"
    portable.write_bytes(b"stable-portable-package")
    artifact_name = "../outside.zip" if unsafe else portable.name
    final_manifest = _write(
        final_dir / "final-release-manifest.json",
        {
            "schema_version": 1,
            "version": "1.0.0",
            "channel": "stable",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "signature_policy": {
                "required": False,
                "application_verified": False,
                "installer_verified": False,
                "timestamp_verified": False,
            },
            "artifacts": [
                {
                    "role": "portable_package",
                    "path": artifact_name,
                    "size_bytes": portable.stat().st_size,
                    "sha256": _sha(portable),
                }
            ],
        },
    )

    channel_dir = runtime.artifacts_dir / "update-channel" / "stable"
    channel_dir.mkdir(parents=True, exist_ok=True)
    channel_portable = channel_dir / portable.name
    channel_portable.write_bytes(portable.read_bytes())
    feed = _write(
        channel_dir / "latest.json",
        {
            "schema_version": 1,
            "product": "S Talking",
            "channel": "stable",
            "version": "1.0.0",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "rollout_percentage": 25,
            "artifacts": [
                {
                    "role": "portable_package",
                    "filename": channel_portable.name,
                    "url": channel_portable.name,
                    "size_bytes": channel_portable.stat().st_size,
                    "sha256": _sha(channel_portable),
                }
            ],
        },
    )
    feed.with_suffix(".sha256").write_text(
        f"{_sha(feed)}  {feed.name}\n",
        encoding="ascii",
    )

    sbom = _write(
        runtime.artifacts_dir
        / "security-supply-chain"
        / "sbom"
        / "S-Talking-SBOM.spdx.json",
        {
            "spdxVersion": "SPDX-2.3",
            "SPDXID": "SPDXRef-DOCUMENT",
            "packages": [
                {
                    "SPDXID": "SPDXRef-Package-S-Talking",
                    "name": "S Talking",
                    "versionInfo": "1.0.0",
                },
                {
                    "SPDXID": "SPDXRef-Package-Python",
                    "name": "Python",
                    "versionInfo": "3.13",
                },
            ],
        },
    )
    return final_manifest, feed, sbom


def test_phase61_stable_identity_attestation_lineage_and_manual_publication_pass(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _packaging_identity(runtime)
    attestation = _attestation(runtime)
    service = _service(runtime)
    snapshot = _snapshot(service, attestation)

    assert snapshot.status == "ready"
    assert snapshot.promotion_allowed
    assert snapshot.blocker_count == 0
    assert snapshot.version == "1.0.0"
    assert snapshot.channel == "stable"
    assert snapshot.source_commit == STABLE_COMMIT
    assert snapshot.attested_commit == ATTESTED_COMMIT
    assert any(gate.code == "manual_publication" and gate.passed for gate in snapshot.gates)


def test_phase61_blocks_prerelease_identity_wrong_target_dirty_tree_and_bad_lineage(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _packaging_identity(runtime, version="1.0.0-rc1")
    attestation = _attestation(runtime, target="1.0.0")
    service = _service(runtime, version="1.0.0-rc1", channel="preview")
    snapshot = service.snapshot(
        attestation_path=attestation,
        source_commit=STABLE_COMMIT,
        parent_commit="c" * 40,
        working_tree_clean=False,
    )

    blocked = {gate.code for gate in snapshot.gates if gate.status == "block"}
    assert snapshot.status == "blocked"
    assert not snapshot.promotion_allowed
    assert {"stable_identity", "attested_target", "attested_lineage", "clean_working_tree"} <= blocked


def test_phase61_rollback_point_requires_acknowledgement_and_detects_tampering(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _packaging_identity(runtime)
    attestation = _attestation(runtime)
    preview = runtime.artifacts_dir / "update-channel" / "preview"
    preview.mkdir(parents=True)
    (preview / "latest.json").write_text('{"channel":"preview"}\n', encoding="utf-8")
    service = _service(runtime)
    snapshot = _snapshot(service, attestation)

    dry_run = service.create_rollback_point(snapshot, attestation_path=attestation)
    assert dry_run["status"] == "dry_run"
    assert not list(service.rollback_root.glob("*"))

    prepared = service.create_rollback_point(
        snapshot,
        attestation_path=attestation,
        acknowledge=True,
    )
    manifest = Path(str(prepared["path"]))
    ok, detail = service.verify_rollback_manifest(manifest)
    assert prepared["status"] == "prepared"
    assert ok, detail
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    first = manifest.parent / payload["artifacts"][0]["path"]
    first.write_text("tampered", encoding="utf-8")
    ok, detail = service.verify_rollback_manifest(manifest)
    assert not ok
    assert "mismatch" in detail.casefold()


def test_phase61_verifies_stable_manifest_feed_sbom_with_nonblocking_signing_warnings(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _packaging_identity(runtime)
    attestation = _attestation(runtime)
    final_manifest, feed, sbom = _stable_artifacts(runtime)
    service = _service(runtime)
    snapshot = service.snapshot(
        attestation_path=attestation,
        source_commit=STABLE_COMMIT,
        parent_commit=ATTESTED_COMMIT,
        working_tree_clean=True,
        rollout_percentage=25,
        include_artifact_gates=True,
        final_manifest_path=final_manifest,
        stable_feed_path=feed,
        sbom_path=sbom,
    )

    assert snapshot.promotion_allowed
    assert snapshot.blocker_count == 0
    assert snapshot.status == "ready_with_warnings"
    assert snapshot.warning_count == 2
    assert {artifact.role for artifact in snapshot.artifacts} >= {
        "production_attestation",
        "final_release_manifest",
        "stable_update_feed",
        "spdx_sbom",
    }


def test_phase61_blocks_unsafe_manifest_and_tampered_stable_feed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _packaging_identity(runtime)
    attestation = _attestation(runtime)
    final_manifest, feed, sbom = _stable_artifacts(runtime, unsafe=True)
    feed.write_text(feed.read_text(encoding="utf-8") + " ", encoding="utf-8")
    service = _service(runtime)
    snapshot = service.snapshot(
        attestation_path=attestation,
        source_commit=STABLE_COMMIT,
        parent_commit=ATTESTED_COMMIT,
        working_tree_clean=True,
        rollout_percentage=25,
        include_artifact_gates=True,
        final_manifest_path=final_manifest,
        stable_feed_path=feed,
        sbom_path=sbom,
    )

    blocked = {gate.code for gate in snapshot.gates if gate.status == "block"}
    assert {"stable_final_manifest", "stable_update_feed"} <= blocked
    assert not snapshot.promotion_allowed


def test_phase61_receipt_requires_verified_rollback_is_privacy_safe_and_tamper_evident(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _packaging_identity(runtime)
    attestation = _attestation(runtime)
    final_manifest, feed, sbom = _stable_artifacts(runtime)
    service = _service(runtime)
    source_snapshot = _snapshot(service, attestation)
    rollback_result = service.create_rollback_point(
        source_snapshot,
        attestation_path=attestation,
        acknowledge=True,
    )
    rollback = Path(str(rollback_result["path"]))
    artifact_snapshot = service.snapshot(
        attestation_path=attestation,
        source_commit=STABLE_COMMIT,
        parent_commit=ATTESTED_COMMIT,
        working_tree_clean=True,
        rollout_percentage=25,
        include_artifact_gates=True,
        final_manifest_path=final_manifest,
        stable_feed_path=feed,
        sbom_path=sbom,
    )

    dry_run = service.write_promotion_receipt(
        artifact_snapshot,
        rollback_manifest=rollback,
        attestation_path=attestation,
        final_manifest_path=final_manifest,
        stable_feed_path=feed,
        sbom_path=sbom,
    )
    assert dry_run["status"] == "dry_run"

    result = service.write_promotion_receipt(
        artifact_snapshot,
        rollback_manifest=rollback,
        attestation_path=attestation,
        final_manifest_path=final_manifest,
        stable_feed_path=feed,
        sbom_path=sbom,
        acknowledge=True,
    )
    receipt = Path(str(result["path"]))
    ok, detail = service.verify_promotion_receipt(receipt)
    assert result["status"] == "verified"
    assert ok, detail
    text = receipt.read_text(encoding="utf-8")
    assert str(tmp_path) not in text
    assert '"automatic_publish": false' in text
    assert '"automatic_tag": false' in text
    document = json.loads(text)
    document["rollout_percentage"] = 99
    receipt.write_text(json.dumps(document), encoding="utf-8")
    ok, detail = service.verify_promotion_receipt(receipt)
    assert not ok
    assert "SHA-256" in detail


def test_phase61_strict_installer_and_signature_policy_turns_warnings_into_blockers(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _packaging_identity(runtime)
    attestation = _attestation(runtime)
    final_manifest, feed, sbom = _stable_artifacts(runtime)
    service = _service(runtime)
    snapshot = service.snapshot(
        attestation_path=attestation,
        source_commit=STABLE_COMMIT,
        parent_commit=ATTESTED_COMMIT,
        working_tree_clean=True,
        rollout_percentage=25,
        include_artifact_gates=True,
        final_manifest_path=final_manifest,
        stable_feed_path=feed,
        sbom_path=sbom,
        require_installer=True,
        require_signatures=True,
    )

    blocked = {gate.code for gate in snapshot.gates if gate.status == "block"}
    assert {"stable_installer", "stable_signatures"} <= blocked
    assert snapshot.status == "blocked"


def test_phase61_cli_script_ui_container_release_and_no_automatic_publish_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    release = (root / "app" / "release.py").read_text(encoding="utf-8")
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    frozen = (root / "app" / "frozen_main.py").read_text(encoding="utf-8")
    service = (root / "app" / "services" / "stable_release_promotion_service.py").read_text(encoding="utf-8")
    dialog = (root / "app" / "gui" / "dialogs" / "stable_release_promotion_dialog.py").read_text(encoding="utf-8")
    main = (root / "app" / "gui" / "main.py").read_text(encoding="utf-8")
    container = (root / "app" / "container.py").read_text(encoding="utf-8")
    script = (root / "scripts" / "stable-release.ps1").read_text(encoding="utf-8")
    notes_service = (root / "app" / "services" / "release_candidate_service.py").read_text(encoding="utf-8")
    security_service = (root / "app" / "services" / "security_supply_chain_service.py").read_text(encoding="utf-8")
    build = (root / "scripts" / "build.ps1").read_text(encoding="utf-8")

    assert 'VERSION = "1.0.0"' in release
    assert 'RELEASE_CHANNEL = "stable"' in release
    assert 'version = "1.0.0"' in pyproject
    assert "--stable-promotion-snapshot" in frozen
    assert "--write-stable-promotion-receipt" in frozen
    assert "--verify-stable-rollback" in frozen
    assert "never invokes Git tag, Git push, a network upload" in service
    assert "automatic_publish" in service
    assert "Stable 1.0 release promotion" in dialog
    assert "Reports: Stable Release Promotion" in main
    assert "stable_release_promotion_service" in container
    assert "-Channel stable" in script
    assert "No Git tag, push, upload" in script
    assert "Stable Release" in notes_service
    assert "S_TALKING_REQUIRE_SIGNING" in security_service
    assert "S_TALKING_REQUIRE_SIGNING" in build


def test_phase61_dialog_mainwindow_and_service_container_contracts(qt_app, tmp_path: Path) -> None:
    from app.bootstrap import create_application_context
    from app.container import create_service_container
    from app.gui.dialogs.stable_release_promotion_dialog import StableReleasePromotionDialog
    from app.gui.main import MainWindow

    runtime = _runtime(tmp_path)
    _packaging_identity(runtime)
    _attestation(runtime)
    container = create_service_container(runtime)
    service = container.stable_release_promotion_service

    dialog = StableReleasePromotionDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "stableReleasePromotionDialog"
    assert dialog.table.rowCount() >= 9
    dialog.close()

    window = MainWindow(create_application_context(container))
    window.show()
    qt_app.processEvents()
    assert "Stable Release Promotion" in window.actions_by_name
    assert any(
        command.name == "Reports: Stable Release Promotion"
        for command in window.command_palette_commands()
    )
    opened = window.open_stable_release_promotion()
    assert opened.objectName() == "stableReleasePromotionDialog"
    window.close()
