"""Test executor for generated Playwright pytest suites."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from src.cli_bridge import PlaywrightCLI
from src.models import AgentConfig, ExecutionResult, GeneratedTestSuite, TestResult

logger = logging.getLogger(__name__)


class TestExecutor:
    """Runs generated pytest suites in an isolated subprocess."""

    def __init__(self, cli: PlaywrightCLI | None = None) -> None:
        self._cli = cli or PlaywrightCLI()

    def _parse_pytest_json(self, json_path: Path) -> list[TestResult]:
        if not json_path.exists():
            return []
        try:
            data = json.loads(json_path.read_text())
            results: list[TestResult] = []
            for test in data.get("tests", []):
                name = test.get("nodeid", "unknown").split("::")[-1]
                call = test.get("call", {})
                error_message = str(call.get("longrepr", ""))[:4000] if call else ""
                trace_path: Path | None = None
                for key in ("setup", "call", "teardown"):
                    for extra in test.get(key, {}).get("extra", []):
                        if extra.get("name") == "trace" and extra.get("url"):
                            trace_path = Path(extra["url"])
                            break
                results.append(TestResult(
                    name=name,
                    status=test.get("outcome", "unknown"),
                    duration=test.get("duration", 0.0),
                    error_message=error_message,
                    trace_path=trace_path,
                ))
            return results
        except (json.JSONDecodeError, KeyError) as exc:
            logger.error("Failed to parse pytest JSON: %s", exc)
            return []

    async def run(
        self,
        suite: GeneratedTestSuite,
        config: AgentConfig,
        run_dir: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> ExecutionResult:
        run_dir = run_dir or config.reports_dir / config.run_id
        (run_dir / "traces").mkdir(parents=True, exist_ok=True)
        json_report_path = (run_dir / "pytest_raw.json").resolve()

        cmd = [
            sys.executable, "-m", "pytest", str(suite.file_path.resolve()),
            "-v", "--tb=short", "--json-report",
            f"--json-report-file={json_report_path}",
            "--timeout=30", "-p", "no:base_url",
        ]
        if not config.headless:
            cmd.append("--headed")

        env = os.environ.copy()
        if extra_env:
            env.update(extra_env)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(suite.file_path.parent),
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=900.0
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
        except TimeoutError:
            stdout, stderr = "", "Timeout after 900s"
        except Exception as exc:
            stdout, stderr = "", str(exc)

        tests = self._parse_pytest_json(json_report_path)
        if not tests and stdout:
            tests = self._parse_stdout_fallback(stdout)

        result = ExecutionResult(
            total=len(tests),
            passed=sum(t.status == "passed" for t in tests),
            failed=sum(t.status == "failed" for t in tests),
            skipped=sum(t.status == "skipped" for t in tests),
            duration_seconds=sum(t.duration for t in tests),
            tests=tests,
            stdout=stdout,
            stderr=stderr,
            pytest_raw_path=json_report_path,
        )
        return result

    def _parse_stdout_fallback(self, stdout: str) -> list[TestResult]:
        results: list[TestResult] = []
        for line in stdout.splitlines():
            line = line.strip()
            for status in ("PASSED", "FAILED", "SKIPPED"):
                marker = f" {status}"
                if marker in line:
                    name = line.split(marker)[0].split("::")[-1].strip()
                    results.append(TestResult(name=name, status=status.lower()))
                    break
        return results
