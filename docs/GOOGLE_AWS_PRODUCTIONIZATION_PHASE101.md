# Phase 101 — Google Cloud TTS + Amazon Polly Productionization

Phase 101 promotes the existing Google Cloud TTS and Amazon Polly adapters from optional setup placeholders to production-oriented provider integrations on top of the Phase 99 Provider Architecture v2 and the Phase 100 provider-account model.

## Architectural guarantees

- Provider selection remains explicit. Smart Routing may recommend another provider, but S-Talking never silently changes provider or engine.
- Preflight and the Generation Engine remain authoritative for generation execution.
- Database schema contract 23 is unchanged.
- `api-profiles.json` and `workspace-profiles.json` remain local-only and are never part of the patch or commit.
- Google and AWS credentials are resolved externally; S-Talking stores only safe profile metadata such as a credential file reference, project ID, API endpoint hostname, AWS profile name, and AWS region.
- Provider-account catalog identity already includes provider options, so changes to Google credential/endpoint metadata or AWS profile/region cannot reuse a stale catalog from another resource.

## Google Cloud Text-to-Speech

The Google provider now supports:

- Application Default Credentials (ADC), or an explicit service-account JSON file reference.
- Optional API endpoint hostname for regional Cloud TTS routing.
- Live classic/Chirp voice discovery through `TextToSpeechClient.list_voices`, plus the documented Gemini-TTS prebuilt speaker catalog with model-compatibility metadata.
- Stable model catalog containing a provider-selected/default Cloud TTS mode plus current Gemini-TTS model families.
- `model_name` routing for Gemini-TTS while legacy/Chirp/Neural2/WaveNet voices continue through the normal Cloud TTS voice path.
- Plain text and SSML for compatible classic voices; Gemini-TTS uses text/prompt input and Chirp 3 HD rejects SSML as required by the provider contract.
- MP3, LINEAR16/WAV, and OGG Opus output mapping.
- Speaking-rate propagation where supported; Chirp 3 HD blocks non-default rate instead of sending an unsupported parameter.
- Current synchronous input-size guards for classic Cloud TTS and Gemini-TTS. Danish (`da-DK`) is exposed for Gemini-TTS only because it is currently listed by Google (Preview), while classic/Chirp availability still comes from the live catalog.
- Normalized credential, quota/rate-limit, timeout, and service errors.
- Connection verification through a real voice-catalog request without synthesizing billable preview audio.

The minimum optional `google-cloud-texttospeech` version is raised to `2.29` because the Cloud TTS Gemini model-name path requires that generation of the client library.

## Amazon Polly

The Amazon Polly provider now supports:

- Standard Boto3 credential resolution using an optional named AWS profile and explicit/derived region.
- Live voice discovery with pagination and bilingual-language inclusion.
- Voice metadata carrying the exact `SupportedEngines` values returned by Polly.
- Engine catalog for `standard`, `neural`, `generative`, and `long-form`.
- Explicit engine selection through the model field. S-Talking refuses synthesis when no Polly engine is selected rather than silently defaulting to another engine.
- Plain text and SSML input.
- MP3, OGG Vorbis, and raw PCM output mapping.
- Danish two-letter language normalization (`da` → `da-DK`) for API requests.
- Synchronous input guards enforce Polly's 3,000 billed-character text limit and the 6,000-character total SSML envelope, with safe audio-stream closure.
- Normalized credential/permission, throttling, timeout, invalid-request, and service errors.
- Connection verification through `DescribeVoices`, without synthesizing audio.

## Provider-account model

Phase 101 generalizes named provider accounts so that a cloud profile can be usable without a secret stored inside S-Talking when the provider authenticates through an external credential chain. OpenAI, Azure, and ElevenLabs retain their saved-secret requirement. Google ADC/service-account references and AWS named/default profiles do not fake an API key merely to satisfy the account model.

Provider Accounts exposes Google and AWS profiles, their safe provider metadata, catalog status, voices/models, and live sync state. Secret-replacement actions remain applicable only to providers that actually use a secret stored by S-Talking.

## Account execution compatibility

Named Google ADC/service-account-reference profiles and AWS named/default-chain profiles participate in the existing same-provider account planning through the manifest-level `credential_ready` contract. Providers that still require a saved secret preserve their historical behavior. This does not enable cross-provider failover.
