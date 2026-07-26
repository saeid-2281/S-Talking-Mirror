# OpenAI Speech

OpenAI Speech uses the official `POST /v1/audio/speech` API.

Configured fields:

- API key
- model
- voice
- output format
- speed

Built-in voices are exposed by the adapter. The provider does not expose an ElevenLabs-style character quota endpoint, so S Talking displays “Quota unavailable from provider” instead of guessing.

Live tests must be explicitly enabled and require a real OpenAI key.
