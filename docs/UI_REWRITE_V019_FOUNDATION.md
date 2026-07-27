# S Talking v0.19 UI Rewrite — Foundation

This slice begins the product UI rewrite by extracting the Provider workspace
from `MainWindow` into a reusable composition module.

## Implemented

- Provider panel construction moved to `app/gui/widgets/provider_workspace.py`.
- Stable design-system spacing and control metrics are used throughout.
- Account management is promoted to the panel header instead of competing with
  the API-profile field.
- Provider controls retain existing `MainWindow` attributes and callbacks, so
  application behavior and persistence remain compatible.
- The panel remains scrollable vertically and never introduces a horizontal
  scrollbar.
- Connection status keeps a fixed 52 px logical height independently of QSS.
- Regression tests prevent the monolithic provider builder from returning.

## Next slices

1. Provider Accounts details/navigation rewrite.
2. Queue model/view and selection toolbar rewrite.
3. Voice Browser visual system migration.
4. Activity and notification center.
