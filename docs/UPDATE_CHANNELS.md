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
