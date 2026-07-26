from __future__ import annotations
import math, struct, wave
from io import BytesIO
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities
from app.providers.base import TTSProvider
class MockProvider(TTSProvider):
    """Creates free WAV tones to test the full batch pipeline."""
    provider_id="mock"; display_name="Mock"
    def __init__(self, settings: AppSettings): self.settings=settings
    def capabilities(self): return ProviderCapabilities("mock","Mock",remote=False,requires_credential=False,supports_voice_listing=True,supports_model_listing=True,supports_cancellation=True,supported_output_formats=("wav",))
    def synthesize(self,text:str,settings:AppSettings)->bytes:
        rate=22050; seconds=min(.35+len(text)*.004,2.0); frames=int(rate*seconds)
        b=BytesIO()
        with wave.open(b,'wb') as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
            for i in range(frames): f.writeframesraw(struct.pack('<h',int(9000*math.sin(2*math.pi*440*i/rate))))
        return b.getvalue()
    def list_voices(self): return [{"voice_id":"mock-tone","name":"Local test tone","category":"free"}]
    def list_models(self): return [{"model_id":"mock-v1","name":"Local test generator"}]
