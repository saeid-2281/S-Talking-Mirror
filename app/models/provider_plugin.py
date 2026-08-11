from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.models.provider_manifest import ProviderManifest


PLUGIN_SDK_API_VERSION = 1
PluginState = Literal["compatible", "active", "blocked", "invalid"]


@dataclass(frozen=True)
class ProviderPluginDescriptor:
    """Validated, non-executing description of one provider plugin."""

    plugin_id: str
    provider_id: str
    display_name: str
    sdk_api_version: int
    root: Path
    entry_file: Path
    entry_class: str
    manifest: ProviderManifest
    manifest_sha256: str
    code_sha256: str
    fingerprint: str


@dataclass(frozen=True)
class ProviderPluginCandidate:
    """Discovery result. Discovery never imports or executes plugin code."""

    root: Path
    state: PluginState
    message: str
    descriptor: ProviderPluginDescriptor | None = None

    @property
    def plugin_id(self) -> str:
        return self.descriptor.plugin_id if self.descriptor else self.root.name

    @property
    def provider_id(self) -> str:
        return self.descriptor.provider_id if self.descriptor else ""


@dataclass(frozen=True)
class ProviderPluginActivation:
    """Secret-free evidence describing an explicit session activation."""

    plugin_id: str
    provider_id: str
    fingerprint: str
    module_name: str
    activated_at: str
    receipt_path: Path
