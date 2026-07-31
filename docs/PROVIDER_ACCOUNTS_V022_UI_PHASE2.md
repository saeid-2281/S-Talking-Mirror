# Provider Accounts 2.0 — UI Phase 2

- Displays account-scoped catalog freshness, voice count, model count, and saved timestamp.
- Reads only snapshots matching provider, profile id, and API-key fingerprint.
- Removes obsolete snapshots when a profile key is replaced or the profile is deleted.
- Keeps remote refresh scoped to the selected account.
