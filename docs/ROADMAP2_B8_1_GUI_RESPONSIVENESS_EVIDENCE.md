# Roadmap 2 B8.1 — External GUI Responsiveness Evidence

## Scope

B7 is frozen at commit `bcfcca70eb135f4caf526e09b7dea5448368ca0f`.
B8.1 creates an **opt-in external monitor** to measure whether the existing
accepted Portable GUI handles a harmless Win32 `WM_NULL` heartbeat while a
human repeats the large-queue Pause, Resume, Stop, and project-switch sequence.
The B7 application, DB schema 23, user provider/account/voice/model/language
authority, offline voices, credentials, and Portable are **not changed**.

## Run on Windows

Run `RUN-B8-GUI-HEARTBEAT.cmd` after completing the B8.1 code/test runner.
The command launches the exact accepted B7 Portable without installing Python
packages or downloading an engine. Perform the normal scenario, then close the
application to save a timestamped `.json` summary and `.jsonl` heartbeat series
under `C:\zip-for-GPT`. The report includes only UTC timestamps and heartbeat
states/counters — no window title, CSV contents, project path, account, voice,
provider, console environment, or secret.

Two consecutive missed GUI heartbeats count as one observed stall. An absent
window, a delayed launch, or one lost message is *not* automatically a GUI hang.
This is a diagnostic, not an automatic certification or an assertion that an
observed stall was caused by S-Talking rather than the operating system. A
clean result still requires the user's manual action sequence and confirmation.

## Release and version policy

`fix/provider-accounts-layout` and the accepted B7 Portable remain unchanged.
New B8.1 work is committed to a separate `roadmap2/b8-gui-responsiveness-evidence`
branch only after dedicated tests and Full Quality Gate pass on Windows. The
freeze report/ZIP from B7 remains independent and immutable. B8.1 does not
create another B7 Portable or reinstall Piper.
