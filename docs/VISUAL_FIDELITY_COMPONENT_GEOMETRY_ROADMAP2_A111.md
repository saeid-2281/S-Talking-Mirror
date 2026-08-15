# Roadmap 2 A11.1 — Visual Fidelity & Component Geometry Hardening

A11 successfully certified the Soft Professional Light/Dark semantic layer, but the
post-certification screenshot review exposed component-level visual defects that are
too visible to defer to A12 certification.

## Screenshot defects closed by A11.1

1. **Main toolbar icon consistency**
   - Every visible main-toolbar action now receives a canonical `action_icon(...)`
     icon at one 20 px size.
   - Legacy/mixed toolbar action icons are no longer retained merely because an
     action already has an icon.
   - Generated `QToolButton` geometry is normalized without changing its action.

2. **Metric-card corner stability**
   - `Files`, `Pending`, `Running`, `Completed`, `Failed`, `Quota`, `ETA`, and the
     other metric pills keep the Soft Professional 12 px card radius in normal,
     hover and active/filter states.
   - Clicking a metric still performs the existing queue-filter action; presentation
     no longer changes the component shape.

3. **Generation Monitor fit**
   - The historical maximum remains 340 px.
   - When the Generation Monitor tab is active it receives a 320–340 px usable dock
     contract and the dock is requested at 340 px.
   - Internal labels, buttons, scroll content and tab bars are allowed to shrink or
     wrap instead of clipping outside the monitor.

4. **Provider Accounts Center details usability**
   - The dialog has a practical minimum desktop geometry.
   - `Account details` receives at least 420 px width, sane margins and non-collapsible
     splitter behavior.
   - Detail labels wrap and action buttons receive enough height/width to remain usable.

5. **Provider overview/sidebar fit**
   - The provider identity/overview card is allowed to grow vertically inside the
     existing scrollable provider dock.
   - Long status labels wrap and long badge/button text elides with a full tooltip.
   - No horizontal provider-dock expansion is introduced.

## Compatibility boundary

A11.1 is presentation-only. It does not change provider selection, account activation,
voice/model/language authority, source text, Preflight authority, generation authority,
Smart Routing, failover, persistence, or database schema.

The A9/A9.1 responsive contracts, A10 dialog modernization, A11 Light/Dark/System
theme authority and historical Q2 repolish optimization remain authoritative.

A12 remains the final product UX and visual certification phase. It must certify the
real product only after the A11.1 screenshot defects are closed.

## Hotfix 3 — Generation Monitor compatibility reconciliation

The historical Generation Monitor API contract exposes a 290 px minimum width.
A11.1 must not redefine that compatibility contract. The visual-fidelity requirement
is instead expressed as the *actual dock width* when the Generation Monitor tab is
active: the dock is requested at 340 px and remains capped at 340 px, while the
historical `minimumWidth()` contract stays in the 280–300 px range.

This keeps older monitor/show-hide/command-palette regressions valid while still
giving the live Generation Monitor a 320–340 px usable presentation when selected.
