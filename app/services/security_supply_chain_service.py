from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import re
import stat
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable
from urllib.parse import quote

import app
from app.config.runtime import RuntimeConfig
from app.models.security_supply_chain import (
    SecurityArtifact,
    SecurityAuditReceipt,
    SecurityComponent,
    SecurityGate,
    SecuritySupplyChainSnapshot,
)
from app.release import RELEASE_CHANNEL
from app.security_runtime import harden_windows_dll_search
from app.services.secure_credentials import SecureCredentialStore


class SecuritySupplyChainService:
    """Audit credential storage, dependencies and distributable artifacts.

    Evidence is metadata-only: package names and versions, file names, sizes and
    hashes. The service never exports provider keys, project text, database rows,
    generated audio, settings values or credential blobs.
    """

    SCHEMA_VERSION = 1
    SPDX_VERSION = "SPDX-2.3"
    SPDX_DATA_LICENSE = "CC0-1.0"
    SBOM_NAME = "S-Talking-SBOM.spdx.json"
    SNAPSHOT_NAME = "latest-security-snapshot.json"
    VULNERABILITY_NAME = "vulnerability-latest.json"
    MAX_ZIP_ENTRIES = 50_000
    MAX_UNCOMPRESSED_BYTES = 4 * 1024**3
    _PRIVATE_PARTS = {
        "credentials",
        "s-talking-data",
        "logs",
        "reports",
        "output",
        "cache",
        ".git",
        ".venv",
    }
    _PRIVATE_NAMES = {
        "settings.json",
        "api-profiles.json",
        "workspace-profiles.json",
        "s_talking.db",
        "s-talking.db",
    }
    _WINDOWS_RESERVED = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
    _UNSAFE_EXECUTABLE_SUFFIXES = {".bat", ".com", ".cpl", ".msi", ".ps1", ".scr", ".vbs"}
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key|authorization|bearer|credential|password|secret|token)"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        credential_store: SecureCredentialStore,
        *,
        now: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.credential_store = credential_store
        self.root = runtime.artifacts_dir / "security-supply-chain"
        self.sbom_dir = self.root / "sbom"
        self.audit_dir = self.root / "package-audits"
        self.exports_dir = self.root / "exports"
        self.latest_snapshot_path = self.root / self.SNAPSHOT_NAME
        self.vulnerability_path = self.root / self.VULNERABILITY_NAME
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._command_runner = command_runner or subprocess.run
        self._component_cache: tuple[SecurityComponent, ...] | None = None
        for path in (self.root, self.sbom_dir, self.audit_dir, self.exports_dir):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def harden_windows_dll_search(runtime: RuntimeConfig) -> tuple[str, str]:
        return harden_windows_dll_search(runtime)

    def snapshot(self, package_path: Path | None = None) -> SecuritySupplyChainSnapshot:
        components = self.component_inventory()
        package = Path(package_path) if package_path else self.latest_portable_package()
        gates: list[SecurityGate] = []
        artifacts: list[SecurityArtifact] = []

        credential_status, credential_detail = self.credential_store.security_status()
        gates.append(
            self._gate(
                "credential_backend",
                "Credential storage backend",
                credential_status,
                "warning",
                credential_detail,
                "Use Windows Credential Manager for production provider secrets.",
            )
        )
        legacy_count = self.credential_store.legacy_file_count()
        legacy_status = "warn" if self.credential_store.backend_name == "windows-credential-manager" and legacy_count else "pass"
        gates.append(
            self._gate(
                "legacy_credentials",
                "Legacy credential files",
                legacy_status,
                "warning",
                (
                    f"{legacy_count} legacy credential file(s) remain and will migrate on first access."
                    if legacy_count
                    else "No pending legacy credential files require migration."
                ),
                "Open each saved provider profile once, verify it, then remove obsolete backups.",
            )
        )

        inventory_ok = bool(components) and any(component.name.casefold() == "s-talking" for component in components)
        gates.append(
            self._gate(
                "component_inventory",
                "Dependency inventory",
                "pass" if inventory_ok else "block",
                "blocker",
                f"Inventory contains {len(components)} component(s)." if inventory_ok else "Application component is missing from inventory.",
                "Rebuild the environment and generate a complete SBOM.",
            )
        )

        sbom = self.latest_sbom_path()
        sbom_ok, sbom_detail = self.verify_sbom(sbom) if sbom.exists() else (False, "No verified SPDX SBOM has been generated yet.")
        gates.append(
            self._gate(
                "sbom",
                "SPDX software bill of materials",
                "pass" if sbom_ok else "warn",
                "warning",
                sbom_detail,
                "Generate and verify the SPDX SBOM before final stable release.",
            )
        )
        if sbom.exists():
            artifacts.append(self._artifact("spdx_sbom", sbom, "verified" if sbom_ok else "failed", sbom_detail))

        if package and package.exists():
            audit_ok, audit_detail, issues = self.inspect_package(package)
            gates.append(
                self._gate(
                    "package_integrity",
                    "Portable package integrity",
                    "pass" if audit_ok else "block",
                    "blocker",
                    audit_detail,
                    "Rebuild the package after removing unsafe, private or unmanifested files.",
                )
            )
            artifacts.append(self._artifact("portable_package", package, "verified" if audit_ok else "failed", audit_detail))
            dll_status = "block" if any(issue.startswith("dll:") for issue in issues) else "pass"
            dll_detail = "No root-level or untrusted DLL placement was detected." if dll_status == "pass" else "Unsafe DLL placement was detected in the portable package."
        else:
            gates.append(
                self._gate(
                    "package_integrity",
                    "Portable package integrity",
                    "not_measured",
                    "warning",
                    "No portable package is available for inspection.",
                    "Build the portable ZIP and run the security audit.",
                )
            )
            dll_status = "not_measured"
            dll_detail = "DLL layout is measured when a portable package is available."
        gates.append(
            self._gate(
                "dll_layout",
                "DLL hijacking resistance",
                dll_status,
                "blocker",
                dll_detail,
                "Keep application DLLs under _internal and never ship arbitrary DLLs beside S-Talking.exe.",
            )
        )

        runtime_status, runtime_detail = self._runtime_hardening_status()
        gates.append(
            self._gate(
                "runtime_dll_search",
                "Runtime DLL search policy",
                runtime_status,
                "warning",
                runtime_detail,
                "Launch the frozen build through app.frozen_main so hardened DLL search is applied.",
            )
        )

        installer_status, installer_detail, installer_path = self._installer_artifact_status()
        gates.append(
            self._gate(
                "installer_artifact",
                "Windows installer artifact",
                installer_status,
                "blocker" if installer_status == "block" else "warning",
                installer_detail,
                "Build a real PE installer with Inno Setup; never publish a placeholder with an .exe suffix.",
            )
        )
        if installer_path is not None:
            artifacts.append(
                self._artifact(
                    "windows_installer",
                    installer_path,
                    "verified" if installer_status == "pass" else "failed",
                    installer_detail,
                )
            )

        signing_status, signing_detail = self._signing_status()
        gates.append(
            self._gate(
                "authenticode",
                "Authenticode evidence",
                signing_status,
                "warning",
                signing_detail,
                "Sign and timestamp application and installer artifacts before stable publication.",
            )
        )

        vulnerability_status, vulnerability_detail = self._vulnerability_status()
        severity = "blocker" if vulnerability_status == "block" else "warning"
        gates.append(
            self._gate(
                "vulnerabilities",
                "Dependency vulnerability scan",
                vulnerability_status,
                severity,
                vulnerability_detail,
                "Run pip-audit, review advisories, update dependencies and regenerate the SBOM.",
            )
        )

        build_status, build_detail = self._build_contract_status()
        gates.append(
            self._gate(
                "build_contract",
                "Frozen build hardening",
                build_status,
                "blocker",
                build_detail,
                "Keep UPX disabled and exclude tests, package managers and development tools from the frozen build.",
            )
        )

        status = self._status(gates)
        summary = self._summary(status, gates, len(components))
        snapshot = SecuritySupplyChainSnapshot(
            captured_at=self._now(),
            status=status,
            summary=summary,
            credential_backend=self.credential_store.backend_name,
            credential_status=credential_status,
            component_count=len(components),
            vulnerability_status=vulnerability_status,
            package_path=package if package and package.exists() else None,
            gates=tuple(gates),
            artifacts=tuple(artifacts),
        )
        self._write_json(self.latest_snapshot_path, snapshot.to_dict())
        return snapshot

    def component_inventory(self, *, refresh: bool = False) -> tuple[SecurityComponent, ...]:
        if self._component_cache is not None and not refresh:
            return self._component_cache
        components: dict[str, SecurityComponent] = {
            "s-talking": SecurityComponent(
                name="s-talking",
                version=app.__version__,
                component_type="application",
                supplier="Organization: S Talking",
                license_expression="NOASSERTION",
                purl=f"pkg:pypi/s-talking@{quote(app.__version__)}",
            )
        }
        for distribution in importlib.metadata.distributions():
            metadata = distribution.metadata
            raw_name = str(metadata.get("Name") or "").strip()
            if not raw_name:
                continue
            name = re.sub(r"[-_.]+", "-", raw_name).casefold()
            if name == "s-talking":
                continue
            license_expression = str(metadata.get("License-Expression") or metadata.get("License") or "NOASSERTION")
            if len(license_expression) > 200 or "\n" in license_expression:
                license_expression = "NOASSERTION"
            supplier = str(metadata.get("Author") or metadata.get("Maintainer") or "")[:160]
            components[name] = SecurityComponent(
                name=raw_name,
                version=str(distribution.version or "UNKNOWN"),
                supplier=supplier,
                license_expression=license_expression,
                purl=f"pkg:pypi/{quote(name)}@{quote(str(distribution.version or 'UNKNOWN'))}",
            )
        self._component_cache = tuple(
            sorted(components.values(), key=lambda item: item.name.casefold())
        )
        return self._component_cache

    def generate_sbom(self) -> Path:
        components = self.component_inventory()
        created = self._now()
        packages: list[dict[str, object]] = []
        relationships: list[dict[str, str]] = []
        app_spdx = "SPDXRef-Package-S-Talking"
        for index, component in enumerate(components, 1):
            spdx_id = app_spdx if component.component_type == "application" else f"SPDXRef-Package-{index}"
            packages.append(
                {
                    "SPDXID": spdx_id,
                    "name": component.name,
                    "versionInfo": component.version,
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                    "licenseConcluded": component.license_expression,
                    "licenseDeclared": component.license_expression,
                    "supplier": component.supplier or "NOASSERTION",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": component.purl,
                        }
                    ],
                }
            )
            if spdx_id != app_spdx:
                relationships.append(
                    {
                        "spdxElementId": app_spdx,
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": spdx_id,
                    }
                )
        document = {
            "spdxVersion": self.SPDX_VERSION,
            "dataLicense": self.SPDX_DATA_LICENSE,
            "SPDXID": "SPDXRef-DOCUMENT",
            "name": f"S-Talking-{app.__version__}-SBOM",
            "documentNamespace": f"https://s-talking.invalid/spdx/{uuid.uuid4()}",
            "creationInfo": {
                "created": created,
                "creators": ["Tool: S-Talking SecuritySupplyChainService"],
            },
            "documentDescribes": [app_spdx],
            "packages": packages,
            "relationships": relationships,
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "platform": platform.platform(),
            },
        }
        path = self.sbom_dir / self.SBOM_NAME
        self._write_json(path, document)
        ok, detail = self.verify_sbom(path)
        if not ok:
            raise ValueError(detail)
        self._write_json(
            self.sbom_dir / "SBOM-result.json",
            {
                "schema_version": 1,
                "status": "verified",
                "created_at": created,
                "path": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": self._sha256(path),
                "component_count": len(components),
            },
        )
        return path

    def verify_sbom(self, path: Path) -> tuple[bool, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"SBOM is unreadable: {exc}"
        if not isinstance(payload, dict) or payload.get("spdxVersion") != self.SPDX_VERSION:
            return False, "SBOM is not an SPDX 2.3 JSON document."
        packages = payload.get("packages")
        if not isinstance(packages, list) or not packages:
            return False, "SBOM contains no packages."
        serialized = json.dumps(payload, ensure_ascii=False)
        if self._contains_secret_field(payload):
            return False, "SBOM contains a forbidden secret-related field."
        if str(self.runtime.app_root) in serialized or str(self.runtime.settings_path.parent) in serialized:
            return False, "SBOM contains a local filesystem path."
        identifiers = [str(item.get("SPDXID") or "") for item in packages if isinstance(item, dict)]
        if len(identifiers) != len(set(identifiers)) or "SPDXRef-Package-S-Talking" not in identifiers:
            return False, "SBOM package identifiers are missing or duplicated."
        return True, f"SPDX SBOM verified with {len(packages)} package(s): {self._sha256(path)[:16]}…"

    def inspect_package(self, path: Path) -> tuple[bool, str, tuple[str, ...]]:
        issues: list[str] = []
        try:
            if path.suffix.casefold() != ".zip":
                return False, "Security package audit supports ZIP artifacts only.", ("package:unsupported",)
            with zipfile.ZipFile(path) as archive:
                infos = [info for info in archive.infolist() if not info.is_dir()]
                if len(infos) > self.MAX_ZIP_ENTRIES:
                    issues.append(f"archive:entry-count:{len(infos)}")
                total_size = sum(max(0, info.file_size) for info in infos)
                if total_size > self.MAX_UNCOMPRESSED_BYTES:
                    issues.append(f"archive:uncompressed-size:{total_size}")
                seen: set[str] = set()
                normalized: dict[str, zipfile.ZipInfo] = {}
                for info in infos:
                    raw = info.filename
                    if "\\" in raw:
                        issues.append(f"path:backslash:{raw}")
                    name = raw.replace("\\", "/")
                    pure = PurePosixPath(name)
                    folded = name.casefold()
                    if folded in seen:
                        issues.append(f"path:duplicate:{name}")
                    seen.add(folded)
                    normalized[folded] = info
                    if name.startswith(("/", "\\")) or pure.is_absolute() or ".." in pure.parts:
                        issues.append(f"path:traversal:{name}")
                    if ":" in name:
                        issues.append(f"path:alternate-stream:{name}")
                    if self._zip_info_is_symlink(info):
                        issues.append(f"path:symlink:{name}")
                    for part in pure.parts:
                        stem = part.split(".", 1)[0].casefold()
                        if stem in self._WINDOWS_RESERVED:
                            issues.append(f"path:reserved:{name}")
                    folded_parts = {part.casefold() for part in pure.parts}
                    if folded_parts & self._PRIVATE_PARTS or pure.name.casefold() in self._PRIVATE_NAMES:
                        issues.append(f"privacy:private-file:{name}")
                    suffix = pure.suffix.casefold()
                    if suffix == ".dll" and "_internal" not in folded_parts:
                        issues.append(f"dll:untrusted-location:{name}")
                    if suffix == ".pyd" and "_internal" not in folded_parts:
                        issues.append(f"dll:python-extension-location:{name}")
                    if suffix == ".exe" and pure.name.casefold() != "s-talking.exe":
                        issues.append(f"executable:unexpected:{name}")
                    if suffix in self._UNSAFE_EXECUTABLE_SUFFIXES:
                        issues.append(f"executable:forbidden:{name}")
                    if info.compress_size and info.file_size > 10 * 1024**2:
                        ratio = info.file_size / max(1, info.compress_size)
                        if ratio > 1_000:
                            issues.append(f"archive:compression-ratio:{name}")
                required = {"s-talking.exe", "portable.mode", "run.cmd"}
                missing = sorted(required - set(normalized))
                issues.extend(f"package:missing:{name}" for name in missing)
                executable = normalized.get("s-talking.exe")
                if executable is not None:
                    with archive.open(executable) as handle:
                        if handle.read(2) != b"MZ":
                            issues.append("executable:not-pe:s-talking.exe")
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            return False, f"Package audit failed: {exc}", ("package:unreadable",)
        unique = tuple(dict.fromkeys(issues))
        if unique:
            return False, f"Package security audit found {len(unique)} issue(s): {unique[0]}", unique
        return True, f"Package security audit passed: {self._sha256(path)[:16]}…", ()

    def audit_package(self, path: Path) -> SecurityAuditReceipt:
        package = Path(path)
        ok, detail, issues = self.inspect_package(package)
        audit_id = f"security-{self._now_compact()}-{uuid.uuid4().hex[:8]}"
        report_path = self.audit_dir / f"{audit_id}.json"
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "audit_id": audit_id,
            "created_at": self._now(),
            "status": "verified" if ok else "blocked",
            "package": {
                "name": package.name,
                "size_bytes": package.stat().st_size if package.exists() else 0,
                "sha256": self._sha256(package) if package.exists() else "",
            },
            "detail": detail,
            "issues": list(issues),
        }
        self._write_json(report_path, payload)
        return SecurityAuditReceipt(
            audit_id=audit_id,
            created_at=str(payload["created_at"]),
            status=str(payload["status"]),
            report_path=report_path,
            sha256=self._sha256(report_path),
            package_path=package if package.exists() else None,
            issue_count=len(issues),
        )

    def verify_audit(self, report_path: Path, package_path: Path) -> tuple[bool, str]:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"Security audit report is unreadable: {exc}"
        package = Path(package_path)
        package_payload = payload.get("package") if isinstance(payload, dict) else None
        if not isinstance(package_payload, dict) or not package.exists():
            return False, "Security audit package evidence is missing."
        if package_payload.get("name") != package.name:
            return False, "Security audit package filename does not match."
        if int(package_payload.get("size_bytes") or -1) != package.stat().st_size:
            return False, "Security audit package size does not match."
        if str(package_payload.get("sha256") or "") != self._sha256(package):
            return False, "Security audit package SHA-256 does not match."
        ok, detail, issues = self.inspect_package(package)
        expected_status = "verified" if ok else "blocked"
        if str(payload.get("status") or "") != expected_status:
            return False, "Security audit status does not match a fresh package inspection."
        if list(payload.get("issues") or []) != list(issues):
            return False, "Security audit issues do not match a fresh package inspection."
        return True, detail

    def run_vulnerability_scan(self) -> Path:
        created = self._now()
        if importlib.util.find_spec("pip_audit") is None:
            payload = {
                "schema_version": 1,
                "created_at": created,
                "status": "unavailable",
                "detail": "pip-audit is not installed in this environment.",
                "vulnerabilities": [],
            }
            self._write_json(self.vulnerability_path, payload)
            return self.vulnerability_path
        command = [
            sys.executable,
            "-m",
            "pip_audit",
            "--format=json",
            "--progress-spinner=off",
        ]
        try:
            completed = self._command_runner(
                command,
                capture_output=True,
                text=True,
                timeout=240,
                check=False,
            )
            data = json.loads(completed.stdout or "{}")
            vulnerabilities = self._normalize_vulnerabilities(data)
            status = "clean" if not vulnerabilities and completed.returncode == 0 else "vulnerable" if vulnerabilities else "failed"
            payload = {
                "schema_version": 1,
                "created_at": created,
                "status": status,
                "return_code": int(completed.returncode),
                "detail": (
                    "No known dependency vulnerabilities were reported."
                    if status == "clean"
                    else f"{len(vulnerabilities)} vulnerability record(s) require review."
                    if status == "vulnerable"
                    else "pip-audit could not complete successfully."
                ),
                "vulnerabilities": vulnerabilities,
            }
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError, TypeError) as exc:
            payload = {
                "schema_version": 1,
                "created_at": created,
                "status": "failed",
                "detail": f"Vulnerability scan failed: {exc}",
                "vulnerabilities": [],
            }
        self._write_json(self.vulnerability_path, payload)
        return self.vulnerability_path

    def export_snapshot(self, package_path: Path | None = None) -> tuple[Path, Path]:
        snapshot = self.snapshot(package_path)
        stamp = self._now_compact()
        json_path = self.exports_dir / f"security-supply-chain-{stamp}.json"
        csv_path = self.exports_dir / f"security-supply-chain-{stamp}.csv"
        self._write_json(json_path, snapshot.to_dict())
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["gate_id", "label", "status", "severity", "detail", "remediation"])
            for gate in snapshot.gates:
                writer.writerow(
                    [
                        gate.gate_id,
                        gate.label,
                        gate.status,
                        gate.severity,
                        gate.detail,
                        gate.remediation,
                    ]
                )
        return json_path, csv_path

    def latest_portable_package(self) -> Path | None:
        package_root = self.runtime.artifacts_dir / "package"
        canonical = package_root / f"S-Talking-{app.__version__}-portable.zip"
        if canonical.exists():
            return canonical
        candidates = sorted(package_root.glob("S-Talking-*-portable.zip"), key=lambda item: item.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def latest_sbom_path(self) -> Path:
        return self.sbom_dir / self.SBOM_NAME

    def _runtime_hardening_status(self) -> tuple[str, str]:
        if sys.platform != "win32":
            return "not_applicable", "DLL search hardening is a Windows production control."
        if not getattr(sys, "frozen", False):
            return "not_measured", "DLL search hardening is applied by frozen_main in packaged builds."
        if os.environ.get("S_TALKING_DLL_SEARCH_HARDENED") == "1":
            return "pass", "The current process reports hardened Windows DLL search directories."
        return "block", "The frozen process did not report hardened Windows DLL search directories."

    def _installer_artifact_status(self) -> tuple[str, str, Path | None]:
        result_path = self.runtime.artifacts_dir / "package" / "installer-result.json"
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return "not_measured", "No compiled Windows installer evidence is available.", None
        raw_path = payload.get("installer_path") or payload.get("artifact_path")
        installer = Path(str(raw_path)) if raw_path else None
        if payload.get("available") is False or installer is None:
            return "not_measured", "The current distribution is portable-only; no installer is included.", None
        if not installer.exists():
            return "block", "Installer evidence points to a missing artifact.", None
        try:
            with installer.open("rb") as handle:
                header = handle.read(2)
            real_pe = (
                installer.suffix.casefold() == ".exe"
                and installer.stat().st_size >= 4096
                and header == b"MZ"
            )
        except OSError as exc:
            return "block", f"Installer artifact is unreadable: {exc}", installer
        if not real_pe:
            return "block", "Installer artifact is not a real Windows PE executable.", installer
        return "pass", f"Compiled Windows installer verified: {self._sha256(installer)[:16]}…", installer

    def _signing_status(self) -> tuple[str, str]:
        path = self.runtime.artifacts_dir / "package" / "signing-result.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return "warn", "No signing evidence is available."
        artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
        if not isinstance(artifacts, list) or not artifacts:
            return "warn", "Signing evidence contains no artifacts."
        statuses = {str(item.get("status") or "") for item in artifacts if isinstance(item, dict)}
        timestamped = all(bool(item.get("timestamped")) for item in artifacts if isinstance(item, dict) and item.get("status") == "verified")
        if statuses == {"verified"} and timestamped:
            return "pass", "All release artifacts have verified timestamped Authenticode signatures."
        if RELEASE_CHANNEL == "stable":
            return "block", "Stable release artifacts are not fully signed and timestamped."
        return "warn", "Preview artifacts are unsigned or lack durable timestamp evidence."

    def _vulnerability_status(self) -> tuple[str, str]:
        try:
            payload = json.loads(self.vulnerability_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return "warn", "No dependency vulnerability report is available."
        status = str(payload.get("status") or "unknown")
        vulnerabilities = payload.get("vulnerabilities") if isinstance(payload.get("vulnerabilities"), list) else []
        if status == "clean":
            return "pass", "The latest local vulnerability scan reported no known findings."
        if status == "vulnerable":
            high = sum(str(item.get("severity") or "unknown").casefold() in {"critical", "high"} for item in vulnerabilities if isinstance(item, dict))
            return ("block" if high else "warn"), f"The latest scan contains {len(vulnerabilities)} finding(s), including {high} high/critical finding(s)."
        return "warn", str(payload.get("detail") or "The vulnerability scan is unavailable or failed.")

    def _build_contract_status(self) -> tuple[str, str]:
        spec = self.runtime.app_root / "packaging" / "S-Talking.spec"
        try:
            text = spec.read_text(encoding="utf-8-sig")
        except OSError:
            return "block", "PyInstaller specification is missing or unreadable."
        required = (
            "upx=False",
            'excludes=["tests", "pytest", "ruff", "pip", "setuptools", "wheel"]',
            "exclude_binaries=True",
        )
        missing = [item for item in required if item not in text]
        if missing:
            return "block", "Frozen build hardening is missing: " + ", ".join(missing)
        return "pass", "UPX is disabled and development/package-management tooling is excluded from the frozen build."

    @classmethod
    def _contains_secret_field(cls, payload: object) -> bool:
        if isinstance(payload, dict):
            for key, value in payload.items():
                normalized = str(key).casefold().replace("-", "_")
                if normalized in {
                    "api_key",
                    "authorization",
                    "bearer",
                    "credential",
                    "password",
                    "secret",
                    "token",
                }:
                    return True
                if cls._contains_secret_field(value):
                    return True
        elif isinstance(payload, list):
            return any(cls._contains_secret_field(value) for value in payload)
        return False

    @classmethod
    def _normalize_vulnerabilities(cls, payload: Any) -> list[dict[str, str]]:
        dependencies = payload.get("dependencies", []) if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        findings: list[dict[str, str]] = []
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            package = str(dependency.get("name") or dependency.get("package") or "unknown")
            version = str(dependency.get("version") or "unknown")
            vulnerabilities = dependency.get("vulns") or dependency.get("vulnerabilities") or []
            for vulnerability in vulnerabilities if isinstance(vulnerabilities, list) else []:
                if not isinstance(vulnerability, dict):
                    continue
                aliases = vulnerability.get("aliases") if isinstance(vulnerability.get("aliases"), list) else []
                severity = str(vulnerability.get("severity") or "unknown")
                findings.append(
                    {
                        "package": package,
                        "version": version,
                        "id": str(vulnerability.get("id") or "unknown"),
                        "severity": severity,
                        "fix_versions": ", ".join(str(value) for value in vulnerability.get("fix_versions", []) if value),
                        "aliases": ", ".join(str(value) for value in aliases if value),
                    }
                )
        return findings

    @classmethod
    def _zip_info_is_symlink(cls, info: zipfile.ZipInfo) -> bool:
        mode = (info.external_attr >> 16) & 0xFFFF
        return stat.S_IFMT(mode) == stat.S_IFLNK

    def _artifact(self, role: str, path: Path, status: str, detail: str) -> SecurityArtifact:
        return SecurityArtifact(
            role=role,
            path=path,
            size_bytes=path.stat().st_size,
            sha256=self._sha256(path),
            status=status,
            detail=detail,
        )

    @staticmethod
    def _gate(
        gate_id: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        remediation: str,
    ) -> SecurityGate:
        return SecurityGate(gate_id, label, status, severity, detail, remediation)

    @staticmethod
    def _status(gates: Iterable[SecurityGate]) -> str:
        statuses = {gate.status for gate in gates}
        if "block" in statuses:
            return "blocked"
        if "warn" in statuses:
            return "attention"
        return "healthy"

    @staticmethod
    def _summary(status: str, gates: Iterable[SecurityGate], component_count: int) -> str:
        gate_list = tuple(gates)
        blockers = sum(gate.status == "block" for gate in gate_list)
        warnings = sum(gate.status == "warn" for gate in gate_list)
        if status == "blocked":
            return f"Security audit is blocked by {blockers} gate(s); {component_count} component(s) inventoried."
        if status == "attention":
            return f"Security audit needs attention for {warnings} warning(s); {component_count} component(s) inventoried."
        return f"Security and supply-chain controls are healthy; {component_count} component(s) inventoried."

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _now(self) -> str:
        return self._now_provider().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _now_compact(self) -> str:
        return self._now_provider().astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
