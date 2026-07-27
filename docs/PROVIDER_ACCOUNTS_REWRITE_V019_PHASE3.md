# Provider Accounts Rewrite v0.19 — Phase 3

This phase turns the selected-account inspector into a structured production panel and fixes the refresh lifecycle that could immediately discard a newly fetched account catalog.

## Account details

The right-side inspector now contains separate identity, quota, catalog, and metadata cards. It exposes account status, active state, remaining quota, voice/model counts, credential state, provider, last check time, and the timestamp of the account-specific catalog snapshot.

## Refresh lifecycle

`Refresh catalog` invalidates only the selected account snapshot, performs a forced remote refresh, stores the resulting catalog timestamp/profile identity, and then refreshes the UI without clearing the newly populated cache. Normal `Test` actions continue to reuse the short-lived account-specific cache.

## Interaction feedback

While a test is in progress, the selected profile enters `TESTING`, the details card updates immediately, and the event loop is allowed to repaint before the provider request runs.

## Compatibility

The existing accounts table, Accounts/Failover tabs, splitter, profile CRUD actions, failover settings, and public widget attributes used by existing tests remain available.
