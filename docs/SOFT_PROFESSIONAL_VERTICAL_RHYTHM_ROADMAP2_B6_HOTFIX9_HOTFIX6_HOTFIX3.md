# Roadmap 2 B6 Hotfix 3 — Hotfix 9 / Hotfix 6 / Hotfix 3

## Queue shell surplus ownership

Hotfix 6 Hotfix 2 proved that the queue chrome itself was already internally compact:

- collapsed root order was `Heading -> Command -> Summary`,
- Heading -> Command and Command -> Summary gaps were within the 8px contract,
- `chrome_host.height()` matched the bounded visible chrome content height,
- yet the launch-to-summary envelope remained 293px instead of at most 220px.

That combination localizes the remaining surplus outside the internal chrome rows. The queue shell still hosted its work surface as a bare child `QVBoxLayout`. On the Windows Qt geometry path, the zero-stretch fixed chrome item could therefore receive a taller outer layout cell before the stretchable child-layout item, placing the first chrome row below the top of the queue even though all internal row geometry was correct.

Hotfix 6 Hotfix 3 makes vertical ownership explicit:

- `queueChromeHost` stays fixed and top-aligned,
- a real `queueBodyHost` QWidget owns the expanding work surface,
- shell stretch factors are explicitly `0 / 1 / 0` for chrome / body / footer,
- the footer is vertically fixed,
- every chrome-height synchronization reasserts the same shell ownership.

No provider, routing, Preflight, Generation, credential, persistence, database, billing, language, or Track A authority changes are introduced.

## Acceptance

At 2048×1140 Wide mode with Workflow and Batch plan collapsed:

- chrome top offset: 0–2px,
- first heading offset inside chrome: 0–2px,
- Chrome -> Body gap: 0–8px,
- Heading -> Command gap: 0–8px,
- Command -> Summary gap: 0–8px,
- Launch -> Summary bottom: at most 220px,
- window-height growth is absorbed by `queueBodyHost`, not by queue chrome,
- disclosure open/close round trips cannot move the collapsed chrome downward.

The existing H9, H6H2, H6, H5, H4, H3, H2, H1, A9/A9.1, three-theme, H8 pixel and Track A regressions remain authoritative.
