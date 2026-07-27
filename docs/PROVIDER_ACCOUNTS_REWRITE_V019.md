# Provider Accounts rewrite — v0.19 phase 1

This phase fixes account isolation in the ElevenLabs voice/model catalog and starts the Provider Accounts UI rewrite.

## Catalog correctness

- Catalog cache keys include provider, selected API profile, and credential fingerprint.
- User-triggered Refresh always bypasses the five-minute cache.
- Connection tests always request current account data.
- Duplicate model records are collapsed by `model_id`.
- Provider verification also performs a forced catalog refresh.

## Provider Accounts UI

- Accounts and Failover use left-side navigation.
- Refresh is a primary account action.
- Account details include voice and TTS model counts.
- Testing a saved account explicitly carries its profile identity into catalog loading.
- The account table remains the dominant surface; failover stays separate.

## Next phase

Extract account list/details into independent widgets and add account-switch refresh feedback in Voice Browser.
