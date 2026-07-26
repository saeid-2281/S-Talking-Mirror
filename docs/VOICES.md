# Voice Browser

S Talking's Voice Browser provides a searchable, project-aware catalog for Mock, Piper, and ElevenLabs voices.

## Features

- Search by name, description, language, accent, gender, age, category, and voice ID.
- Filter favorites and provider metadata.
- Select a compatible TTS model together with the voice.
- View account tier and remaining ElevenLabs character allowance when available.
- Cache generated previews so identical previews do not consume credits twice.
- Store favorites locally in SQLite.

## ElevenLabs notes

The catalog uses the ElevenLabs voices and models APIs and reads subscription information when the API key permits it. Voice availability can depend on account tier and library permissions. A voice visible in a catalog may still require a paid plan for API synthesis.

API keys are never written into project files, reports, or voice metadata.
