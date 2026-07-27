# Qt Multimedia and MP3 timestamp warnings

## Symptom

During MP3 playback the development console can display messages such as:

- `Could not update timestamps for skipped samples.`
- `Could not update timestamps for discarded samples.`

## Root cause

MP3 encoders add a small encoder delay and trailing padding. The Xing/LAME
metadata can describe those samples so a decoder can perform gapless playback.
Qt Multimedia uses FFmpeg by default. Some FFmpeg/Qt combinations decode the
file correctly but cannot adjust packet timestamps while applying the skip or
discard metadata, so FFmpeg writes a warning to native stderr.

The common `start: 0.025057` value at 44.1 kHz is approximately 1,105 samples,
which is consistent with MP3 encoder/decoder delay metadata. This warning alone
does not indicate corrupted synthesis or a damaged output file.

## S Talking behavior

- These exact messages are classified as benign multimedia diagnostics.
- They must not reduce Health score or mark an audio file as failed.
- The normal `scripts/run.ps1` launcher uses `pythonw.exe`, so native decoder
  diagnostics are not shown to production users.
- Developers can run `scripts/run-console.ps1` to keep console diagnostics.
- The default backend remains FFmpeg for codec coverage.
- On Windows, a user can test the native backend with:

  ```powershell
  .\scripts\run.ps1 -MediaBackend windows
  ```

  The Windows backend is an optional compatibility workaround, not the default.

## When it is a real problem

Investigate further only when one or more of these are also present:

- playback fails or stops early;
- output duration is incorrect;
- the file is zero bytes;
- audio validation identifies HTML, JSON, or text instead of audio;
- Qt reports a `QMediaPlayer` error;
- audible clipping occurs at the beginning or end.
