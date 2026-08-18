# Roadmap 2 B6 Hotfix 3 / Hotfix 9 — A9.1 Hotfix 1

## Historical heading-geometry contract reconciliation

This continuation is **test-contract only**. It does not modify production or runtime source.

The H9/H6 geometry chain intentionally tightened the queue-heading layout from the historical A9.1 `(12, 8, 10, 8)` margins / `8px` spacing to `(12, 5, 10, 5)` / `6px`. That tighter heading band is part of the later certified vertical-rhythm authority that keeps the launch-to-summary envelope at `<=220px` while preserving the 46px historical heading-height contract.

Phase89 Hotfix 1 proved the runtime chain through H9/H6/H5/H4/H3/H2/H1 is healthy. The remaining A9.1 failure was therefore a stale literal implementation expectation, not a product regression.

This continuation updates only `tests/test_soft_professional_visual_alignment_roadmap2_a91.py` so every density/responsive assertion follows the current H9 geometry authority. It preserves:

- Soft Professional as the selected visual direction.
- System / Light / Dark theme certification.
- 46px queue-heading contract and compact 34px controls.
- `<=220px` launch-to-summary envelope.
- Structural Workflow / Batch / Range disclosure composition.
- Provider, routing, Preflight, Generation, credential, portable and database authority.
- Track A frozen behavior and Database Schema 23.
