# Phase 107 — Provider Cost / Quota / Limits Intelligence

Phase 107 adds one read-only intelligence surface for provider economics and request-size limits.

## Safety contract

- The intelligence service never changes the selected provider, account, model, voice, or generation settings.
- It never performs implicit billing, admin, credit, balance, or usage API calls.
- Cloud pricing is **unknown** unless a non-zero S-Talking pricing rate is already configured.
- Local providers report `0` provider fee only; electricity, hardware, and local operating costs are intentionally excluded.
- Quota is **confirmed** only when an existing profile or cached account catalog contains remaining usage data.
- Missing quota is not converted into zero and is not treated as exhausted.
- Request limits are shown only from encoded provider contracts or cached model metadata.
- No hidden cross-provider failover is introduced.

## Request-limit contracts

The static provider registry now carries conservative synchronous synthesis limits where S-Talking already has a stable provider contract:

- OpenAI Speech: 4,096 input characters.
- Google Cloud TTS classic: 5,000 input bytes. Gemini-TTS is represented separately as 4,000 text bytes, 4,000 prompt bytes, and 8,000 combined.
- Amazon Polly `SynthesizeSpeech`: 3,000 billed characters; 6,000 total characters including SSML/whitespace.
- Murf API non-streaming: 3,000 characters.
- ElevenLabs remains model-catalog driven because its maximum request length varies by model.

Unknown limits for other providers remain explicitly unknown rather than guessed.

## Pricing and quota sources

The new service composes:

1. `GenerationCostCapacityService` configured project/global pricing rates.
2. `ApiProfile` confirmed quota fields.
3. Cached `VoiceCatalog.account` quota snapshots.
4. Unified Voice & Model Catalog model metadata.
5. Provider Registry static request-limit contracts.

The Provider Cost / Quota / Limits dialog links back to **Cost & Capacity** for rate configuration and **Provider Accounts** for explicit account refresh/management.

## Database

No database migration is introduced. Schema contract **23** is preserved.
