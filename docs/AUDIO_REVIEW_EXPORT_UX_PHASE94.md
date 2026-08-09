# Phase 94 — Audio Review & Export UX 2.0

Phase 94 turns the existing Output playback tab into a post-generation review and handoff workspace without changing generation, retry, billing, queue ordering, or playback semantics.

## Review flow

The Output workspace now derives a read-only inventory from the real generation queue:

- Ready — completed job with an existing output artifact.
- Missing — completed job whose expected output artifact cannot be found.
- Failed — failed generation job.
- Pending — retained in summary state but omitted from the generated-output review selector.

Users can filter the generated-output review list, move Previous/Next, load ready artifacts into the existing AudioPlayerService, and inspect missing/failed artifacts without forcing playback.

## Export flow

Export is copy-only. It never transcodes source audio, mutates a generated artifact, changes queue state, or overwrites an existing destination file.

Presets:

- Flat bundle — copy all ready artifacts into one destination directory.
- Preserve folders — preserve output-root-relative subfolders when possible.

Scopes:

- All ready outputs.
- Current output.

Every copied file is SHA-256 verified after copy. Name collisions receive deterministic `__2`, `__3`, ... suffixes. A `S-Talking-audio-export-manifest*.json` file records source path, destination path, size and SHA-256 for each copy.

## Integration

`Ctrl+Alt+A` opens and focuses `Audio review & export`. The existing `Ctrl+6` Output playback action remains unchanged.

The Output workspace receives queue, output-directory, settings and output-path providers from MainWindow. `show_output_workspace()` refreshes the review inventory before handing off to playback.

## Safety contract

Phase 94 does not:

- create a new generation path;
- alter retry policy;
- reorder queue jobs;
- modify output artifacts;
- transcode audio;
- auto-play during Previous/Next review;
- overwrite an existing exported copy.
