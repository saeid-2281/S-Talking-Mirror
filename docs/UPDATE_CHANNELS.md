# S-Talking Update Channels

## Preview

For release candidates, QA and limited internal rollout. Prerelease versions are allowed. Start with a low rollout percentage when validating new packaging or migration behavior.

## Beta

For broader prerelease testing after preview verification. Prerelease versions are allowed, but artifacts must still pass all mandatory final-release integrity and privacy gates.

## Stable

For production releases. Versions containing a prerelease suffix such as `-rc1`, `-beta` or `-preview` are rejected.

## Feed contract

Each channel publishes a JSON feed with:

- schema version;
- product and application version;
- update channel and rollout percentage;
- publication timestamp;
- minimum supported version;
- critical-update flag;
- portable and optional installer metadata;
- safe relative URL, size, SHA-256 and signature status for each artifact.

The feed is accompanied by a SHA-256 digest. Downloaded artifacts must be hash-verified before they are used. Installer and executable Authenticode status is recorded separately and can be made mandatory by the release command.

## Application delivery client

Phase 55 adds a user-controlled delivery client inside **Reports → Update Delivery**.

- Update checks are disabled or enabled by an explicit preference.
- Startup checks are optional and respect a configurable interval.
- Remote feeds and artifacts require HTTPS; local verified feeds remain supported for QA.
- `latest.json` must be accompanied by `latest.sha256`.
- Bundle feeds use `update-feed.sha256`.
- Release notes must be embedded in the verified feed or referenced by a safe relative filename and SHA-256.
- Staged rollout assignment is deterministic for one local client identity, channel and version.
- A download is written to a temporary `.partial` file and moved into place only after exact size and SHA-256 verification.
- A Windows installer advertised as signed is checked again with Windows Authenticode after download.
- The application never launches an installer, extracts a portable package, restarts, or closes itself automatically.
- An installer plan is exposed only after the downloaded file passes the required verification gates.
