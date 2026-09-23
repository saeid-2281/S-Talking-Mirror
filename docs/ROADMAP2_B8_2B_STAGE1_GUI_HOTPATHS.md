# Roadmap 2 / B8.2B — Stage 1: GUI hot-path isolation

B7 frozen baseline `bcfcca70eb135f4caf526e09b7dea5448368ca0f` remains untouched.
This scoped stage uses B8.2A baseline `db4307efebb48e8f70604a8db76d02331d2d3ecc`.

Observed trace: repeated costly Smart Routing provider construction and Git status
queries during startup/project/queue transitions. This stage keeps Smart Routing
informational, never applies a provider or starts a job automatically.

- Smart Routing analysis for regular GUI refreshes runs in a daemon worker;
  Qt receives the result on the GUI thread. Pending refreshes coalesce; stale
  results cannot overwrite a newer provider/project context.
- The existing explicit manual `Apply` action still resolves synchronously before
  applying the user-selected recommendation. The deterministic test fast path
  remains synchronous, preserving existing source and UI contracts.
- An ordinary status-bar repaint no longer synchronously re-probes all providers.
  Actual provider, settings and connection changes still request a refresh.
- Packaged runtime health checks do not spawn Git subprocesses: Git/CI state is
  not applicable for installed or frozen Portable binaries. Source-checkout
  health keeps its existing Git inspection.

This stage does NOT claim resolution of the 7+ minute per-job database stalls or
110-second final receipt hash; those require separate lifetime-safe persistence
and receipt workers and must be verified with a large real-world queue. Reuse
Piper from existing B8.2A diagnostic Portable and keep B7 unchanged.

Acceptance: Ruff + dedicated tests + targeted regressions + full quality gate;
commit/push B8-only; build separate TRUE Portable from pushed source; migrated
Piper/provider-account checks; repeat B8.1 heartbeat and B8.2A trace manually.
