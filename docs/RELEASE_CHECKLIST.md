# Release Checklist

## Identity

- Version is `0.18.2-rc1`.
- Release channel is `rc`.
- Runtime information, diagnostics, reports, Health Center, installer metadata, and `pyproject.toml` use the shared version.

## Checks

- Run `.\scripts\release-check.ps1`.
- Confirm compileall, pytest, Ruff, database smoke, CSV smoke, preflight smoke, report smoke, diagnostics redaction smoke, and import smoke pass.
- Build and verify the release candidate with `.\scripts\release-candidate.ps1`.

## Manual Verification

- Launch with no project.
- Launch with last project restore.
- Open the production project with `input.repaired.csv`.
- Confirm 4,212 valid rows and 0 rejected rows.
- Run Mock preflight and a short generation.
- Test stop/resume/retry.
- Open Voice Browser saved previews.
- Test ElevenLabs connection.
- Close the app with dialogs and audio open.
- Launch the portable package.

## Packaging

- Run `.\scripts\build.ps1`.
- Confirm the portable ZIP exists under `artifacts\package`.
- When Inno Setup is installed, confirm `installer-result.json` marks a real `MZ` installer as available and distributable.
- When Inno Setup is missing, confirm only `S-Talking-<version>-installer-unavailable.txt` is produced—never a fake `.exe`.
- Confirm secrets, reports, output, databases, caches, logs, tests, and virtual environments are excluded.

## Upgrade and Distribution

- Confirm the installer uses the stable AppId and `%LOCALAPPDATA%\Programs\S Talking`.
- Confirm uninstall does not remove `%LOCALAPPDATA%\S-Talking` user data.
- Back up `%LOCALAPPDATA%\S-Talking` and test an in-place upgrade from the previous verified build.
- Verify existing settings, credentials, projects, queue state, reports, and output paths after upgrade.
- Test rollback with a disposable application-data copy.
- Run `.\scripts\distribution-candidate.ps1`; use `-RequireInstaller` for installer-mandatory publication.
- Verify `distribution-manifest.json`, `upgrade-plan.json`, `ROLLBACK.md`, and `SHA256SUMS.txt`.

## Generation Monitor Pro v1.0 hardening

- [ ] Schema migrations 1–22 are applied without gaps.
- [ ] Database quick check passes.
- [ ] Foreign-key check has no violations.
- [ ] A verified backup and SHA-256 manifest are created.
- [ ] Restore is tested against a disposable copy.
- [ ] Retention preview contains only expected records.
- [ ] Incident-linked sessions are preserved by retention.
- [ ] Full Quality Gate passes after Phase 55.

## Signing and Update Channel

- Configure `S_TALKING_SIGN_CERT_THUMBPRINT` with a code-signing certificate in the Windows certificate store.
- Configure `S_TALKING_TIMESTAMP_URL` for timestamped Authenticode signatures.
- Use `S_TALKING_SIGNTOOL_PATH` only when SignTool is not discoverable from PATH or the Windows SDK.
- Run `scripts/build.ps1 -RequireSigning` and confirm `signing-result.json` verifies both `application_executable` and `windows_installer`.
- Run `scripts/final-release.ps1 -RequireInstaller -RequireSigning -Channel preview`.
- Verify `final-release-manifest.json`, `S-Talking-preview.json`, `update-feed.sha256`, and final `SHA256SUMS.txt`.
- Confirm prerelease versions cannot be published to the stable channel.
- Confirm update URLs are safe relative filenames and downloaded artifacts match SHA-256 before publication.

## Upgrade and recovery validation

- [ ] Run `scripts/upgrade-validation.ps1 -CreateBackup -ValidateMigration`.
- [ ] Confirm the backup manifest verifies and the disposable database reaches schema 22.
- [ ] Test portable-to-installed preservation with a copied portable data directory.
- [ ] Confirm a newer unsupported schema is blocked.
- [ ] Review the dry-run restore plan; perform an actual restore only while S Talking is closed.
- [ ] Verify an existing project and one mock-provider output after upgrade or recovery.

## Update delivery client

- [ ] Publish `latest.json` and `latest.sha256` for each enabled channel.
- [ ] Confirm the feed product is `S Talking` and the channel matches the configured client channel.
- [ ] Confirm release notes are copied beside the published feed and match `release_notes_sha256`.
- [ ] Test one client inside and one client outside a staged rollout assignment.
- [ ] Confirm a tampered feed, unsafe relative URL, wrong channel, invalid artifact size, or wrong SHA-256 is blocked.
- [ ] Confirm a verified portable ZIP downloads without extraction or restart.
- [ ] Confirm a signed installer is rechecked with Authenticode and is never launched automatically.
- [ ] Confirm disabling update checks prevents startup network access.
- [ ] Review the exported update-check snapshot and download receipt for secret-free metadata.

## Phase 56 crash-recovery checks

- [ ] Unhandled Python and thread exceptions create integrity-protected structured reports.
- [ ] Qt critical/fatal capture is installed only during production startup.
- [ ] Normal window close removes the active-session marker.
- [ ] A stale marker is reported as an unclean prior shutdown.
- [ ] `--safe-mode` skips automatic project/session restore, generation recovery prompts and startup update checks.
- [ ] Diagnostics bundles verify every included artifact against the internal manifest.
- [ ] Bundles contain no settings, API profiles, credentials, databases, project sources or generated audio.
- [ ] Report tampering blocks acknowledgement and marks recovery status as blocked.
- [ ] Database quick check remains read-only.
