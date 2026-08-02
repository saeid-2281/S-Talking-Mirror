# Audio Output, Playback & Export UX — Phase 32

Phase 32 upgrades the existing **Output** tab without changing its public tab name or the legacy `output_log` handle.

## Output playback workspace

- Persistent shared audio player backed by `AudioPlayerService`.
- Current output path, format, size and availability status.
- Direct actions for opening the file, opening its folder, copying its path and copying handoff details.
- Existing output activity log remains writable through `MainWindow.output_log`.
- The output workspace opens automatically when queue or monitor playback starts.

## Professional audio controls

`AudioPlayerWidget` now uses a structured header, semantic status badge, transport card, seek control, volume control and responsive file actions. Existing public controls and keyboard Space play/pause behavior remain available.

## Navigation

- View → Output playback
- `Ctrl+6` focuses and expands the Output workspace.
- Activity tabs remain exactly `Activity`, `Output`, and `Errors`.

## Compatibility

No database migration or generation-engine behavior changed. Playback still uses the shared application `AudioPlayerService`, and all existing output-log integrations remain compatible.
