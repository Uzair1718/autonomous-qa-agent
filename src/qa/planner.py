"""Local-LLM QA planning and adversarial scenario expansion."""
from __future__ import annotations
import json
from typing import Any
from src.llm.ollama import OllamaClient

DEFAULT_CATEGORIES = [
    "happy_path","negative_validation","authentication_authorization","rbac",
    "crud","search_filter_pagination","uploads_downloads","notifications",
    "payments","refresh_back_forward","duplicate_submission","direct_url_access",
    "expired_session","network_failure","responsive","accessibility","arabic_rtl",
    "console_network_errors","business_rules","boundary_values"
]

class QAPlanner:
    def __init__(self, client: Any | None = None, model: str = "qwen3:8b") -> None:
        self.client = client or OllamaClient()
        self.model = model

    async def plan(self, url: str, crawl: dict, srs: str = "", design: str = "", categories: list[str] | None = None) -> list[dict[str, Any]]:
        cats = categories or DEFAULT_CATEGORIES
        system = """You are a senior SDET planning adversarial web QA. Produce executable test scenarios, not vague advice.
Cover happy paths and ways the product can break. Never invent an observed defect; mark assumptions as assumptions.
Return only JSON array. Each item: id, category, title, priority, preconditions, steps, expected, test_data."""
        user = f"URL: {url}\nCategories: {json.dumps(cats)}\nSRS:\n{srs[:16000]}\nDESIGN (.pen):\n{design[:16000]}\nCRAWL:\n{json.dumps(crawl)[:12000]}"
        r = await self.client.chat.completions.create(model=self.model,temperature=0,messages=[{"role":"system","content":system},{"role":"user","content":user}],response_format={"type":"json_object"})
        raw = r.choices[0].message.content or "[]"
        data = json.loads(raw)
        if isinstance(data, dict):
            data = data.get("scenarios", data.get("tests", []))
        return data if isinstance(data,list) else []
