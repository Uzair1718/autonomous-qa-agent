"""AI flow inference with optional run-specific QA context."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from src.models import CrawlResult, FlowStep, UserFlow

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent.parent.parent / ".claude" / "skills" / "ui-tester" / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / name
    return path.read_text() if path.exists() else ""


def _extract_system_prompt(content: str) -> str:
    lines = content.splitlines()
    out: list[str] = []
    active = False
    for line in lines:
        if line.strip() == "## System Prompt":
            active = True
            continue
        if active and line.startswith("## "):
            break
        if active:
            out.append(line)
    return "\n".join(out).strip()


class FlowInferencer:
    def __init__(self, client: AsyncOpenAI | None = None, model: str = "gpt-4o-mini") -> None:
        self._client = client or AsyncOpenAI()
        self._model = model

    def _deduplicate_flows(self, flows: list[UserFlow]) -> list[UserFlow]:
        seen: set[str] = set()
        unique: list[UserFlow] = []
        for flow in flows:
            sig = "|".join(f"{s.action}:{s.selector}" for s in flow.steps)
            if sig not in seen:
                seen.add(sig)
                unique.append(flow)
        return unique

    def _parse_flows(self, raw_json: str) -> list[UserFlow]:
        raw_json = raw_json.strip()
        fence = chr(96) * 3
        if raw_json.startswith(fence):
            lines = raw_json.splitlines()
            raw_json = "\n".join(lines[1:-1])
        data = json.loads(raw_json)
        if not isinstance(data, list):
            raise ValueError("Expected a JSON array")
        return [
            UserFlow(
                name=item.get("name", "Unnamed Flow"),
                priority=item.get("priority", "MEDIUM"),
                description=item.get("description", ""),
                preconditions=item.get("preconditions", []),
                steps=[FlowStep(**s) for s in item.get("steps", [])],
                expected_outcome=item.get("expected_outcome", ""),
                test_data=item.get("test_data", {}),
            )
            for item in data
        ]

    async def infer(
        self,
        crawl_result: CrawlResult,
        codegen_script: str = "",
        extra_context: str = "",
    ) -> list[UserFlow]:
        system_prompt = _extract_system_prompt(_load_prompt("infer_flows.md"))
        system_prompt = system_prompt or (
            "You are an expert SDET. Infer deterministic, safe web QA flows. "
            "Return only a JSON array."
        )

        crawl_data = crawl_result.model_dump(mode="json")
        user_content = (
            f"Base URL: {crawl_result.base_url}\n\n"
            f"QA RUN CONTEXT:\n{extra_context[:12000]}\n\n"
            f"Codegen Scaffold:\n{codegen_script[:3000]}\n\n"
            f"Crawl Result:\n{json.dumps(crawl_data, indent=2)[:16000]}\n\n"
            "Generate broad end-to-end QA flows covering positive, negative, validation, "
            "navigation, permissions/authentication, and edge cases. Never invent unsupported "
            "selectors. Do not perform destructive actions."
        )

        for attempt in range(2):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    temperature=0,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                )
                flows = self._deduplicate_flows(
                    self._parse_flows(response.choices[0].message.content or "[]")
                )
                return sorted(
                    flows,
                    key=lambda f: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(f.priority, 1),
                )
            except Exception as exc:
                logger.warning("Flow inference attempt %d failed: %s", attempt + 1, exc)
                user_content += "\nReturn raw JSON only."
        return []
