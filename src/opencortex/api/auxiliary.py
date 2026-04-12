"""Auxiliary model client for cheap offloading of background tasks."""

from __future__ import annotations

import logging
from typing import Any, Protocol

log = logging.getLogger(__name__)


class AuxiliaryProvider(Protocol):
    """Minimal protocol for an LLM provider that can complete a chat."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system_prompt: str | None = None,
        max_tokens: int = 1000,
    ) -> str: ...


class AuxiliaryClient:
    """辅助模型池：旁路任务（压缩、搜索摘要、视觉分析）用廉价模型。

    支持配置多个辅助模型，有降级链。第一个失败自动切到下一个。

    Usage::

        client = AuxiliaryClient.from_config({
            "providers": [
                {"name": "haiku", "model": "claude-3-haiku", "api_key": "..."},
                {"name": "gpt-mini", "model": "gpt-4o-mini", "api_key": "..."},
            ]
        })
        summary = await client.summarize(long_text)
    """

    def __init__(self, providers: list[tuple[str, Any, str]] | None = None):
        # [(name, client_instance, model_id), ...]
        self._providers: list[tuple[str, Any, str]] = providers or []

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, provider_config: dict) -> AuxiliaryClient:
        """Build an AuxiliaryClient from a config dict.

        Expected shape::

            {
                "providers": [
                    {"name": "haiku", "model": "claude-3-haiku", "api_key": "..."},
                    # ... more providers for failover
                ]
            }
        """
        providers: list[tuple[str, Any, str]] = []
        for entry in provider_config.get("providers", []):
            name = entry.get("name", "unknown")
            model = entry.get("model", "")
            # Try to build an OpenAI-compatible async client
            api_key = entry.get("api_key") or entry.get("api_base")
            base_url = entry.get("base_url") or entry.get("api_base")
            if api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
                    providers.append((name, client, model))
                    log.info("Auxiliary provider registered: %s (%s)", name, model)
                except ImportError:
                    log.warning("openai package not installed, skipping provider %s", name)
            else:
                log.warning("No api_key for auxiliary provider %s, skipping", name)

        return cls(providers)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Return True if at least one provider is configured."""
        return len(self._providers) > 0

    async def _call_openai(
        self,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        system_prompt: str | None,
        max_tokens: int,
    ) -> str:
        """Call an OpenAI-compatible chat completion endpoint."""
        msg_list = []
        if system_prompt:
            msg_list.append({"role": "system", "content": system_prompt})
        msg_list.extend(messages)

        resp = await client.chat.completions.create(
            model=model,
            messages=msg_list,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def _call(
        self,
        client: Any,
        model: str,
        messages: list[dict[str, str]],
        system_prompt: str | None,
        max_tokens: int,
    ) -> str:
        """Dispatch to the appropriate call method based on client type."""
        # OpenAI AsyncClient
        if hasattr(client, "chat") and hasattr(client.chat, "completions"):
            return await self._call_openai(client, model, messages, system_prompt, max_tokens)

        # Duck-typing: if client has a `chat` coroutine matching the Protocol
        if callable(getattr(client, "chat", None)):
            return await client.chat(
                messages,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
            )

        raise TypeError(f"Unsupported auxiliary client type: {type(client)}")

    async def complete(
        self,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
        max_tokens: int = 1000,
    ) -> str:
        """用辅助模型完成文本任务。失败时自动降级到下一个 provider。"""
        last_error: Exception | None = None
        for name, client, model in self._providers:
            try:
                result = await self._call(client, model, messages, system_prompt, max_tokens)
                log.debug("Auxiliary task completed by %s (%s)", name, model)
                return result
            except Exception as exc:
                log.warning("Auxiliary provider %s failed: %s", name, exc)
                last_error = exc
                continue
        raise RuntimeError(f"All auxiliary providers failed (last: {last_error})")

    async def summarize(self, text: str, instruction: str = "Summarize concisely") -> str:
        """摘要任务。"""
        return await self.complete(
            [{"role": "user", "content": f"{instruction}:\n\n{text}"}],
        )


# Singleton for global access (set during app startup)
_instance: AuxiliaryClient | None = None


def get_auxiliary_client() -> AuxiliaryClient:
    """Return the global AuxiliaryClient singleton."""
    global _instance
    if _instance is None:
        _instance = AuxiliaryClient()  # empty — no providers
    return _instance


def set_auxiliary_client(client: AuxiliaryClient) -> None:
    """Set the global AuxiliaryClient singleton."""
    global _instance
    _instance = client
