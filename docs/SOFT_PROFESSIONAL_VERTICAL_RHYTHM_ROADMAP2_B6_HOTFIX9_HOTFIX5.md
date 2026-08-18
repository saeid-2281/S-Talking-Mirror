# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Hotfix 5

## Fixed Queue Chrome Host

H9 H1-H4 progressively removed every suspected optional source of the dead
vertical slot. H4 evidence was decisive: Workflow, Batch Operations and Range
were all physically absent from `QueueWorkspace.root_layout`, the command host
was index 1 immediately after the heading, yet the rendered heading-to-command
gap remained 50 px. Explicit Workflow/Batch layouts also retained 24-25 px
gaps despite contiguous layout indices.

The remaining defect is therefore not stale optional membership. Fixed-height
queue chrome and the expanding queue work surface still shared one vertically
expanding QVBoxLayout. On the Windows Qt layout path, surplus height can be
assigned to the fixed chrome layout cells even though the widgets themselves
remain fixed, leaving visible blank space around those widgets.

H5 isolates the chrome into a dedicated vertically Fixed `queueChromeHost`. The
historical `QueueWorkspace.root_layout` API is preserved and now belongs to that
host, so all existing MainWindow/A9 insertion paths and ordering semantics remain
intact. The outer `shell_layout` owns the stretchable table/body. A small
`sync_chrome_height()` contract locks the host to the exact root-layout size hint
after geometry/disclosure changes. Thus spare desktop height can only expand the
work surface, never the gaps between queue bands.

This remains presentation-only. Provider/account/voice/model/language authority,
Preflight, Generation, Smart Routing, credentials, portable data semantics and
database schema 23 are unchanged.
