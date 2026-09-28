# Roadmap 2 / B8.2B Stage 3B-3 — Queue header theme performance

## Evidence

Runtime attribution with a representative 4,212-row model/view queue isolated the dominant live-theme stall to `QueueTableView` while Qt repolished the global application stylesheet. The table used five `QHeaderView.ResizeToContents` compact columns. Freezing those five sections at their current pixel widths reduced the measured global QSS path from roughly 18.8 seconds to roughly 1.1 seconds while manual visual, popup, focus/state and queue-width checks remained correct.

A follow-up experiment kept `ResizeToContents` but reduced `resizeContentsPrecision` from 1000 to 32. That preserved appearance but still measured about 1.8 seconds, so sampled auto-sizing remained materially slower than the deterministic-width path.

## Permanent repair

Both queue implementations now use deterministic `Interactive` widths for the five compact columns:

- Source row: 121 px
- Characters: 117 px
- Status: 91 px
- Duration: 108 px
- Retry: 87 px

Filename and Output remain `Stretch`. Other data columns keep their existing explicit widths. `Interactive` preserves manual resizing and avoids row/model-wide size-hint rescans when a theme change causes Qt stylesheet repolish.

## Preserved boundaries

- Exact global theme/QSS authority is unchanged.
- Light, Dark and System theme content is unchanged.
- Queue data/model, sorting, selection and generation scope are unchanged.
- No provider/account/voice/model/language authority changes.
- No automatic Preflight or Generation.
- No hidden cross-provider failover.
- Database schema remains 23.
