# Phase 111 — Provider Plugin SDK

Phase 111 introduces a stable **Provider Plugin SDK v1** for third-party TTS adapters while preserving S-Talking's provider authority model.

## Security and authority contract

- Plugin discovery is metadata-only. `plugin.json` and the entry-point bytes are read and hashed; Python code is **not imported** during scan.
- Plugin activation is explicit and **session-only**. S-Talking does not auto-load third-party Python at startup in Phase 111.
- Activation is blocked while generation is active.
- Built-in provider IDs cannot be replaced or unregistered.
- Deactivation is blocked while generation is active or while the plugin provider is selected.
- Activating a plugin adds an available provider route; it does **not** change the current provider, account, voice, model, queue, Preflight decision, or Generation state.
- Plugins use the same Provider Accounts, Voice & Model Catalog, Preflight and Generation Engine paths as built-ins.
- No plugin registration path creates automatic cross-provider retry/failover.

## SDK v1 layout

```text
my_provider/
  plugin.json
  provider.py
```

`plugin.json`:

```json
{
  "sdk_api_version": 1,
  "plugin_id": "acme_tts.provider",
  "provider_id": "acme_tts",
  "entry_point": "provider.py:PluginProvider",
  "manifest": {
    "display_name": "Acme TTS",
    "locality": "cloud",
    "credential_mode": "profile_or_key",
    "setup_kind": "credential",
    "placeholder_api_key": true,
    "profile_management_ready": true,
    "controls": {
      "api_profile": true,
      "api_key": true,
      "voice_browser_fallback": true,
      "model_listing_fallback": true
    }
  }
}
```

The provider class imports the stable public contract from `app.plugin_sdk` and subclasses `TTSProvider`.

## Integrity and lifecycle

Discovery computes SHA-256 for `plugin.json` and the entry-point file, then derives a combined fingerprint. Activation re-reads the descriptor and refuses to load if the fingerprint changed after scan. A secret-free activation receipt is stored under the reports `provider-plugins` directory.

Plugin IDs and provider IDs use stable lowercase identifiers. Entry points must remain inside the plugin directory and symlinked plugin directories/files are rejected.

## Developer starter

Settings → **Provider Plugins / SDK** can create a minimal starter plugin. The template deliberately leaves synthesis unimplemented and does not contain credentials.

## Deliberate Phase 111 boundaries

This SDK is an extensibility contract, not a Python sandbox. Explicitly activated third-party Python executes with the application's OS permissions, which is why activation is never automatic. Persistent trusted-plugin allowlists, signed distribution policy, and final GA certification belong to Phase 112.

Database schema remains **23**.
