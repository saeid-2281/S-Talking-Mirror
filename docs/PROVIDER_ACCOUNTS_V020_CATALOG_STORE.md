# Provider Accounts 2.0 — Account Catalog Store

Provider voice/model catalogs are now persisted as account-scoped snapshots.

- Cache identity includes provider, profile ID, and a one-way credential fingerprint.
- Raw API keys are never written to disk.
- Each account owns its own model, voice, quota, and refresh timestamp snapshot.
- An explicit refresh invalidates only the selected account.
- A changed key cannot reuse a snapshot created by an older key.
- Corrupt, incompatible, and expired snapshots are ignored safely.

This is the first infrastructure slice of Provider Accounts 2.0. It removes the
remaining process-only catalog cache dependency and prevents account A from
showing account B's catalog after an application restart.
