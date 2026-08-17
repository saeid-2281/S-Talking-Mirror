# Roadmap 2 B6 Hotfix 3 — Hotfix 7

## Main-shell legacy surface drain

Hotfix 6 correctly removed the Provider Accounts legacy navy table family, but its
pixel-level certification failed closed because the main shell still contained
10.0160% exact legacy dark structural colors and the Light screenshot still
contained 0.3387% of the historical `#2563EB` primary.

The remaining dark leakage comes from higher-specificity historical selectors on
main-shell structural widgets (metric pills, generation action bar, provider
summary/intelligence cards, collapsed activity chrome and status chrome). The
remaining Light primary leakage comes from historical ID/property selectors such
as queue, inspector, source, monitor and audio primary actions which outrank the
generic Hotfix 6 property selector.

Hotfix 7 is presentation-only. It:

- maps the remaining main-shell structural hosts to the selected Soft Professional
  canvas/surface/surface-secondary hierarchy;
- makes passive child labels transparent where the structural parent owns the
  surface;
- explicitly maps the historical high-specificity primary action selectors to
  the selected concept primary/hover colors;
- preserves semantic success/warning/error/info colors;
- keeps Provider Accounts Hotfix 6 surfaces intact;
- extends screenshot certification with per-color sampled counts and bounding
  boxes so any future exact-color leakage is locatable from `certification.json`;
- preserves provider/account/voice/model/language authority, Preflight,
  Generation, Smart Routing, credentials, portable behavior and database schema
  23.

Acceptance thresholds remain unchanged: legacy dark structural colors below 1%
in both dark screenshots, and historical `#2563EB` below 0.2% in Light Main.
