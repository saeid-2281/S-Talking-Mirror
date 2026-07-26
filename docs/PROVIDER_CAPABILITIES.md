# Provider Capabilities

Provider adapters expose a common capability model:

| Provider | Remote | Credential | Voices | Models | Language | SSML | Dictionary | Quota | Formats |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mock | No | No | Yes | Yes | No | No | No | No | wav |
| Piper | No | No | Yes | Yes | Yes | No | No | No | wav |
| ElevenLabs | Yes | API key | Yes | Yes | Yes | No | Yes | Yes | mp3/wav/pcm |
| OpenAI Speech | Yes | API key | Built-in | Static supported list | No | No | No | No | mp3/opus/aac/flac/wav/pcm |
| Azure AI Speech | Yes | Key/region or supported credential | Optional SDK | Optional SDK | Yes | Yes | No | No | mp3/wav |
| Google Cloud TTS | Yes | ADC or safe credential reference | Optional SDK | Optional SDK | Yes | No | No | No | mp3/wav |
| Amazon Polly | Yes | AWS profile/region | Optional SDK | Optional SDK | Yes | Yes | No | No | mp3/wav |
| Kokoro Local | No | No | Installed runtime | Installed runtime | Runtime-derived | No | No | No | wav |

Unavailable optional dependencies never prevent app startup. The setup status is shown through adapter validation.
