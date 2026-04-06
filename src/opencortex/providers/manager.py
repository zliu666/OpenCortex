"""Provider manager for switching between AI providers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opencortex.config.paths import get_config_dir

# Preset providers with known configurations
PRESET_PROVIDERS: dict[str, dict[str, Any]] = {
    "zhipu": {
        "name": "智谱 AI (GLM)",
        "base_url": "https://open.bigmodel.cn/api/anthropic",
        "api_format": "anthropic",
        "default_model": "glm-5-turbo",
        "models": ["glm-5.1", "glm-5-turbo", "glm-5", "glm-4.7", "glm-4.6", "glm-4.5-air"],
        "requires": ["ZHIPU_API_KEY"],
        "key_url": "https://open.bigmodel.cn/usercenter/apikeys",
    },
    "minimax": {
        "name": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "api_format": "openai",
        "default_model": "MiniMax-M2.7",
        "models": ["MiniMax-M2.7", "MiniMax-M2.7-highspeed", "MiniMax-M2.5", "MiniMax-M2.5-highspeed", "MiniMax-M2.1", "MiniMax-M2"],
        "requires": ["MINIMAX_API_KEY"],
        "key_url": "https://platform.minimaxi.com/user-center/basic-information",
    },
}


class ProviderManager:
    """Manager for AI providers.

    Supports preset providers (zhipu, minimax) and custom providers
    defined in ~/.opencortex/providers.json.
    """

    def __init__(self) -> None:
        """Initialize the provider manager."""
        self._custom_providers: dict[str, dict[str, Any]] = {}
        self._load_custom_providers()

    def _get_providers_file(self) -> Path:
        """Return the path to the custom providers config file."""
        return get_config_dir() / "providers.json"

    def _load_custom_providers(self) -> None:
        """Load custom providers from the config file."""
        providers_file = self._get_providers_file()
        if providers_file.exists():
            try:
                raw = json.loads(providers_file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._custom_providers = raw
            except (json.JSONDecodeError, OSError):
                self._custom_providers = {}

    def list_providers(self) -> dict[str, dict[str, Any]]:
        """Return all available providers (preset + custom).

        Returns:
            Dict mapping provider ID to provider config.
        """
        result = dict(PRESET_PROVIDERS)
        # Custom providers are prefixed with "custom:" in usage
        for key, config in self._custom_providers.items():
            result[f"custom:{key}"] = config
        return result

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        """Get a specific provider by ID.

        Args:
            provider_id: Provider identifier (e.g., "zhipu", "minimax", "custom:my-ollama")

        Returns:
            Provider config dict, or None if not found.
        """
        if provider_id in PRESET_PROVIDERS:
            return PRESET_PROVIDERS[provider_id]

        if provider_id.startswith("custom:"):
            custom_key = provider_id[7:]  # Remove "custom:" prefix
            return self._custom_providers.get(custom_key)

        return None

    def get_provider_info(self, provider_id: str) -> str:
        """Get human-readable info about a provider.

        Args:
            provider_id: Provider identifier

        Returns:
            Formatted string with provider details.
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return f"Provider not found: {provider_id}"

        lines = [
            f"Provider: {provider.get('name', provider_id)}",
            f"  base_url: {provider.get('base_url', '(default)')}",
            f"  api_format: {provider.get('api_format', 'anthropic')}",
            f"  default_model: {provider.get('default_model', '(unknown)')}",
        ]

        models = provider.get("models", [])
        if models:
            lines.append(f"  models: {', '.join(models)}")

        requires = provider.get("requires", [])
        if requires:
            lines.append(f"  requires: {', '.join(requires)}")

        return "\n".join(lines)

    def list_custom_providers(self) -> dict[str, dict[str, Any]]:
        """Return custom providers without 'custom:' prefix.

        Returns:
            Dict mapping custom provider ID to provider config.
        """
        return dict(self._custom_providers)

    def list_all_info(self) -> str:
        """Get human-readable info about all providers.

        Returns:
            Formatted string listing all providers.
        """
        lines = ["Available providers:", ""]
        lines.append("Preset providers:")

        for provider_id, config in PRESET_PROVIDERS.items():
            name = config.get("name", provider_id)
            default_model = config.get("default_model", "(unknown)")
            lines.append(f"  {provider_id}: {name} (default: {default_model})")

        if self._custom_providers:
            lines.append("")
            lines.append("Custom providers (from ~/.opencortex/providers.json):")
            for provider_id, config in self._custom_providers.items():
                name = config.get("name", provider_id)
                default_model = config.get("default_model", "(unknown)")
                lines.append(f"  custom:{provider_id}: {name} (default: {default_model})")
        else:
            lines.append("")
            lines.append("No custom providers configured.")
            lines.append("Create ~/.opencortex/providers.json to add custom providers.")

        return "\n".join(lines)
