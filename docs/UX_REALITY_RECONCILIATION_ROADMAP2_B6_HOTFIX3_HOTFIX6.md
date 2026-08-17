# Roadmap 2 B6 Hotfix 3 — Hotfix 6

## Manual Visual Acceptance Reconciliation

Hotfix 5 completed the automated B6 Hotfix 3 chain, but the required manual
review of the generated screenshots found two remaining presentation defects:

1. exact legacy navy colors were still painted by child widgets even though
   their structural parents had already moved to the Soft Professional dark
   palette; and
2. a small set of primary actions still used the historical `#2563EB` brand
   blue instead of the selected Soft Professional primary.

The leak is caused by the historical global `QWidget`/object-specific rules
having higher specificity than parent-only reconciliation selectors.  Hotfix 6
adds a final object-specific presentation layer, makes passive labels
transparent inside semantic structural hosts, gives Provider Accounts runtime
hosts explicit object names, and restyles the Provider Accounts table/header
with semantic surfaces.

The certification script now performs a pixel audit.  Exact legacy structural
navy colors must occupy less than 1% of either Dark screenshot, and the legacy
Light primary `#2563EB` must occupy less than 0.2% of the Light main screenshot.
This converts the manual defect into a repeatable certification boundary.

No provider/account/voice/model/language selection authority, Preflight,
Generation, Smart Routing, failover, credential storage, portable runtime or
database schema behavior is changed.
