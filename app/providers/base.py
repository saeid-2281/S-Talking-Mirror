from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import AppSettings


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        """Convert text to audio bytes."""

    @abstractmethod
    def list_voices(self) -> list[dict]:
        """Return available voices."""

    @abstractmethod
    def list_models(self) -> list[dict]:
        """Return available models."""
