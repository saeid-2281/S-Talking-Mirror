# Release Checklist

## Identity

- Version is `1.0.0`.
- Release channel is `stable`.
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
- [ ] Full Quality Gate passes after Phase 61.

## Signing and Update Channel

- Configure `S_TALKING_SIGN_CERT_THUMBPRINT` with a code-signing certificate in the Windows certificate store.
- Configure `S_TALKING_TIMESTAMP_URL` for timestamped Authenticode signatures.
- Use `S_TALKING_SIGNTOOL_PATH` only when SignTool is not discoverable from PATH or the Windows SDK.
- Run `scripts/build.ps1 -RequireSigning` and confirm `signing-result.json` verifies both `application_executable` and `windows_installer`.
- Run `scripts/final-release.ps1 -RequireInstaller -RequireSigning -Channel stable`.
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

## Phase 57 — Performance and long-run stability

- [ ] Reports → Performance & Stability opens and displays seven budget gates.
- [ ] Startup readiness is marked after the first event-loop turn without delaying the window.
- [ ] Background sampling interval is at least 15 seconds and retained history is bounded.
- [ ] A manual observation records start/end/peak RSS and MB/hour growth.
- [ ] `scripts/performance-soak.ps1 -Quick -Export` completes successfully.
- [ ] Performance evidence contains no project text, filenames, API profiles, credentials, database rows or generated audio.
- [ ] Active observations are finished as `interrupted` during application shutdown.
- [ ] Full pytest, Ruff and Quality Gate pass.
- [ ] Database schema remains 22.

## Phase 58 security and supply-chain gate

- [ ] `Reports → Security & Supply Chain` has no blocker gates.
- [ ] Windows production credentials report `windows-credential-manager`.
- [ ] The SPDX 2.3 SBOM is generated and verified.
- [ ] The current portable ZIP passes path, privacy, PE and DLL-layout audits.
- [ ] The latest vulnerability report is reviewed; high/critical findings are zero.
- [ ] Stable application and installer artifacts are signed and timestamped.
- [ ] Frozen startup reports hardened DLL search directories.
- [ ] Security JSON/CSV exports contain no local paths or secret values.

## Phase 59 — UX, accessibility and theme certification

- [ ] Run `scripts/ux-certification.ps1 -Export`.
- [ ] Confirm Dark, Graphite and Light theme contrast gates pass.
- [ ] Confirm selected-row text is readable in every certified theme.
- [ ] Confirm all seven Ctrl+number workspace focus routes and F6 cycling work.
- [ ] Confirm icon-only controls expose accessible names or tooltips.
- [ ] Confirm 100%, 125%, 150% and 200% display profiles remain scroll-safe.
- [ ] Review shortcut conflicts and target-size warnings.
- [ ] Store the generated JSON and CSV evidence with release artifacts.

## Phase 60 — Production certification

- Run `scripts/production-certification.ps1 -TargetVersion 1.0.0 -ExpectedTests 850` from the exact clean commit intended for promotion.
- Require zero production-certification blockers.
- Verify `artifacts/production-certification/production-release-attestation.json` before preparing a promotion plan.
- Treat preview/beta channel evidence as an explicit warning; promotion to stable remains manual.
- Never edit the version, create a tag, publish an update feed or upload artifacts from the certification command.
- After approval, perform the version/channel change in a separate reviewed commit and rebuild every distributable artifact from that commit.


## Phase 61 — Stable 1.0 promotion

- [ ] Confirm `app.release`, `pyproject.toml`, Inno Setup defaults and Windows version metadata all identify `1.0.0`/`stable`.
- [ ] Confirm the stable promotion commit directly follows the verified Phase 60 attested commit.
- [ ] Run `scripts/stable-release.ps1` without acknowledgement and review the dry-run preflight.
- [ ] Run `scripts/stable-release.ps1 -AcknowledgePromotion -BuildPackages` to create the rollback point, build local artifacts and write the verified promotion receipt.
- [ ] Use `-RequireInstaller -RequireSigning` when stable publication requires a compiled, signed and timestamped installer.
- [ ] Verify the stable final manifest, stable `latest.json`, feed digest, portable ZIP, installer when present and SPDX SBOM.
- [ ] Confirm the promotion receipt records `automatic_tag=false`, `automatic_push=false`, `automatic_publish=false` and `automatic_install=false`.
- [ ] Keep Git tag creation, push, release upload and rollout activation as separate human-controlled operations.
