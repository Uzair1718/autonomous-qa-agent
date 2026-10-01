from unittest.mock import AsyncMock, patch
import httpx
import pytest
from src.llm.ollama import OllamaClient, OllamaError

@pytest.mark.asyncio
async def test_ollama_chat_maps_response():
    response=httpx.Response(200,json={"message":{"content":"hello"}})
    response.request=httpx.Request("POST","http://localhost:11434/api/chat")
    with patch("httpx.AsyncClient.post",new=AsyncMock(return_value=response)):
        client=OllamaClient("http://localhost:11434")
        result=await client.chat.completions.create(model="qwen3:8b",messages=[{"role":"user","content":"hi"}])
    assert result.choices[0].message.content=="hello"

@pytest.mark.asyncio
async def test_ensure_model_rejects_missing():
    client=OllamaClient()
    client.list_models=AsyncMock(return_value=["llama3:8b"])
    with pytest.raises(OllamaError,match="ollama pull qwen3:8b"):
        await client.ensure_model("qwen3:8b")

@pytest.mark.asyncio
async def test_health_returns_false_on_network_error():
    client=OllamaClient()
    with patch("httpx.AsyncClient.get",new=AsyncMock(side_effect=httpx.ConnectError("down"))):
        assert await client.health() is False
