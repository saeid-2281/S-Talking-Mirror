# Roadmap 2 B7 — Minimal Daily Workflow

## Purpose

B7 turns the certified B6/H11 workspace into a queue-first daily workflow without removing professional capabilities or creating alternate execution paths. The approved Soft Professional concept is the presentation contract: one command/status strip, one consolidated project context, a dominant queue work surface, stacked secondary queue tools, and a compact Output drawer.

## Daily-workflow composition

- The native `QMainWindow` toolbar remains the QAction/shortcut authority but is not rendered as a second command row.
- `MetricsStrip` is reused as the unified daily command/status strip. New/Open/Save are grouped under **Project**; **Sources** and **Start** remain primary daily actions; provider/model/Preflight badges share the same strip; advanced actions live under **More**.
- The separate project banner and source/output strip are one `workspaceHero`. Project, source, provider, voice, model, output summary and contextual Reload/Output controls therefore share one surface.
- The duplicate Add Sources control inside the hero is hidden in `MainWindow`; the unified strip owns the one visible daily Sources command.
- The secondary GenerationStatusStrip keeps its stable API handles but does not render another Start or Preflight button in B7. Pause/Stop appear only while generation is active.

## Queue-first workspace

The queue table owns the expanding work surface. Existing controls are reparented, not reimplemented, into one-at-a-time stacked sections below the rows:

1. Queue actions
2. Filters
3. Batch plan
4. Workflow
5. Columns

The old command host and A9 header disclosure buttons remain compatibility handles but consume no B7 workspace height. Historical focus shortcuts open the corresponding B7 accordion section.

## Output

`ActivityCenter` retains its historical component default for compatibility. `MainWindow` enables B7 compact-output mode at 260 px. Output playback still uses the H11 internal scroll-safe workspace, but opening Output no longer takes over the queue.

## Preflight / dry-run presentation and CSV-state repair

- B7 exposes one secondary **Preflight / dry run** action. It performs the existing no-audio explicit Preflight path; the duplicate inline queue button and secondary GenerationStatusStrip Preflight button are hidden.
- No automatic provider/account/voice/model/language change is introduced.
- No hidden provider failover is introduced.
- Explicit Preflight/dry-run is optional. If no fresh result exists, `MainWindow.start()` runs the same no-audio safety evaluation automatically before any provider request; hard blockers still stop generation.
- Before an explicitly requested Preflight, current-state read, or launch-revision calculation, the generation controller is synchronized from the visible Scope and Order controls. This prevents a stale controller planning mode from reporting an empty Preflight plan while the visible queue targets a populated scope.

## Launch acknowledgement

Multiple required acknowledgement codes remain individually auditable in the launch receipt, but the dialog presents one human decision checkbox. Checking it acknowledges the reviewed warning set once instead of forcing several repetitive clicks.

## Safety boundaries

- Existing `QAction` objects and MainWindow handlers remain command authority.
- GenerationController remains generation authority.
- Preflight safety semantics are preserved, but the manual Preflight step is no longer a required user workflow before Start.
- No automatic user-visible Preflight workflow, Generation start, Smart Routing, provider/account/voice/model/language selection, or cross-provider failover is introduced. Start may run the existing no-audio safety evaluator when its cached validation is stale; it never bypasses a hard blocker.
- Database schema 23 is unchanged.
- H11 incremental queue progress and scroll-safe Output behavior remain in place.

## Acceptance criteria

- One visible daily Start command in the workspace.
- One visible daily Sources command in the workspace.
- One secondary Preflight/dry-run entry; no repeated workspace buttons.
- Project/source/provider/voice/model/output context uses one consolidated hero surface.
- Toolbar/status chips are one command strip.
- Queue tools sit below the table in a stacked one-open accordion.
- Output opens as a compact drawer and leaves the queue usable on a large desktop display.
- Explicit Preflight uses the visible queue scope/order and does not falsely report an empty CSV scope when jobs are loaded.
- Multiple launch acknowledgement codes require one visual checkbox while all codes remain recorded.
- System / Light / Dark remain supported by semantic styling.
