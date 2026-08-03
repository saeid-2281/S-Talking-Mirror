# Phase 52 — Installer, Upgrade & Distribution Readiness

Phase 52 converts the verified `0.18.2-rc1` release candidate into an auditable distribution bundle while keeping installed binaries, portable data, and user application data isolated.

## Distribution channels

- **Portable:** the verified release-candidate ZIP remains a first-class distribution channel. `portable.mode` keeps writable data in `S-Talking-Data` beside the executable.
- **Installed:** Inno Setup installs per-user under `%LOCALAPPDATA%\Programs\S Talking` without administrator elevation. Writable application data stays under `%LOCALAPPDATA%\S-Talking`.

## Upgrade safety

The installer keeps the stable AppId, reuses the previous install directory, requests the running application to close, does not automatically restart it, and does not use a destructive `[UninstallDelete]` section. Uninstalling program files must not remove settings, credentials, databases, reports, outputs, or diagnostics.

## Build artifacts

`scripts/build.ps1` now writes installer result schema 2. When Inno Setup is available, a real Windows PE installer is compiled, hashed, and marked distributable. When Inno Setup is unavailable, the build produces a clearly named `.txt` explanation instead of a fake `.exe`; the portable package remains valid.

## Distribution bundle

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\distribution-candidate.ps1 -BuildPackages
```

Use `-BuildPackages` to run the frozen build first. Add `-RequireInstaller` to reject portable-only bundles.

The verified bundle contains:

- portable ZIP;
- optional real installer;
- release-candidate manifest, checksums, and notes;
- `upgrade-plan.json`;
- `INSTALL.md` and `ROLLBACK.md`;
- `distribution-manifest.json` and `SHA256SUMS.txt`.

The application exposes the same evidence under **Reports → Distribution Readiness** and the command palette.

No database migration is introduced; schema remains 22.
