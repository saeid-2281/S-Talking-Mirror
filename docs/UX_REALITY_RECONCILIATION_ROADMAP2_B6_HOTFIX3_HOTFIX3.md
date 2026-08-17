# Roadmap 2 B6 Hotfix 3 — Hotfix 3

## Responsive monitor authority reconciliation

The previous continuation proved the A11.1 monitor-width repair in isolation but
still exposed an order-dependent collapse to exactly 290 px after the A12 visual
certifier. The remaining conflict was not font metrics: the debounced responsive
workspace coordinator and the A11.1 visual-fidelity hardener both owned the same
physical right dock.

When Generation Monitor is the active right-dock tab and
`visualFidelityRequestedWidth` is present, that explicit monitor width is now the
presentation authority. A responsive breakpoint refresh may still choose its
normal 290/310/330 px inspector width for Selected Row and other tabs, but it may
not replace the active Generation Monitor target. The historical 290 px
`minimumWidth()` API contract remains unchanged.

## Regression coverage

- A forced responsive refresh after `refresh_monitor()` must keep the real active
  dock width in the A11.1 320–340 px range.
- A second responsive reconciliation after another monitor refresh must remain
  stable.
- The existing A12 → A11.1 same-process order regression remains mandatory.
- System / Light / Dark screenshot certification, Provider Accounts, startup
  recovery, HiDPI icons, B6 operations, Track A authority and schema 23 remain
  unchanged.
