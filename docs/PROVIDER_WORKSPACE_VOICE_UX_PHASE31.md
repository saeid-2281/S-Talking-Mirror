# Phase 31 — Provider Workspace & Voice Configuration UX

Phase 31 turns the provider panel into a task-oriented setup surface while preserving all existing provider controls and public handles.

## Provider readiness overview

The panel now starts with a compact overview card containing:

- provider display name and local/cloud mode;
- semantic connection status;
- active credential profile;
- confirmed or provider-reported quota state;
- capability badges;
- a context-sensitive next step.

The overview is presentation-only. Provider configuration, verification and catalog behavior remain in the existing services.

## Context-aware form

Rows that do not apply to the selected provider are hidden as complete form rows, including labels. For example, Piper exposes the local model path while cloud credential rows remain hidden. ElevenLabs exposes profile, key, failover and expression controls.

## Section guidance

Each collapsible section includes a short explanation of its purpose. Collapsed Account and Voice sections keep concise live summaries so operators can understand the active configuration without reopening every section.

## Compatibility

Existing handles such as `provider`, `api_profile`, `key`, `voice`, `model`, `connection_status`, `provider_sections` and all icon action buttons remain unchanged. Database schema and persistence are unchanged.
