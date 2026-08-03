# Phase 50 — Release Candidate & Production Readiness

Phase 50 closes the current S-Talking roadmap by turning release readiness into a reproducible, auditable release-candidate workflow.

## Release gates

The Release Candidate Center evaluates:

- clean Git working tree;
- version consistency between runtime metadata and `pyproject.toml`;
- supported release channel;
- compileall, Ruff, full pytest, and release-smoke results;
- portable package availability;
- ZIP structure, corruption, path traversal, credential files, runtime data, caches, databases, and generated audio.

A candidate is reported as `ready`, `ready_with_warnings`, or `blocked`.

## Candidate artifacts

A successful build creates:

- the portable source package;
- `release-candidate-manifest.json`;
- `SHA256SUMS.txt`;
- `RELEASE-NOTES.md`;
- `release-candidate-result.json`.

Artifacts are published under `artifacts/release-candidate/` with a verified copy in `latest/`.

## Privacy and safety

The portable package excludes local settings, API profiles, workspace profiles, credentials, databases, reports, outputs, caches, generated audio, and development environments. The verifier rejects unsafe relative paths and forbidden files before a candidate can become ready.

## Operator workflow

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\release-candidate.ps1
```

The script runs release checks, builds the portable package, creates the manifest and checksums, and fails if any release blocker remains.

The same workflow is available from `Reports → Release Candidate`.

## Release completion checklist

1. Run the full Quality Gate.
2. Commit and push Phase 50.
3. Run `scripts/release-candidate.ps1` from a clean working tree.
4. Verify the manifest in the Release Candidate Center.
5. Perform clean-install, upgrade, and rollback checks on the target Windows environment.
6. Create the release tag only after all candidate evidence is archived.

Database schema remains version 22.
