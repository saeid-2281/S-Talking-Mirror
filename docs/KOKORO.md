# Kokoro Local

Kokoro is an optional local provider using the official `KPipeline` API. S-Talking exposes only the Kokoro v1.0 language/voice combinations that are explicitly present in the upstream catalog.

Current certified pipelines are American English (`a`), British English (`b`), Spanish (`e`), French (`f`), Hindi (`h`), Italian (`i`), Japanese (`j`), Brazilian Portuguese (`p`), and Mandarin Chinese (`z`).

Danish is **not** in the official Kokoro v1.0 language catalog. `da` / `da-DK` must therefore remain blocked until an upstream model/runtime with explicit Danish support is independently certified.

The local runtime caches language pipelines, supports cooperative cancellation, and returns 24 kHz WAV bytes to the existing Generation Worker. Inventory and validation do not download model assets; explicit warm-up or generation may let the upstream Kokoro runtime resolve its own required assets.
