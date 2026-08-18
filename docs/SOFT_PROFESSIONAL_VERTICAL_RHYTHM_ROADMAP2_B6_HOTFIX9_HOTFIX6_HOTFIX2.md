# Roadmap 2 B6 Hotfix 3 — Hotfix 9 / Hotfix 6 / Hotfix 2

## Bounded Queue Chrome Height Authority

The H6 Hotfix 1 run proved the canonical disclosure chain itself is healthy:
H2 repaired, H6 4/4, H5 5/5, H4 5/5, H3 4/4 and H1 3/3 all passed. The remaining H9 failure was the cumulative launch-to-summary envelope (293px versus <=220px), while the heading-to-command gap already passed.

The fixed chrome host introduced in H5 was still using `QVBoxLayout.sizeHint()` as its locking authority. On the Windows Qt path that hint can retain the envelope of an earlier taller disclosure composition. A fixed host can therefore stay taller than its currently attached bounded rows and Qt redistributes that surplus as dead space later in the chrome.

This continuation changes only presentation geometry. `QueueWorkspace.chrome_content_height()` measures currently attached, visible chrome widgets and clamps every widget hint to its explicit minimum/maximum height. `sync_chrome_height()` releases any previous host lock, measures that bounded visible composition, and then fixes the host to that exact height.

The historical H5 regression and H9 certifier are reconciled to use the bounded content metric rather than the stale generic layout size hint. The original <=220px H9 envelope remains unchanged and gains an explicit Command-to-Summary <=8px check.

Provider/account selection, target language authority, Preflight, Generation, routing/failover, credential storage, portable-data semantics and database schema 23 are unchanged.
