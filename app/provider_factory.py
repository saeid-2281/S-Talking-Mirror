from app.exceptions import ConfigurationError
from app.providers.elevenlabs import ElevenLabsProvider
from app.providers.mock import MockProvider
from app.providers.piper import PiperProvider
def create_provider(settings):
    return {"elevenlabs":ElevenLabsProvider,"mock":MockProvider,"piper":PiperProvider}.get(settings.provider,lambda s:(_ for _ in ()).throw(ConfigurationError(f'Unsupported provider: {s.provider}')))(settings)
