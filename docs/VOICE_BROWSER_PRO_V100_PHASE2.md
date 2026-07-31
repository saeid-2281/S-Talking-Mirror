# Voice Browser Pro v1.0 — Phase 2

This phase adds account/profile-scoped voice library features.

## Added

- Pinned voices
- Recently used voices with use counts and timestamps
- Named collections
- Collections tab and filter
- Context menu actions
- Profile-scoped persistence in `voice-library.json`
- Catalog-ID filtering so a browser never shows repository voices outside the active account catalog

Favorites remain provider-wide to preserve the existing application contract.
Pins, recents, and collections are scoped by provider and API profile.
