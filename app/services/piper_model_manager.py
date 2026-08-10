from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.config.runtime import RuntimeConfig
from app.exceptions import ConfigurationError


@dataclass(frozen=True)
class PiperManagedVoice:
    voice_id: str
    model_path: Path
    config_path: Path
    language_code: str | None
    sample_rate: int | None
    speaker_count: int | None
    size_bytes: int
    managed: bool


class PiperModelManager:
    """Validate and explicitly import local Piper voice assets.

    The manager never downloads voices. Import is an explicit local file action
    that copies the ONNX model and required adjacent JSON config into S-Talking's
    managed offline-voice root. Existing conflicting assets are never overwritten.
    """

    def __init__(self, runtime: RuntimeConfig) -> None:
        self.runtime = runtime

    @property
    def managed_root(self) -> Path:
        return self.runtime.data_dir / "offline-voices" / "piper"

    def inspect(self, model_path: str | Path) -> PiperManagedVoice:
        model = Path(model_path).expanduser()
        if not model.is_file() or model.suffix.casefold() != ".onnx":
            raise ConfigurationError(f"Piper ONNX model not found: {model}")
        try:
            if model.stat().st_size <= 0:
                raise ConfigurationError(f"Piper ONNX model is empty: {model}")
        except OSError as exc:
            raise ConfigurationError(f"Piper ONNX model could not be inspected: {model}") from exc
        config = Path(f"{model}.json")
        if not config.is_file():
            raise ConfigurationError(f"Piper voice config not found: {config}")
        metadata = self._read_config(config)
        language = metadata.get("language") if isinstance(metadata.get("language"), dict) else {}
        audio = metadata.get("audio") if isinstance(metadata.get("audio"), dict) else {}
        language_code = self._string(language.get("code")) or self._string(metadata.get("language_code"))
        sample_rate = self._integer(audio.get("sample_rate")) or self._integer(metadata.get("sample_rate"))
        speaker_count = self._integer(metadata.get("num_speakers"))
        return PiperManagedVoice(
            voice_id=model.stem,
            model_path=model.resolve(),
            config_path=config.resolve(),
            language_code=language_code,
            sample_rate=sample_rate,
            speaker_count=speaker_count,
            size_bytes=max(0, int(model.stat().st_size)),
            managed=self._is_managed(model),
        )

    def import_voice(self, model_path: str | Path) -> PiperManagedVoice:
        source = self.inspect(model_path)
        target_dir = self.managed_root / source.voice_id
        target_model = target_dir / source.model_path.name
        target_config = target_dir / source.config_path.name

        if target_model.exists() or target_config.exists():
            if target_model.is_file() and target_config.is_file():
                if (
                    self._sha256(target_model) == self._sha256(source.model_path)
                    and self._sha256(target_config) == self._sha256(source.config_path)
                ):
                    return self.inspect(target_model)
            raise FileExistsError(
                f"Managed Piper voice already exists with different content: {target_dir}"
            )

        target_dir.mkdir(parents=True, exist_ok=False)
        try:
            shutil.copy2(source.model_path, target_model)
            shutil.copy2(source.config_path, target_config)
            model_card = source.model_path.parent / "MODEL_CARD"
            if model_card.is_file():
                shutil.copy2(model_card, target_dir / "MODEL_CARD")
            if self._sha256(target_model) != self._sha256(source.model_path):
                raise OSError("Imported Piper model hash verification failed.")
            if self._sha256(target_config) != self._sha256(source.config_path):
                raise OSError("Imported Piper config hash verification failed.")
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        return self.inspect(target_model)

    def managed_models(self) -> tuple[Path, ...]:
        root = self.managed_root
        if not root.is_dir():
            return ()
        try:
            return tuple(sorted(root.rglob("*.onnx"), key=lambda item: item.name.casefold()))
        except OSError:
            return ()

    def _is_managed(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.managed_root.resolve())
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _read_config(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Piper voice config is invalid: {path}") from exc
        if not isinstance(payload, dict):
            raise ConfigurationError(f"Piper voice config must contain a JSON object: {path}")
        return payload

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _string(value: object) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None

    @staticmethod
    def _integer(value: object) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
