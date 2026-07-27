# v0.19 Phase 4 — Voice Browser and Pronunciation UI

This phase continues the direct UI rewrite without changing provider business logic.

## Voice Browser

- Added a compact account/provider context card.
- Replaced the classic search group box with a card-style filter surface.
- Added a persistent `Recent` navigation tab beside All Voices and Favorites.
- Moved saved-preview actions to a responsive grid to avoid horizontal clipping.
- Added stable object names for theme and regression coverage.
- Preserved account-specific catalog loading and model compatibility filtering.

## Pronunciation Dictionaries

- Added a clear product header explaining that rules do not change source CSV text.
- Added styled compatibility and action surfaces.
- Centered and clarified the existing onboarding state.
- Preserved all existing dictionary and rule operations.

## Compatibility

The existing public widget attributes and behaviors used by older tests remain intact.
