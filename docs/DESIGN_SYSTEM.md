# S Talking Design System

## Semantic Tokens

Theme tokens are defined in `app/gui/theme.py`.

- Canvas: application background.
- Surface: panels and primary containers.
- Surface raised: buttons, headers, elevated controls.
- Surface soft: quiet section backgrounds.
- Input: editable fields and table bodies.
- Border subtle/standard/strong: structural separation.
- Focus: keyboard and active-control ring.
- Text primary/secondary/muted/disabled/inverse: typography hierarchy.
- Primary/hover/pressed/destructive: actions.
- Success/info/warning/error/pending/running/skipped/favorite/selected: state language.

## Spacing

Base unit is 4 px.

- xs: 4 px
- sm: 8 px
- md: 12 px
- lg: 16 px
- xl: 24 px
- 2xl: 32 px

Controls should default to 30-36 px tall; primary actions may use 40 px. Icon buttons should be 34-36 px with tooltips.

## Shape

Small radius: 5 px. Standard controls: 8 px. Cards/dialogs: 10 px. Pills/status badges may be fully rounded.

Avoid toy-like 16-24 px rounded rectangles in dense production tools.

## Reports

HTML reports should use the brand symbol, system fonts, semantic state colors, and printable spacing. JSON reports remain numeric and machine-readable.
