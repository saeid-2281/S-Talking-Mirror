from __future__ import annotations
import shutil, subprocess, tempfile
from pathlib import Path
from app.exceptions import ConfigurationError, ProviderError
from app.models import AppSettings
from app.models.provider_contract import ProviderCapabilities
from app.providers.base import TTSProvider
class PiperProvider(TTSProvider):
    provider_id="piper"; display_name="Piper"
    def __init__(self, settings:AppSettings):
        self.settings=settings; self.exe=shutil.which('piper')
        if not self.exe: raise ConfigurationError('Piper is not installed. Run: py -m pip install piper-tts')
        if not settings.piper_model_path: raise ConfigurationError('Select a Piper .onnx model.')
        self.model=Path(settings.piper_model_path)
        if not self.model.exists(): raise ConfigurationError(f'Piper model not found: {self.model}')
    def synthesize(self,text:str,settings:AppSettings)->bytes:
        with tempfile.TemporaryDirectory(prefix='s_talking_') as d:
            out=Path(d)/'out.wav'
            r=subprocess.run([self.exe,'--model',str(self.model),'--output_file',str(out)],input=text,text=True,encoding='utf-8',capture_output=True,timeout=settings.timeout_seconds)
            if r.returncode or not out.exists(): raise ProviderError((r.stderr or 'Piper failed')[:800])
            return out.read_bytes()
    def list_voices(self): return [{"voice_id":str(self.model),"name":self.model.stem,"category":"offline"}]
    def list_models(self): return [{"model_id":"piper-local","name":"Piper local ONNX"}]
    def capabilities(self): return ProviderCapabilities("piper","Piper",remote=False,requires_credential=False,supports_voice_listing=True,supports_model_listing=True,supports_language_code=True,supports_cancellation=True,supported_output_formats=("wav",))
