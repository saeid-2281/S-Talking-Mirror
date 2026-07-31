# Phase C compatibility fix

This follow-up keeps the established workspace contracts intact while retaining
the new product centers.

- The right inspector remains exactly `Selected Row` and `Generation Monitor`.
- Notification Center is now an independent hideable dock.
- The top-level activity area remains exactly `Activity`, `Output`, and `Errors`.
- Activity Timeline is embedded inside the Activity workspace.
- Tests use per-test INI-backed QSettings storage instead of the Windows
  registry, preventing access-denied cleanup warnings.
