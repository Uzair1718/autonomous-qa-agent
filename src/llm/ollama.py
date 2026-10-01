"""Local Ollama LLM client with an OpenAI-compatible async chat interface.

This keeps the existing QA agent modules provider-agnostic while removing any
runtime dependency on the OpenAI SDK/API.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import httpx


class OllamaError(RuntimeError):
    """Raised when the local Ollama service cannot answer a request."""


class _ChatCompletions:
    def __init__(self, client: "OllamaClient") -> None:
        self._client = client

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0,
        **kwargs: Any,
    ) -> Any:
        return await self._client._chat(
            model=model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )


class OllamaClient:
    """Small async client for Ollama's native /api/chat endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout or float(os.getenv("OLLAMA_TIMEOUT", "180"))
        self.chat_completions = _ChatCompletions(self)
        # Compatibility shape used by the existing agent modules:
        self.chat = SimpleNamespace(completions=self.chat_completions)

    async def _chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0,
        **kwargs: Any,
    ) -> Any:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        # Ollama accepts format=json when structured JSON is requested.
        if kwargs.get("response_format") or kwargs.get("format") == "json":
            payload["format"] = "json"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError(
                f"Could not reach Ollama at {self.base_url}. "
                f"Start Ollama and run 'ollama pull {model}'. Details: {exc}"
            ) from exc

        content = data.get("message", {}).get("content", "")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    async def health(self) -> bool:
        """Return True when Ollama is reachable."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True
        except httpx.HTTPError:
            return False

    async def list_models(self) -> list[str]:
        """List locally available Ollama model names."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OllamaError(
                f"Could not reach Ollama at {self.base_url}. "
                "Start Ollama with 'ollama serve'. Details: "
                f"{exc}"
            ) from exc
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    async def ensure_model(self, model: str) -> None:
        """Fail with an actionable message if the configured model is absent."""
        models = await self.list_models()
        if model not in models:
            raise OllamaError(
                f"Model '{model}' is not installed locally. Run: ollama pull {model}"
            )
