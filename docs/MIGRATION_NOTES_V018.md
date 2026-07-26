# v0.18 Migration Notes

S Talking v0.18 is a production UX and workflow polish pass. It preserves the existing queue, provider, project, report, health, and packaging architecture while tightening the visible workspace.

## Branding

- The official master logo now lives at `app/resources/brand/official/S-Logo.svg`.
- Derived PNG/ICO assets are generated from that SVG only.
- Automated tests verify the master SHA256 hash.
- About dialog, taskbar icon, PyInstaller spec, and Inno Setup config prefer the official derived icon.

## Workspace

- MainWindow now starts at a screen-clamped production size with a minimum of `1180x700`.
- The large permanent heading was replaced by a compact project context bar.
- Workspace presets were added under `View > Workspace Layout`:
  Compact, Standard, Wide, Focus Mode, and Restore Default Layout.
- Project menu commands are sectioned with separators and icons.

## Health

- Healthy feature-branch work can score 100/100 while still recommending a commit.
- Source-development checks and packaged-runtime checks remain separated from v0.17.2.

## Compatibility

- Project files, provider IDs, queue persistence, reports, health artifacts, and portable packaging paths remain compatible.
- Internal provider IDs are unchanged.
