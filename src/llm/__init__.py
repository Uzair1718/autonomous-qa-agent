"""Local LLM integrations."""

from .ollama import OllamaClient, OllamaError

__all__ = ["OllamaClient", "OllamaError"]
