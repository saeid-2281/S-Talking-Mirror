# Voice Browser Pro v1.0 — Phase 4

Adds account-scoped provider catalog background sync and diagnostics.

- Refresh keeps the current catalog visible while the remote request runs.
- Cancel is logical: late provider responses are ignored safely.
- Request identities prevent a slow older refresh from replacing a newer account catalog.
- Diagnostics show provider/profile, cache state, counts, quota, snapshot timestamps, latency, and the last error.
- Existing direct `_catalog_loaded(catalog)` calls remain supported during migration.
