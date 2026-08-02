# Generation Launch Receipts, Integrity & Audit UX — Phase 36

Phase 36 turns the launch receipt introduced in Phase 35 into a usable audit workflow.

## Capabilities

- New launch receipts use schema version 2 and include a deterministic SHA-256 integrity digest.
- Existing schema version 1 receipts remain readable and are labeled as legacy.
- Modified receipts are detected as integrity mismatches; malformed JSON remains visible as unreadable instead of breaking the archive.
- The new Generation Launch Receipts dialog supports current-project, provider, risk, integrity and text filters.
- Summary metrics expose verified, legacy, integrity-issue and high-risk counts.
- Operators can open JSON, Markdown or output paths, copy receipt paths or fingerprints, and export a secret-free JSON/CSV catalog.
- Reports menu, toolbar overflow, command palette and notification routing expose the new audit center.

## Compatibility

- No database migration is required.
- Phase 35 receipt paths and filenames are preserved.
- Legacy receipts are not rewritten or deleted.
- API keys and credential values remain excluded from receipts and catalog exports.
