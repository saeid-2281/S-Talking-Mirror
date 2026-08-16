# Roadmap 2 B2 — Intelligent TTS Execution Integration + Dark Theme Surface Unification

## Baseline

B2 starts from the certified B1 commit:

`4671d517ab6e008e7cd6e872e66d6e94a77e5ce6`

B1 is preserved as the immutable production-manifest authority boundary.

## Execution integration

B2 adds `IntelligentTTSExecutionService`. Immediately after the existing
Preflight == Launch == Generation assurance check and immediately before the
existing `GenerationController.start(...)` call, MainWindow now creates an
immutable B1-backed execution binding and verifies that it has not drifted.

The binding locks the exact queue order, provider, API profile, voice, model,
default language, output root, request ids, text hashes and manifest digest.
Any drift cancels the already-created execution session and releases the budget
reservation; Generation is not started.

B2 does **not** create a provider, choose a provider, run Preflight, start
Generation by itself, apply Smart Routing, infer language from text, reorder the
queue, or enable hidden cross-provider failover. Per-job language changes remain
explicit-only; B2 exposes an explicit override mapping API but MainWindow does
not invent one.

## Dark Theme correction

The user-reported runtime screenshot after A12.1 showed two visual families in
Dark mode: a Soft Professional neutral/olive central workspace and legacy
navy/blue Provider + Inspector dock surfaces.

Root cause: A12.1 attached `a121SurfaceFamily` dynamic properties, but the final
stylesheet still relied primarily on object-name selectors. Runtime Provider tab
pages/scroll viewports and the Selected Row panel therefore escaped the intended
semantic surface family.

B2 closes that gap by:

- making `a121SurfaceFamily=canvas|surface` itself a final stylesheet selector;
- enumerating actual left/right tab pages at runtime;
- tagging scroll-area viewport and content widgets, not just the outer dock;
- applying the semantic QPalette Window/Base colors to structural roots;
- explicitly treating Selected Row as a raised `surface`;
- preserving the three public themes System / Light / Dark;
- preserving the internal Graphite compatibility theme without exposing it.

The correction is structural and palette-driven, so Light and System use the
same hierarchy without hard-coded Dark-only colors.

## Evidence and exit criteria

B2 produces:

`artifacts/intelligent-tts-production/roadmap2-b2/`

and refreshes the existing three-theme screenshot evidence:

`artifacts/theme-surface-coherence/roadmap2-a12.1/`

B2 closes only after 14 execution tests, 8 dark-theme tests, B1/A12.1/Track A
focused regressions, machine certification, System/Light/Dark screenshot
evidence, one Full Quality Gate, commit/push verification and a clean source
Working Tree excluding local-only profiles.
