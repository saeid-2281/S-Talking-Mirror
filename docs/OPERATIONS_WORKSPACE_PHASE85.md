# Phase 85 — UI/UX Consolidation: Operations Workspace

Phase 85 reduces Reports-menu and operational-dialog discovery cost without replacing any authoritative operational service.

## Unified workspace

`Reports → Operations Workspace` is the primary navigation surface for operational work. It groups specialist tools into Reliability, Incidents, Recovery, Providers & Billing, Evidence & Certification, and Release & Security. The overview is powered by the existing Phase 80 command-center service.

## Menu consolidation

The Reports menu is split into four focused submenus: Operations & Governance, Release/Security/Runtime, Generation Analytics & Controls, and Reports & Diagnostics. Existing action names stay registered in `actions_by_name`, so command palette and automation hooks remain backward-compatible.

## Behavior-preserving contract

Phase 85 does not change operational evidence schemas, service behavior, persistence, provider routing, billing state, release state, recovery execution or certification semantics. The new dialog only calls the read-only `OperationsCommandCenterService.snapshot()` method and emits navigation requests to the existing specialist dialogs.

## Accessibility

The workspace provides keyboard-focusable section navigation, a clear search field, descriptive button accessible names and retained specialist workflows.
