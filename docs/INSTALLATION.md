# Installation

## Development Install

1. Install Python 3.11 or newer.
2. Create a virtual environment: `py -3.11 -m venv .venv`
3. Install dependencies: `.\.venv\Scripts\python.exe -m pip install -e .[dev]`
4. Launch: `.\.venv\Scripts\python.exe -m app.gui.main`

## Portable Release

Run `.\scripts\build.ps1` to create `S-Talking-<version>-portable.zip` under `artifacts\package`.

Extract it to a writable folder and start `RUN.cmd` or `S-Talking.exe`. Because `portable.mode` is present, settings, databases, credentials, logs, reports, and generated output are stored in `S-Talking-Data` beside the executable.

## Per-user Windows Installer

Install Inno Setup so `ISCC.exe` is available, then run `.\scripts\build.ps1`. A verified unsigned installer is written under `artifacts\package\installer`.

The installer:

- installs under `%LOCALAPPDATA%\Programs\S Talking`;
- does not require administrator elevation;
- preserves application data under `%LOCALAPPDATA%\S-Talking`;
- reuses the previous installation directory during upgrades;
- closes a running application before replacing binaries;
- never treats a text placeholder as an installer executable.

## Distribution Bundle

After a verified release candidate exists, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\distribution-candidate.ps1 -BuildPackages
```

Use `-BuildPackages` to compile the frozen package first and `-RequireInstaller` when a portable-only bundle is not acceptable. Verify all files against `SHA256SUMS.txt` before publication.

## Upgrade and Rollback

Back up `%LOCALAPPDATA%\S-Talking` before an upgrade. Program files and writable user data are intentionally separate. The distribution bundle includes machine-readable `upgrade-plan.json` plus `ROLLBACK.md`.

## Provider Setup

Mock works without extra setup. ElevenLabs requires an API key. Piper requires the Piper executable and a local `.onnx` model.

## Upgrade, portable migration and rollback

Before changing versions, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade-validation.ps1 -CreateBackup -ValidateMigration
```

For a portable-to-installed transition, pass the extracted portable directory through `-SourceRoot` and use `-Mode portable_to_installed`. The source portable directory is never modified. Restore a verified backup only while S Talking is closed and only with the explicit `-AcknowledgeRestore` switch.

## Updating from inside S Talking

Open **Reports → Update Delivery** to configure a preview, beta, or stable feed. The application verifies feed and artifact SHA-256 values before a download is accepted. Signed Windows installers are rechecked with Authenticode. S Talking does not silently install, close, restart, or extract an update; the final action remains explicit and user-controlled.

## Crash recovery and safe mode

If S Talking repeatedly fails during startup, launch it once with `--safe-mode`. Safe mode skips automatic project/session restore, the generation recovery prompt and startup update checks while preserving access to **Reports → Crash Recovery & Diagnostics** and **Reports → Upgrade & Recovery**.

Structured crash reports and verified support bundles are stored under the writable diagnostics directory. They exclude settings, API profiles, credentials, databases, project sources and generated audio. Use `scripts\crash-diagnostics.ps1` from a source checkout to inspect or export the same evidence.

## Security verification

Before distributing a portable or installed build, generate the SPDX SBOM and
run the package audit:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\security-audit.ps1 `
  -GenerateSbom `
  -AuditPackage .\artifacts\package\S-Talking-1.0.0-portable.zip `
  -Export
```

Production Windows builds store provider credentials in Windows Credential
Manager. Do not copy the local `credentials` directory between users or include
it in installers, portable archives, backups intended for support, or release
artifacts.
