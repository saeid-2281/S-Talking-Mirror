# Phase 55 — Update Channels and Release Delivery

## Goal

Deliver verified release metadata and artifacts to the desktop application while preserving explicit user control. This phase does not implement unattended installation or automatic restart.

## User workflow

1. Open **Reports → Update Delivery**.
2. Enable checks, select `preview`, `beta`, or `stable`, and configure an HTTPS feed or a local QA feed.
3. Run **Check now**.
4. Review feed integrity, version policy, staged rollout, artifact metadata, and release notes.
5. Download the selected artifact.
6. Review or copy the install plan. The user must still launch an installer or extract a portable package manually.

## Security gates

- HTTPS-only remote metadata and artifact delivery.
- Feed SHA-256 verification before JSON is trusted.
- Product and channel identity validation.
- Stable-channel prerelease rejection.
- Safe relative artifact and release-note filenames.
- Exact artifact size and SHA-256 verification.
- Local Authenticode verification for installers advertised as signed.
- Partial-download cleanup after every failure.
- No credential, project source, API profile, or generated audio content in snapshots or receipts.

## Staged rollout

A private random client identifier is stored in the settings directory. The rollout bucket is derived from SHA-256 over client ID, channel, and version. The identifier is not published in reports. Critical updates may bypass staged rollout assignment, but still require all integrity gates.

## Persistence

- `update-delivery.json`: user preferences.
- `update-delivery-state.json`: last check time and status.
- `update-client-id.txt`: opaque local rollout identifier.
- `cache/updates/<channel>/<version>/`: verified downloaded artifacts.
- `artifacts/update-delivery/`: secret-free check snapshots and download receipts.

## Non-goals

- No silent installation.
- No automatic application shutdown.
- No automatic restart.
- No background download.
- No bypass for failed hashes, unsafe URLs, channel mismatches, or invalid signatures.
- No database migration; schema remains 22.
