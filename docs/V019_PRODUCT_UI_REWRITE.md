# S Talking v0.19 Product UI Rewrite

v0.19 is split into controlled slices so visual work remains testable and does
not destabilize generation.

## Phase 1 — Design-system foundation (included)

- shared spacing, control-height, radius, typography and density scales;
- one source of truth for compact and comfortable layouts;
- media-runtime isolation and clean production launcher;
- no change to the official S Talking logo.

## Phase 2 — Main workspace

- queue-first central workspace;
- unified project context and metrics strips;
- compact provider/source dock;
- inspector/monitor dock;
- collapsed activity area by default.

## Phase 3 — Provider experience

- full Provider Accounts page;
- readable account/profile state;
- stable connection and quota components;
- provider-specific settings generated from capability schemas.

## Phase 4 — Voice Browser and queue

- professional catalog/list-detail layout;
- uniform preview controls;
- model-view queue and semantic status cells;
- keyboard-first sorting, selection and scope controls.

Each phase requires before/after screenshots, DPI validation, all automated
checks, and a clean local commit before proceeding.
