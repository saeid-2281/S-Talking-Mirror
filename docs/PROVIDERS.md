# Providers

S Talking uses provider adapters behind a common contract. The GUI and Preflight should inspect capabilities rather than hard-code provider names.

Base installation includes Mock, Piper integration, ElevenLabs, OpenAI Speech REST support, and setup-aware adapter shells for Azure AI Speech, Google Cloud Text-to-Speech, Amazon Polly, and Kokoro Local.

Secrets are stored only through secure settings/profile services. Reports and diagnostics must contain safe display names, provider IDs, request IDs, and redacted errors, not raw credentials.

Live tests remain opt-in through provider-specific environment flags.
