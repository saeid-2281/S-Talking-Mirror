# Phase 61 — Production Promotion & Stable 1.0 Release

Phase 61 promotes the reviewed source identity from `0.18.2-rc1`/`rc` to `1.0.0`/`stable` and adds a human-controlled workflow for rollback evidence, local package construction, stable update-feed verification, SPDX SBOM verification, and a tamper-evident promotion receipt.

## Safety boundary

The stable-promotion service and script never perform any of the following automatically:

- create or push a Git tag;
- push a commit;
- upload a release or update feed;
- activate a remote rollout;
- launch an installer;
- install an update;
- restart S Talking;
- delete the previous preview feed or upgrade backup.

A verified receipt means the local artifacts are internally consistent and eligible for a separate human publication decision. It does not mean that anything has been uploaded.

## Source identity

The stable promotion requires all of these identities to agree:

- `app/release.py`: `VERSION = "1.0.0"`, `RELEASE_CHANNEL = "stable"`;
- `pyproject.toml`: `version = "1.0.0"`;
- Inno Setup defaults: `1.0.0` and `S-Talking-1.0.0-setup`;
- Windows executable metadata: file and product version `1.0.0`;
- the Phase 60 production attestation target: `1.0.0`.

The stable promotion commit must directly follow the source commit recorded in the verified Phase 60 attestation. This prevents unrelated commits from being silently inserted between certification and promotion.

## User interface

Open:

```text
Reports → Stable Release Promotion
```

The workspace provides:

- source and attestation preflight;
- stable rollout selection;
- optional strict installer policy;
- optional strict Authenticode/timestamp policy;
- rollback-point preparation;
- stable artifact verification;
- promotion-receipt creation and verification.

Explicit acknowledgement is required before a rollback point or promotion receipt is written.

## Command-line preflight

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\stable-release.ps1
```

The first run is a dry run. It verifies stable identity, attestation integrity, commit lineage, clean working tree, packaging metadata, and rollout policy. It writes no rollback point and builds no package.

## Build and locally certify stable artifacts

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\stable-release.ps1 `
  -AcknowledgePromotion `
  -BuildPackages `
  -RolloutPercentage 100
```

The script:

1. runs the full release check unless `-SkipReleaseCheck` is explicitly supplied;
2. verifies the Phase 60 attestation;
3. confirms the stable commit directly follows the attested commit;
4. creates and verifies a rollback point;
5. invokes the existing package, distribution, and final-release pipelines;
6. creates the local `stable` update feed;
7. verifies the final manifest, feed digest, downloadable artifacts, and SPDX 2.3 SBOM;
8. writes and verifies a tamper-evident promotion receipt.

Strict installer and signing publication:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\stable-release.ps1 `
  -AcknowledgePromotion `
  -BuildPackages `
  -RequireInstaller `
  -RequireSigning
```

Without the strict switches, a portable-only or unsigned local build remains `ready_with_warnings`. With either strict switch, the missing requirement becomes a blocker.

## Evidence

```text
artifacts/stable-promotion/
  stable-release-command-result.json
  stable-release-rollback-manifest.json
  stable-release-promotion-receipt.json
  rollback-points/
  receipts/
```

The rollback point may include:

- the verified Phase 60 attestation;
- the stable `app/release.py` identity file;
- the previous preview update feed and digest when available;
- the verified upgrade-backup manifest when available.

Every rollback artifact is recorded with size and SHA-256. Tampering, missing files, path traversal, or unsafe filenames fail verification.

The promotion receipt records:

- stable version and channel;
- stable source commit and attested parent commit;
- rollout percentage;
- production-attestation digest;
- rollback-manifest digest;
- final-release-manifest digest;
- stable-feed digest;
- SPDX-SBOM digest;
- warning count;
- the manual-publication contract.

Receipt paths are relative to the application root; local usernames and absolute workspace paths are not exported.

## Direct CLI contracts

```text
--stable-promotion-snapshot
--stable-promotion-verify-artifacts
--prepare-stable-rollback
--write-stable-promotion-receipt
--verify-stable-promotion-receipt <path>
--verify-stable-rollback <path>
--acknowledge-stable-promotion
--production-attestation <path>
--rollback-manifest <path>
--stable-rollout <1-100>
--require-stable-installer
--require-stable-signatures
```

## Publication after local verification

Git tag creation, Git push, release upload, stable-feed upload, and rollout activation remain manual actions outside Phase 61. Before any publication, compare the uploaded artifact hashes with the verified local promotion receipt and preserve the rollback point.

## Validation

Dedicated Phase 61 tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/test_stable_release_promotion_phase61.py
```

Expected result:

```text
9 passed
```

Expected full suite after Phase 61:

```text
859 passed, 1 skipped
```

Then run:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\quality-gate.ps1 `
  -Full
```
