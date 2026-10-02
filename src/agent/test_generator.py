"""Generate executable Playwright tests from inferred QA flows."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

from openai import AsyncOpenAI

from src.models import GeneratedTestSuite, UserFlow

logger = logging.getLogger(__name__)
_PROMPTS_DIR = Path(__file__).parent.parent.parent / ".claude" / "skills" / "ui-tester" / "prompts"


def _load_system_prompt(filename: str) -> str:
    path = _PROMPTS_DIR / filename
    if not path.exists():
        return "You are an expert SDET. Generate only valid pytest Playwright Python code."
    content = path.read_text()
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


def _extract_python_code(raw: str) -> str:
    raw = raw.strip()
    fence = chr(96) * 3
    if raw.startswith(fence):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1])
    return raw.strip()


def _count_test_functions(code: str) -> int:
    try:
        return sum(
            1 for node in ast.walk(ast.parse(code))
            if isinstance(node, ast.AsyncFunctionDef) and node.name.startswith("test_")
        )
    except SyntaxError:
        return 0


def _extract_page_objects(code: str) -> list[str]:
    try:
        return [
            node.name for node in ast.walk(ast.parse(code))
            if isinstance(node, ast.ClassDef) and node.name.endswith("Page")
        ]
    except SyntaxError:
        return []


class TestGenerator:
    def __init__(self, client: AsyncOpenAI | None = None, model: str = "gpt-4o-mini") -> None:
        self._client = client or AsyncOpenAI()
        self._model = model

    async def _call(
        self,
        flows: list[UserFlow],
        base_url: str,
        extra_context: str = "",
        retry_hint: str = "",
    ) -> str:
        system = _load_system_prompt("generate_tests.md")
        flows_json = json.dumps([f.model_dump(mode="json") for f in flows], indent=2)
        user = (
            f"Base URL: {base_url}\n"
            f"QA RUN CONTEXT:\n{extra_context[:12000]}\n\n"
            f"Flows:\n{flows_json}\n\n"
            "Generate one complete pytest + Playwright file. Use environment variables "
            "QA_ADMIN_URL, QA_ADMIN_USERNAME, QA_ADMIN_PASSWORD, QA_TEST_EMAIL and "
            "QA_TEST_PASSWORD when needed; never hard-code credentials. Only interact with "
            "the target websites. Do not delete data, send real messages, make payments, "
            "change production settings, or use subprocess/eval/exec. Add assertions for "
            "expected outcomes and use Playwright screenshots/traces on failures. Return only Python code."
        )
        if retry_hint:
            user += f"\nPrevious attempt failed: {retry_hint}"
        response = await self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        )
        return response.choices[0].message.content or ""

    async def generate(
        self,
        flows: list[UserFlow],
        base_url: str,
        run_dir: Path = Path("reports"),
        extra_context: str = "",
    ) -> GeneratedTestSuite:
        run_dir.mkdir(parents=True, exist_ok=True)
        output_path = run_dir / "generated_tests.py"
        errors: list[str] = []
        raw_code = ""

        for _attempt in range(2):
            try:
                raw_code = _extract_python_code(
                    await self._call(
                        flows,
                        base_url,
                        extra_context,
                        errors[-1] if errors else "",
                    )
                )
                ast.parse(raw_code)
                output_path.write_text(raw_code)
                return GeneratedTestSuite(
                    file_path=output_path,
                    test_count=_count_test_functions(raw_code),
                    page_objects=_extract_page_objects(raw_code),
                    syntax_valid=True,
                    generation_errors=errors,
                )
            except SyntaxError as exc:
                errors.append(f"SyntaxError line {exc.lineno}: {exc.msg}")
            except Exception as exc:
                errors.append(str(exc))
                break

        output_path.write_text(
            "# Test generation failed; see generated_tests.py.broken\n"
            "import pytest\n\n"
            "def test_generation_failed():\n"
            f"    pytest.skip({errors[-1] if errors else 'unknown error'!r})\n"
        )
        if raw_code:
            (run_dir / "generated_tests.py.broken").write_text(raw_code)
        return GeneratedTestSuite(
            file_path=output_path,
            test_count=0,
            syntax_valid=False,
            generation_errors=errors,
        )
