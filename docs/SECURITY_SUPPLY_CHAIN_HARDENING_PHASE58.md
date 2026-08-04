# Phase 58 — Security & Supply-Chain Hardening

Phase 58 adds production controls for credential storage, dependency inventory,
SPDX SBOM generation, vulnerability evidence, package path safety, DLL placement,
Authenticode evidence and deterministic release audits.

## Credential storage

Frozen Windows production builds use Generic Credentials in Windows Credential
Manager. Existing DPAPI `.cred` files are migrated on first successful read and
then overwritten and deleted on a best-effort basis. Source-mode Windows runs use
isolated DPAPI-protected files so tests and development profiles do not persist in
the operating-system credential vault. Non-Windows source-mode development keeps
an explicitly degraded per-user fallback; it is never described as production
encryption.

Credential values are never copied into SBOMs, snapshots, package audits or
security exports.

## Package controls

Portable ZIP audits reject:

- absolute paths, `..`, backslashes and NTFS alternate data streams;
- duplicate case-insensitive names;
- symlinks and Windows reserved device names;
- settings, profile metadata, credentials, databases, logs, cache, reports,
  generated output and `S-Talking-Data`;
- arbitrary executables and script payloads;
- DLL or `.pyd` files outside `_internal`;
- missing or non-PE `S-Talking.exe`;
- suspicious archive entry counts, expanded size or compression ratios.

Windows frozen startup calls `SetDefaultDllDirectories` before PySide6 is loaded
and allows DLL directories only for the application and `_internal` roots.

## SPDX SBOM

`Reports → Security & Supply Chain` can generate and verify:

```text
artifacts/security-supply-chain/sbom/S-Talking-SBOM.spdx.json
```

The document records package names, versions, declared license metadata, purls,
Python version and platform. It excludes local paths, environment variables,
settings values and secret-related fields.

## Vulnerability evidence

The optional scan uses the already-installed `pip-audit` module. Phase 58 never
installs tools or dependencies during the audit. Missing tooling is a warning;
high or critical findings block release readiness.

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\security-audit.ps1 `
  -GenerateSbom `
  -ScanVulnerabilities `
  -AuditPackage .\artifacts\package\S-Talking-0.18.2-rc1-portable.zip `
  -Export
```

## Frozen CLI

```text
--security-snapshot
--generate-sbom
--security-audit-package <zip>
--security-vulnerability-scan
--security-export
```

No database migration is introduced. Database schema remains 22.
