# Phase 59 — Final UX, Accessibility & Theme Certification

Phase 59 establishes a repeatable release gate for the S Talking visual system. It certifies the Dark, Graphite and Light themes, keyboard focus paths, selected-row readability, interactive target sizes, display scaling and assistive-technology metadata without reading private project content.

## Product entry points

- `Reports → UX & Accessibility Certification`
- Command Palette: `Reports: UX & Accessibility Certification`
- Source/frozen CLI: `--ux-certification`
- Export CLI: `--ux-certification --ux-certification-export`
- PowerShell: `scripts/ux-certification.ps1 -Export`

## Certified theme contracts

Every release must preserve:

- Dark canvas `#0A0F1C`
- Light canvas `#F3F6FA`
- Graphite canvas `#16181C`
- Skipped state `#94A3B8` in the established shared status contract
- Readable selected-row foreground/background pairs
- A focus indicator with at least 3:1 contrast against the canvas
- Primary and secondary text at WCAG-oriented thresholds

The service verifies seven foreground/background pairs for each theme. Missing tokens or a failed required contrast pair block certification.

## Keyboard and assistive-technology contract

The seven direct workspace routes remain certified:

- Ctrl+1 Provider
- Ctrl+2 Queue
- Ctrl+3 Inspector
- Ctrl+4 Activity
- Ctrl+5 Generation controls
- Ctrl+6 Output playback
- Ctrl+7 Text Studio
- F6 cycles the major regions

Visible icon-only controls require a tooltip or accessible name. Primary controls must remain keyboard focusable. Duplicate active shortcuts are reported as advisory findings.

## Display profiles

The release matrix covers Windows display scaling at 100%, 125%, 150% and 200%. Dialog actions remain pinned outside scrolling content, while high text scale uses the existing scroll-safe workspace contracts.

## Certified preset

The dialog can apply a non-destructive accessibility preset:

- High contrast
- Text scale at least 110%
- Enhanced keyboard focus
- Reduced motion
- Status announcements enabled

This changes only interface preferences. It does not modify projects, provider settings, source files, queue data or generated audio.

## Privacy boundary

Certification evidence contains only theme tokens, widget class/object metadata, dimensions, accessible labels, shortcut labels and gate results. It never reads project text, filenames, API profiles, credentials, database rows, generated audio or provider payloads.

## Release requirement

A stable release must have:

1. No blocker-level theme contrast failure.
2. All seven keyboard regions available.
3. No unnamed visible icon-only primary control.
4. No non-focusable primary action.
5. Valid JSON and CSV certification evidence.
6. The Phase 59 dedicated tests, full pytest suite and Quality Gate passing.
