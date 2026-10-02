"""Provider-neutral OpenAI-compatible LLM client."""
from __future__ import annotations
import os
from openai import AsyncOpenAI

def create_llm_client() -> AsyncOpenAI:
    provider = os.getenv("LLM_PROVIDER", "openrouter").lower()
    if provider == "ollama":
        base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
        api_key = os.getenv("LLM_API_KEY", "ollama")
    elif provider == "lmstudio":
        base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:1234/v1")
        api_key = os.getenv("LLM_API_KEY", "lm-studio")
    elif provider in {"vllm", "openai-compatible"}:
        base_url = os.getenv("LLM_BASE_URL", "http://127.0.0.1:8000/v1")
        api_key = os.getenv("LLM_API_KEY", "local")
    else:
        base_url = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
        api_key = os.getenv("LLM_API_KEY", "")
    if not api_key:
        raise RuntimeError("LLM_API_KEY is required for the selected provider")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)

def llm_model() -> str:
    return os.getenv("LLM_MODEL", os.getenv("QA_MODEL", "openrouter/free"))
