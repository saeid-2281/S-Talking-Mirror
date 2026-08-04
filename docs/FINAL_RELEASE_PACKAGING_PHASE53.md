# Phase 53 — Signed Installer, Update Channel & Final Release Packaging

Phase 53 turns the verified Phase 52 distribution candidate into a final release bundle with explicit Authenticode evidence and deterministic update-channel metadata.

## Release modes

- `preview`: release candidates and internal staged rollout.
- `beta`: wider prerelease rollout.
- `stable`: production releases only; prerelease version suffixes are blocked.

Rollout percentages are restricted to 1–100. Update artifact URLs are safe relative filenames so publishing infrastructure can choose the final base URL without modifying signed or checksummed metadata.

## Code signing

`scripts/build.ps1` supports Microsoft SignTool with a certificate already installed in the Windows certificate store:

```powershell
$env:S_TALKING_SIGN_CERT_THUMBPRINT = "CERTIFICATE_THUMBPRINT"
$env:S_TALKING_TIMESTAMP_URL = "https://your-rfc3161-timestamp-service"
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1 -RequireSigning
```

Optional SignTool override:

```powershell
$env:S_TALKING_SIGNTOOL_PATH = "C:\Path\To\signtool.exe"
```

The build does not accept a PFX password on the command line. This avoids exposing certificate passwords in process listings and logs. Certificate private keys remain in the Windows certificate store.

The build records only public evidence in `artifacts/package/signing-result.json`: role, file path, SHA-256, status, certificate subject, thumbprint and timestamp presence. No private key or password is written.

## Final release command

Portable final release with warning status when signatures or installer are unavailable:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\final-release.ps1 -Channel preview
```

Strict signed release:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\final-release.ps1 `
  -BuildPackages `
  -RequireInstaller `
  -RequireSigning `
  -Channel preview
```

## Outputs

Final bundles are written under:

```text
artifacts/final-release/S-Talking-<version>-<channel>-<timestamp>/
```

The latest verified bundle is copied to:

```text
artifacts/final-release/latest/
```

The latest channel feed and digest are published to:

```text
artifacts/update-channel/<channel>/latest.json
artifacts/update-channel/<channel>/latest.sha256
```

The update feed contains version, channel, rollout percentage, release time, minimum supported version, relative artifact URLs, SHA-256 values and signature status. Phase 55 will consume this contract for interactive update discovery and download verification.

## Safety guarantees

- Stable channel rejects prerelease version suffixes.
- Final manifests and update feeds are verified before publishing `latest`.
- Tampered files fail SHA-256 verification.
- Update URLs must be safe relative filenames.
- Credentials, settings, databases, logs, reports and generated outputs are blocked.
- Strict mode requires both application and installer Authenticode evidence.
- Database schema remains 22.
