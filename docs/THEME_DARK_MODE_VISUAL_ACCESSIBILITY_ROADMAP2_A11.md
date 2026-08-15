# Roadmap 2 A11 — Theme, Dark Mode & Visual Accessibility

A11 certifies the selected **Soft Professional** visual direction across Light, Dark, and System theme resolution while preserving the long-lived `ThemeManager` and Qt `QPalette` authority.

## Product contract

A11 is a presentation/accessibility phase. It does **not** change provider selection, voice/model/language authority, source text, Preflight execution, generation start/restart, Smart Routing apply behavior, hidden failover, persistence schema, or queue business rules.

The legacy theme compatibility tokens remain frozen, including `DARK_TOKENS["canvas"] == "#0A0F1C"`, `LIGHT_TOKENS["canvas"] == "#F3F6FA"`, and `STATUS_COLORS["skipped"] == "#94A3B8"`. The root `QMainWindow` palette remains owned by `ThemeManager`; A11 never reintroduces a `QMainWindow` background takeover.

## Soft Professional accessibility refinement

The user-selected Light palette keeps its warm canvas, white surfaces, and primary blue. A11 strengthens only low-contrast semantic text/status tones so small UI text clears WCAG AA contrast:

- muted text: `#6C726B`
- success: `#2B7655`
- warning: `#8F5F1D`
- danger: `#A94646`
- info: `#476A91`

The filled primary remains `#5271C6`. On the light primary-soft tint, small semantic text uses the darker `primary_hover` tone so the tinted action/badge treatment also clears AA. The existing Soft Professional Dark palette is formally certified as the dark counterpart.

## Runtime theme behavior

`ThemeAccessibilityModernizer` propagates the resolved theme mode (`light`/`dark`), requested theme (`Light`/`Dark`/`System`), contrast mode, focus mode, and reduced-motion preference to the application shell and custom dialogs. `System` is resolved from the actual `ThemeManager.palette("System")` luminance instead of guessing from the name.

A11 is the final stylesheet layer after ThemeManager, A8 semantic tokens, A9/A9.1 workspace styling, and A10 dialog/form styling. This gives it authority over visual accessibility states without taking ownership of business behavior or root palette selection.

## Visual accessibility semantics

A11 provides:

- visible keyboard focus on buttons, tool buttons, form controls, editors, tables, trees, and lists;
- an enhanced-focus variant with a 2 px semantic focus ring;
- stronger boundaries in High Contrast mode;
- disabled states with explicit muted foreground and secondary surfaces;
- selected data rows with both tonal selection and a primary edge cue;
- status states with text color, soft background, boundary, and weight rather than hue alone;
- dark-aware tooltips and semantic selection colors;
- full stylesheet recomposition when interface preferences change so A9, A10, and A11 overlays cannot be accidentally dropped.

## Contrast evidence

The A11 contrast audit evaluates both Light and Dark palettes for primary, secondary, muted, primary-action, primary-soft, success, warning, danger, info, and focus-ring pairings. Normal text uses a 4.5:1 minimum; the graphical focus-ring contract uses 3:1.

## Compatibility boundaries

A11 preserves:

- A9/A9.1 workspace layout, responsive and geometry contracts;
- A10 form/control geometry and native file/font dialog exclusion;
- ThemeManager Light/Dark/System authority and historical tokens;
- existing Interface Preferences for High Contrast, Enhanced Focus, Reduced Motion, and announcements;
- Database schema 23;
- Track A provider/language/Preflight/generation authority freeze.

The next phase is **A12 — Final Product UX & Visual Certification**.
