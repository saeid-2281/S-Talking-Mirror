from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import inspect
import json
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any

from app.exceptions import ConfigurationError
from app.models.provider_manifest import ProviderControlPolicy, ProviderManifest
from app.models.provider_plugin import (
    PLUGIN_SDK_API_VERSION,
    ProviderPluginActivation,
    ProviderPluginCandidate,
    ProviderPluginDescriptor,
)
from app.provider_factory import register_provider_class, unregister_provider_class
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from app.providers.base import TTSProvider


_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{2,63}$")
_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_ENTRY_POINT_RE = re.compile(r"^(?P<file>[A-Za-z0-9_./-]+\.py):(?P<class>[A-Za-z_][A-Za-z0-9_]*)$")
_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_ENTRY_BYTES = 4 * 1024 * 1024


class ProviderPluginSDKService:
    """Explicit, session-scoped provider plugin discovery and activation.

    Discovery reads metadata and computes fingerprints only. Third-party Python code
    is imported exclusively from ``activate(..., approved=True)``. S-Talking does not
    auto-load provider plugins at startup in Phase 111.
    """

    def __init__(
        self,
        plugin_root: Path,
        evidence_dir: Path,
        *,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.plugin_root = Path(plugin_root)
        self.evidence_dir = Path(evidence_dir)
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY
        self._active: dict[
            str,
            tuple[ProviderPluginDescriptor, ModuleType, ProviderPluginActivation],
        ] = {}

    def ensure_directories(self) -> None:
        self.plugin_root.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

    def discover(self, root: Path | None = None) -> tuple[ProviderPluginCandidate, ...]:
        """Inspect plugin manifests without importing any plugin module."""

        scan_root = Path(root) if root is not None else self.plugin_root
        if not scan_root.exists():
            return ()
        if not scan_root.is_dir() or scan_root.is_symlink():
            return (
                ProviderPluginCandidate(
                    scan_root,
                    "invalid",
                    "Plugin root must be a real directory.",
                ),
            )

        directories: list[Path]
        if (scan_root / "plugin.json").is_file():
            directories = [scan_root]
        else:
            directories = sorted(
                (
                    item
                    for item in scan_root.iterdir()
                    if item.is_dir() and not item.is_symlink()
                ),
                key=lambda item: item.name.casefold(),
            )

        candidates: list[ProviderPluginCandidate] = []
        for directory in directories:
            try:
                descriptor = self._load_descriptor(directory)
                if descriptor.provider_id in self._active:
                    state = "active"
                    message = "Active for this S-Talking session."
                elif descriptor.provider_id in self.registry.provider_ids():
                    state = "blocked"
                    message = "Provider ID is already registered and cannot be overridden."
                else:
                    state = "compatible"
                    message = "Compatible; activation requires explicit user approval."
                candidates.append(
                    ProviderPluginCandidate(directory, state, message, descriptor)
                )
            except Exception as exc:
                candidates.append(
                    ProviderPluginCandidate(directory, "invalid", str(exc))
                )
        return tuple(candidates)

    def activate(
        self,
        candidate: ProviderPluginCandidate,
        *,
        approved: bool,
        generation_active: bool = False,
    ) -> ProviderPluginActivation:
        """Import and register a plugin only after explicit user approval."""

        if not approved:
            raise ConfigurationError(
                "Plugin activation requires explicit user approval."
            )
        if generation_active:
            raise ConfigurationError(
                "Stop active generation before activating a provider plugin."
            )
        descriptor = candidate.descriptor
        if descriptor is None:
            raise ConfigurationError("Invalid provider plugin cannot be activated.")
        if candidate.state not in {"compatible", "active"}:
            raise ConfigurationError(candidate.message or "Provider plugin is blocked.")
        if descriptor.provider_id in self._active:
            return self._active[descriptor.provider_id][2]

        current = self._load_descriptor(descriptor.root)
        if current.fingerprint != descriptor.fingerprint:
            raise ConfigurationError(
                "Plugin files changed after discovery; scan again before activation."
            )
        if descriptor.provider_id in self.registry.provider_ids():
            raise ConfigurationError(
                f"Provider ID is already registered: {descriptor.provider_id}"
            )

        module_name = (
            "s_talking_plugin_"
            f"{descriptor.plugin_id.replace('.', '_').replace('-', '_')}_"
            f"{descriptor.fingerprint[:12]}"
        )
        module = self._import_module(descriptor, module_name)
        provider_class = getattr(module, descriptor.entry_class, None)
        try:
            self._validate_provider_class(provider_class, descriptor)
            register_provider_class(descriptor.provider_id, provider_class)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        try:
            self.registry.register_plugin_manifest(descriptor.manifest)
        except Exception:
            unregister_provider_class(descriptor.provider_id)
            sys.modules.pop(module_name, None)
            raise

        activation = self._write_activation_receipt(descriptor, module_name)
        self._active[descriptor.provider_id] = (descriptor, module, activation)
        return activation

    def deactivate(
        self,
        provider_id: str,
        *,
        approved: bool,
        active_provider_id: str = "",
        generation_active: bool = False,
    ) -> None:
        """Remove a session plugin without changing the selected provider."""

        if not approved:
            raise ConfigurationError(
                "Plugin deactivation requires explicit user approval."
            )
        if generation_active:
            raise ConfigurationError(
                "Stop active generation before deactivating a provider plugin."
            )
        normalized = str(provider_id or "").strip().casefold()
        if normalized == str(active_provider_id or "").strip().casefold():
            raise ConfigurationError(
                "Select a different provider before deactivating this plugin."
            )
        active = self._active.get(normalized)
        if active is None:
            raise ConfigurationError(
                f"Provider plugin is not active: {normalized}"
            )

        descriptor, _module, activation = active
        self.registry.unregister_plugin_manifest(normalized)
        try:
            unregister_provider_class(normalized)
        except Exception:
            self.registry.register_plugin_manifest(descriptor.manifest)
            raise
        self._active.pop(normalized, None)
        sys.modules.pop(activation.module_name, None)

    def active_plugins(self) -> tuple[ProviderPluginActivation, ...]:
        return tuple(item[2] for item in self._active.values())

    def scaffold(
        self,
        destination: Path,
        *,
        provider_id: str,
        display_name: str,
    ) -> Path:
        """Create a minimal SDK v1 starter plugin without activating it."""

        normalized = str(provider_id or "").strip().casefold()
        if not _PROVIDER_ID_RE.fullmatch(normalized):
            raise ValueError("provider_id must match [a-z][a-z0-9_]{2,63}")
        if normalized in self.registry.provider_ids():
            raise ValueError(f"Provider ID already exists: {normalized}")
        name = str(display_name or "").strip()
        if not name:
            raise ValueError("display_name is required")
        target = Path(destination)
        if target.exists() and any(target.iterdir()):
            raise ValueError("Starter plugin destination must be empty.")
        target.mkdir(parents=True, exist_ok=True)
        plugin_id = f"{normalized}.provider"
        manifest = {
            "sdk_api_version": PLUGIN_SDK_API_VERSION,
            "plugin_id": plugin_id,
            "provider_id": normalized,
            "entry_point": "provider.py:PluginProvider",
            "manifest": {
                "display_name": name,
                "locality": "cloud",
                "credential_mode": "profile_or_key",
                "setup_kind": "credential",
                "placeholder_api_key": True,
                "profile_management_ready": True,
                "controls": {
                    "api_profile": True,
                    "api_key": True,
                    "voice_browser_fallback": True,
                    "model_listing_fallback": True,
                },
            },
        }
        (target / "plugin.json").write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        (target / "provider.py").write_text(
            self._starter_provider(normalized, name),
            encoding="utf-8",
        )
        (target / "README.md").write_text(
            self._starter_readme(normalized, name),
            encoding="utf-8",
        )
        return target

    def _load_descriptor(self, root: Path) -> ProviderPluginDescriptor:
        root = Path(root)
        if root.is_symlink():
            raise ValueError("Symlinked plugin directories are not accepted.")
        manifest_path = root / "plugin.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            raise ValueError("plugin.json is required and cannot be a symlink.")
        raw = manifest_path.read_bytes()
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ValueError("plugin.json exceeds the 64 KiB SDK limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(f"Invalid plugin.json: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("plugin.json root must be an object.")

        allowed_top = {
            "sdk_api_version",
            "plugin_id",
            "provider_id",
            "entry_point",
            "manifest",
        }
        unknown_top = sorted(set(payload) - allowed_top)
        if unknown_top:
            raise ValueError(
                f"Unknown plugin.json fields: {', '.join(unknown_top)}"
            )
        sdk_api_version = payload.get("sdk_api_version")
        if sdk_api_version != PLUGIN_SDK_API_VERSION:
            raise ValueError(
                "Unsupported plugin SDK API version "
                f"{sdk_api_version!r}; expected {PLUGIN_SDK_API_VERSION}."
            )
        raw_plugin_id = str(payload.get("plugin_id") or "").strip()
        raw_provider_id = str(payload.get("provider_id") or "").strip()
        plugin_id = raw_plugin_id.casefold()
        provider_id = raw_provider_id.casefold()
        if raw_plugin_id != plugin_id or not _PLUGIN_ID_RE.fullmatch(plugin_id):
            raise ValueError(
                "plugin_id must be a lowercase stable identifier (3-64 characters)."
            )
        if raw_provider_id != provider_id or not _PROVIDER_ID_RE.fullmatch(provider_id):
            raise ValueError("provider_id must match [a-z][a-z0-9_]{2,63}.")

        entry_point = str(payload.get("entry_point") or "").strip()
        match = _ENTRY_POINT_RE.fullmatch(entry_point)
        if match is None:
            raise ValueError(
                "entry_point must use relative/path.py:ProviderClass syntax."
            )
        entry_class = match.group("class")
        root_resolved = root.resolve(strict=True)
        entry_candidate = root / match.group("file")
        if entry_candidate.is_symlink():
            raise ValueError(
                "Plugin entry point must be a real Python file, not a symlink."
            )
        entry_file = entry_candidate.resolve(strict=True)
        if entry_file == root_resolved or root_resolved not in entry_file.parents:
            raise ValueError(
                "Plugin entry point must stay inside its plugin directory."
            )
        if not entry_file.is_file():
            raise ValueError(
                "Plugin entry point must be a real Python file."
            )
        code = entry_file.read_bytes()
        if len(code) > _MAX_ENTRY_BYTES:
            raise ValueError("Plugin entry point exceeds the 4 MiB SDK limit.")

        manifest = self._provider_manifest(provider_id, payload.get("manifest"))
        manifest_hash = sha256(raw).hexdigest()
        code_hash = sha256(code).hexdigest()
        fingerprint = sha256(
            f"{manifest_hash}:{code_hash}".encode("ascii")
        ).hexdigest()
        return ProviderPluginDescriptor(
            plugin_id=plugin_id,
            provider_id=provider_id,
            display_name=manifest.display_name,
            sdk_api_version=sdk_api_version,
            root=root_resolved,
            entry_file=entry_file,
            entry_class=entry_class,
            manifest=manifest,
            manifest_sha256=manifest_hash,
            code_sha256=code_hash,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _provider_manifest(provider_id: str, payload: Any) -> ProviderManifest:
        if not isinstance(payload, dict):
            raise ValueError("manifest must be an object.")
        allowed = {
            field.name
            for field in fields(ProviderManifest)
        } - {"provider_id", "controls"}
        unknown = sorted(set(payload) - allowed - {"controls"})
        if unknown:
            raise ValueError(
                f"Unknown provider manifest fields: {', '.join(unknown)}"
            )
        controls_payload = payload.get("controls", {})
        if not isinstance(controls_payload, dict):
            raise ValueError("manifest.controls must be an object.")
        allowed_controls = {
            field.name for field in fields(ProviderControlPolicy)
        }
        unknown_controls = sorted(set(controls_payload) - allowed_controls)
        if unknown_controls:
            raise ValueError(
                "Unknown provider control fields: "
                f"{', '.join(unknown_controls)}"
            )
        try:
            controls = ProviderControlPolicy(**controls_payload)
            values = {
                key: value
                for key, value in payload.items()
                if key != "controls"
            }
            return ProviderManifest(
                provider_id=provider_id,
                controls=controls,
                **values,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid provider manifest: {exc}") from exc

    @staticmethod
    def _validate_provider_class(
        provider_class: object,
        descriptor: ProviderPluginDescriptor,
    ) -> None:
        if not isinstance(provider_class, type) or not issubclass(
            provider_class,
            TTSProvider,
        ):
            raise ConfigurationError(
                "Plugin entry class must inherit app.plugin_sdk.TTSProvider."
            )
        if inspect.isabstract(provider_class):
            raise ConfigurationError(
                "Plugin entry class does not implement all required TTSProvider methods."
            )
        if str(getattr(provider_class, "provider_id", "")).strip() != descriptor.provider_id:
            raise ConfigurationError(
                "Plugin provider class provider_id does not match plugin.json."
            )
        if not str(getattr(provider_class, "display_name", "")).strip():
            raise ConfigurationError(
                "Plugin provider class display_name is required."
            )

    @staticmethod
    def _import_module(
        descriptor: ProviderPluginDescriptor,
        module_name: str,
    ) -> ModuleType:
        spec = importlib.util.spec_from_file_location(
            module_name,
            descriptor.entry_file,
        )
        if spec is None or spec.loader is None:
            raise ConfigurationError(
                "Unable to create a module loader for the provider plugin."
            )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        plugin_dir = str(descriptor.root)
        inserted = plugin_dir not in sys.path
        if inserted:
            sys.path.insert(0, plugin_dir)
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        finally:
            if inserted:
                try:
                    sys.path.remove(plugin_dir)
                except ValueError:
                    pass
        return module

    def _write_activation_receipt(
        self,
        descriptor: ProviderPluginDescriptor,
        module_name: str,
    ) -> ProviderPluginActivation:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        activated_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "schema_version": 1,
            "sdk_api_version": descriptor.sdk_api_version,
            "plugin_id": descriptor.plugin_id,
            "provider_id": descriptor.provider_id,
            "display_name": descriptor.display_name,
            "fingerprint": descriptor.fingerprint,
            "manifest_sha256": descriptor.manifest_sha256,
            "code_sha256": descriptor.code_sha256,
            "module_name": module_name,
            "activated_at": activated_at,
            "activation_scope": "session",
            "automatic_startup_loading": False,
            "provider_manifest": asdict(descriptor.manifest),
        }
        receipt_id = f"{descriptor.provider_id}-{descriptor.fingerprint[:12]}"
        path = self.evidence_dir / f"plugin-activation-{receipt_id}.json"
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return ProviderPluginActivation(
            plugin_id=descriptor.plugin_id,
            provider_id=descriptor.provider_id,
            fingerprint=descriptor.fingerprint,
            module_name=module_name,
            activated_at=activated_at,
            receipt_path=path,
        )

    @staticmethod
    def _starter_provider(provider_id: str, display_name: str) -> str:
        return f'''from __future__ import annotations

from app.plugin_sdk import (
    AppSettings,
    ProviderCapabilities,
    ProviderConfigurationResult,
    ProviderError,
    TTSProvider,
)


class PluginProvider(TTSProvider):
    provider_id = {provider_id!r}
    display_name = {display_name!r}

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            display_name=self.display_name,
            remote=True,
            requires_credential=True,
            supports_voice_listing=True,
            supports_model_listing=True,
            supports_cancellation=True,
            supported_output_formats=("mp3", "wav"),
            credential_fields=("api_key",),
        )

    def validate_configuration(self, settings: AppSettings) -> ProviderConfigurationResult:
        if not settings.api_key.strip():
            return ProviderConfigurationResult(False, "API key is required.")
        return ProviderConfigurationResult(True, "Plugin credential is configured.")

    def synthesize(self, text: str, settings: AppSettings) -> bytes:
        raise ProviderError(
            "Implement synthesis in your provider plugin.",
            provider_code="plugin_not_implemented",
        )

    def list_voices(self) -> list[dict]:
        return []

    def list_models(self) -> list[dict]:
        return []
'''

    @staticmethod
    def _starter_readme(provider_id: str, display_name: str) -> str:
        return f'''# {display_name} provider plugin

Provider ID: `{provider_id}`
S-Talking Plugin SDK API: `{PLUGIN_SDK_API_VERSION}`

1. Implement `synthesize`, `list_voices`, and `list_models` in `provider.py`.
2. Keep network activity out of module import. S-Talking imports plugin code only after explicit session activation.
3. Keep secrets in S-Talking provider profiles/settings; never place credentials in `plugin.json`.
4. Use Provider Accounts, Voice & Model Catalog, Preflight, and Start Generation normally. Plugins do not bypass those authorities.
5. Re-scan after any source change; the activation fingerprint must match the discovered files.
'''
