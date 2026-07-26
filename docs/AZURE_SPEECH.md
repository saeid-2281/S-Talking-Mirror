# Azure AI Speech

Azure AI Speech is represented by a setup-aware optional adapter. Safe metadata may include profile name, region, and optional endpoint. Subscription secrets must not be written to project files.

The adapter reports missing SDK or credential setup without breaking application startup. SSML must be produced through a safe builder before full synthesis support is enabled.
