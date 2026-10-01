"""
Typer CLI entrypoint for the AutonomousQA Agent.
All commands print Rich-formatted output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import RunData

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

load_dotenv()

app = typer.Typer(
    name="qa-agent",
    help="🤖 AutonomousQA Agent — local-LLM autonomous web testing",
    rich_markup_mode="rich",
)
console = Console()


def _setup_logging(level: str) -> None:
    """Configure logging level from string."""
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


def _make_run_id() -> str:
    """Generate a timestamped run ID."""
    return f"run_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"


def _get_reports_dir() -> Path:
    """Get reports directory from env or default."""
    return Path(os.getenv("QA_REPORTS_DIR", "reports"))


async def _full_run(
    url: str,
    depth: int,
    browsers: list[str],
    headless: bool,
    a11y: bool,
    visual_diff: bool,
    interactive: bool,
    log_level: str,
    srs_path: str = "",
    pen_path: str = "",
) -> None:
    """Full orchestrated agent run."""
    from src.agent.crawler import SiteCrawler
    from src.agent.executor import TestExecutor
    from src.agent.flow_inferencer import FlowInferencer
    from src.agent.test_generator import TestGenerator
    from src.analysis.accessibility import AccessibilityAuditor
    from src.analysis.severity_scorer import SeverityScorer
    from src.analysis.visual_diff import VisualDiffer
    from src.cli_bridge import PlaywrightCLI
    from src.models import AgentConfig, RunData
    from src.reporting.html_reporter import HTMLReporter
    from src.reporting.json_reporter import JSONReporter
    from src.reporting.excel_reporter import ExcelReporter
    from src.reporting.pdf_reporter import PDFReporter
    from src.qa.planner import QAPlanner
    from src.qa.design_compare import DesignComparator
    from src.qa.exploratory import ExploratoryAgent

    model = os.getenv("QA_MODEL", "qwen3:8b")
    config = AgentConfig(
        url=url,
        max_depth=depth,
        browsers=browsers,
        headless=headless,
        a11y=a11y,
        visual_diff=visual_diff,
        interactive=interactive,
        run_id=_make_run_id(),
        reports_dir=_get_reports_dir(),
        model=model,
        log_level=log_level,
    )

    run_dir = config.reports_dir / config.run_id
    srs_context = Path(srs_path).read_text(encoding="utf-8") if srs_path else ""
    design_context = Path(pen_path).read_text(encoding="utf-8") if pen_path else ""
    users_path = Path(os.getenv("QA_USERS_FILE", "qa-users.json"))
    users_context = users_path.read_text(encoding="utf-8") if users_path.exists() else ""
    if users_context:
        srs_context += "\n\nTEST USERS / ROLES:\n" + users_context[:8000]
    if srs_context:
        (run_dir / "srs_input.md").write_text(srs_context, encoding="utf-8")
    if design_context:
        (run_dir / "design_input.pen").write_text(design_context, encoding="utf-8")
    run_dir.mkdir(parents=True, exist_ok=True)

    run_data = RunData(
        run_id=config.run_id,
        config=config,
        started_at=datetime.now(UTC),
        run_dir=run_dir,
    )

    from src.llm.ollama import OllamaClient, OllamaError
    llm = OllamaClient()
    try:
        await llm.ensure_model(model)
    except OllamaError as exc:
        console.print(f"[red]✗ Local LLM unavailable: {exc}[/red]")
        raise typer.Exit(1) from exc

    cli = PlaywrightCLI()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:

        # STEP 1: Get playwright version
        task = progress.add_task("[1/13] Getting Playwright version...", total=None)
        try:
            run_data.playwright_version = await cli.get_version()
            progress.update(task, description=f"[1/13] Playwright {run_data.playwright_version}")
        except Exception as exc:
            console.print(f"[yellow]⚠ Could not get playwright version: {exc}[/yellow]")
        progress.remove_task(task)

        # STEP 2: Install browsers
        task = progress.add_task("[2/13] Verifying browsers...", total=None)
        try:
            await cli.install_browsers(browsers)
            progress.update(task, description=f"[2/13] Browsers ready: {', '.join(browsers)}")
        except Exception as exc:
            console.print(f"[yellow]⚠ Browser install warning: {exc}[/yellow]")
        progress.remove_task(task)

        # STEP 3: Codegen scaffold
        task = progress.add_task("[3/13] Running codegen scaffold...", total=None)
        codegen_script = ""
        try:
            codegen_result = await cli.codegen(url, run_dir / "codegen_script.py")
            run_data.codegen_result = codegen_result
            if codegen_result.script_path.exists():
                codegen_script = codegen_result.script_path.read_text()
            progress.update(task, description=f"[3/13] Codegen: {codegen_result.actions_recorded} actions")
        except Exception as exc:
            console.print(f"[yellow]⚠ Codegen skipped: {exc}[/yellow]")
        progress.remove_task(task)

        # STEP 4: HAR capture
        task = progress.add_task("[4/13] Capturing HAR traffic...", total=None)
        try:
            har_result = await cli.save_har(url, run_dir / "traffic.har")
            run_data.har_result = har_result
            progress.update(task, description=f"[4/13] HAR: {har_result.request_count} requests")
        except Exception as exc:
            console.print(f"[yellow]⚠ HAR capture skipped: {exc}[/yellow]")
        progress.remove_task(task)

        # STEP 5: BFS Crawl
        task = progress.add_task("[5/13] Crawling web app...", total=None)
        try:
            crawler = SiteCrawler(cli=cli)
            crawl_result = await crawler.crawl(
                url=url,
                max_depth=depth,
                browser_type=browsers[0],
                run_dir=run_dir,
                headless=headless,
            )
            run_data.crawl_result = crawl_result
            progress.update(
                task,
                description=f"[5/13] Crawled {crawl_result.total_pages} pages"
                + (f" ({len(crawl_result.errors)} errors)" if crawl_result.errors else ""),
            )
        except Exception as exc:
            console.print(f"[red]✗ Crawl failed: {exc}[/red]")
            raise typer.Exit(1) from exc
        progress.remove_task(task)

        # STEP 6: Flow inference
        task = progress.add_task("[6/13] Inferring user flows with AI...", total=None)
        try:
            from src.llm.ollama import OllamaClient
            client = OllamaClient()
            inferencer = FlowInferencer(client=client, model=model)
            flows = await inferencer.infer(crawl_result, codegen_script, srs_context=srs_context, design_context=design_context)
            run_data.flows = flows
            progress.update(task, description=f"[6/13] {len(flows)} user flows inferred")
        except Exception as exc:
            console.print(f"[yellow]⚠ Flow inference failed: {exc}[/yellow]")
            flows = []
        progress.remove_task(task)

        # STEP 7: Adversarial scenario expansion
        task = progress.add_task("[7/14] Expanding adversarial QA scenarios...", total=None)
        try:
            planner = QAPlanner(client=OllamaClient(), model=model)
            scenarios = await planner.plan(
                url,
                crawl_result.model_dump(mode="json"),
                srs=srs_context,
                design=design_context,
            )
            (run_dir / "qa_scenarios.json").write_text(
                json.dumps(scenarios, indent=2, default=str), encoding="utf-8"
            )
            progress.update(task, description=f"[7/14] Planned {len(scenarios)} adversarial scenarios")
        except Exception as exc:
            console.print(f"[yellow]⚠ Scenario planning failed: {exc}[/yellow]")
            scenarios = []
        progress.remove_task(task)

        if scenarios:
            from src.models import UserFlow, FlowStep
            existing = {f.name.lower() for f in flows}
            for scenario in scenarios:
                name = str(scenario.get("title") or scenario.get("name") or "").strip()
                if not name or name.lower() in existing:
                    continue
                steps = [
                    FlowStep(
                        action=str(step.get("action", "assert")),
                        selector=str(step.get("selector", "")),
                        value=step.get("value"),
                        description=str(step.get("description", "")),
                        expected_result=str(step.get("expected_result", "")),
                    )
                    for step in scenario.get("steps", [])
                    if isinstance(step, dict)
                ]
                flows.append(UserFlow(
                    name=name,
                    priority=str(scenario.get("priority", "MEDIUM")),
                    description=str(scenario.get("description", "")),
                    preconditions=[str(x) for x in scenario.get("preconditions", [])],
                    steps=steps,
                    expected_outcome=str(scenario.get("expected", scenario.get("expected_outcome", ""))),
                    test_data=scenario.get("test_data", {}) if isinstance(scenario.get("test_data", {}), dict) else {},
                ))
                existing.add(name.lower())
            run_data.flows = flows

                # STEP 9: Test generation
        task = progress.add_task("[9/16] Generating test code...", total=None)
        try:
            from src.llm.ollama import OllamaClient
            client = OllamaClient()
            generator = TestGenerator(client=client, model=model)
            test_suite = await generator.generate(flows, url, run_dir, srs_context=srs_context, design_context=design_context)
            run_data.test_suite = test_suite
            progress.update(
                task,
                description=f"[9/16] Generated {test_suite.test_count} tests"
                + (" ⚠ syntax errors" if not test_suite.syntax_valid else ""),
            )
        except Exception as exc:
            console.print(f"[yellow]⚠ Test generation failed: {exc}[/yellow]")
            test_suite = None
        progress.remove_task(task)

                # STEP 10: Execute tests
        task = progress.add_task("[10/16] Running tests...", total=None)
        execution_result = None
        if test_suite:
            try:
                executor = TestExecutor(cli=cli)
                execution_result = await executor.run(test_suite, config, run_dir)
                run_data.execution_result = execution_result
                progress.update(
                    task,
                    description=f"[10/16] Tests: {execution_result.passed}/{execution_result.total} passed",
                )
            except Exception as exc:
                console.print(f"[yellow]⚠ Test execution error: {exc}[/yellow]")
        else:
            progress.update(task, description="[10/16] Tests: skipped (no suite)")
        progress.remove_task(task)

                # STEP 11: Accessibility audit
        if a11y and run_data.crawl_result:
            task = progress.add_task("[11/16] Auditing accessibility...", total=None)
            try:
                auditor = AccessibilityAuditor()
                a11y_report = await auditor.audit(
                    run_data.crawl_result.pages, browser_type=browsers[0]
                )
                run_data.a11y_report = a11y_report
                progress.update(
                    task,
                    description=f"[11/16] WCAG score: {a11y_report.wcag_score:.0f}/100 ({a11y_report.total_violations} violations)",
                )
            except Exception as exc:
                console.print(f"[yellow]⚠ Accessibility audit failed: {exc}[/yellow]")
            progress.remove_task(task)

                # STEP 12: Design vs live semantic comparison
        if design_context and run_data.crawl_result:
            try:
                comparator = DesignComparator()
                design_doc = comparator.load_pen(Path(pen_path))
                live_pages = [p.model_dump(mode="json") for p in run_data.crawl_result.pages]
                comparison = comparator.compare(design_doc, live_pages)
                (run_dir / "design_comparison.json").write_text(
                    json.dumps(comparison, indent=2, default=str), encoding="utf-8"
                )
            except Exception as exc:
                console.print(f"[yellow]⚠ Design comparison failed: {exc}[/yellow]")

                # STEP 13: Visual diff
        if visual_diff and run_data.crawl_result:
            task = progress.add_task("[13/16] Computing visual diffs...", total=None)
            try:
                differ = VisualDiffer(cli=cli)
                before_map = await differ.capture_baseline(run_data.crawl_result.pages, run_dir)
                after_map = await differ.capture_after(run_data.crawl_result.pages, run_dir)
                vdiff = await differ.diff(before_map, after_map, run_dir)
                run_data.visual_diff_result = vdiff
                progress.update(
                    task,
                    description=f"[13/16] Visual diff: {vdiff.pages_changed}/{vdiff.total_pages} pages changed",
                )
            except Exception as exc:
                console.print(f"[yellow]⚠ Visual diff failed: {exc}[/yellow]")
            progress.remove_task(task)

                # STEP 14: Severity scoring
        if execution_result and execution_result.failed > 0:
            task = progress.add_task("[14/16] Scoring failure severity...", total=None)
            try:
                from src.llm.ollama import OllamaClient
                client = OllamaClient()
                scorer = SeverityScorer(client=client, model=model)
                scored = await scorer.score(
                    execution_result,
                    target_url=url,
                    generated_tests_path=run_dir / "generated_tests.py",
                )
                run_data.scored_failures = scored
                # Build severity breakdown
                for sf in scored:
                    sev = sf.severity.upper()
                    if sev in run_data.severity_breakdown:
                        run_data.severity_breakdown[sev] += 1
                progress.update(task, description=f"[14/16] Severity scored: {len(scored)} failures")
            except Exception as exc:
                console.print(f"[yellow]⚠ Severity scoring failed: {exc}[/yellow]")
            progress.remove_task(task)

                # STEP 15: Generate reports
        task = progress.add_task("[15/16] Generating reports...", total=None)
        run_data.finished_at = datetime.now(UTC)
        try:
            html_path = HTMLReporter().generate(run_data)
            json_path = JSONReporter().generate(run_data)
            ExcelReporter().generate(run_data)
            PDFReporter().generate(run_data)
            progress.update(task, description="[15/16] HTML + JSON + Excel + PDF reports saved")
        except Exception as exc:
            console.print(f"[red]✗ Report generation failed: {exc}[/red]")
            raise typer.Exit(1) from exc
        progress.remove_task(task)

                # STEP 16: Trace viewer
        if interactive and execution_result and execution_result.failed > 0:
            task = progress.add_task("[16/16] Opening trace viewer...", total=None)
            failed_with_trace = [
                t for t in execution_result.tests if t.status == "failed" and t.trace_path
            ]
            if failed_with_trace:
                await cli.show_trace(failed_with_trace[0].trace_path)  # type: ignore[arg-type]
            progress.remove_task(task)

    # Final summary table
    console.print()
    _print_summary(run_data, html_path, json_path)


def _print_summary(run_data: RunData, html_path: Path, json_path: Path) -> None:
    """Print the final run summary table."""

    exec_result = run_data.execution_result
    total = exec_result.total if exec_result else 0
    passed = exec_result.passed if exec_result else 0
    failed = exec_result.failed if exec_result else 0

    # Summary panel
    pass_rate = run_data.pass_rate
    color = "green" if pass_rate == 100 else "yellow" if pass_rate >= 70 else "red"

    table = Table(title=f"QA Run Summary — {run_data.run_id}", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="dim", width=24)
    table.add_column("Value", width=40)

    table.add_row("URL", run_data.config.url)
    table.add_row("Duration", f"{run_data.duration_seconds:.1f}s")
    table.add_row("Pages Crawled", str(run_data.crawl_result.total_pages if run_data.crawl_result else 0))
    table.add_row("Flows Inferred", str(len(run_data.flows)))
    table.add_row("Tests Run", str(total))
    table.add_row("Passed", f"[green]{passed}[/green]")
    table.add_row("Failed", f"[red]{failed}[/red]")
    table.add_row("Pass Rate", f"[{color}]{pass_rate:.1f}%[/{color}]")

    sev = run_data.severity_breakdown
    table.add_row(
        "Severity",
        f"[red]CRITICAL:{sev.get('CRITICAL',0)}[/red] "
        f"[yellow]HIGH:{sev.get('HIGH',0)}[/yellow] "
        f"MEDIUM:{sev.get('MEDIUM',0)} LOW:{sev.get('LOW',0)}",
    )

    if run_data.a11y_report:
        table.add_row("WCAG Score", f"{run_data.a11y_report.wcag_score:.0f}/100")

    console.print(table)
    console.print()
    console.print(f"[bold green]✓ Report saved to:[/bold green] {html_path}")
    console.print(f"[bold green]✓ JSON saved to:[/bold green]   {json_path}")
    excel_path = run_data.run_dir / "execution-report.xlsx"
    pdf_path = run_data.run_dir / "final-report.pdf"
    if excel_path.exists():
        console.print(f"[bold green]✓ Excel saved to:[/bold green]  {excel_path}")
    if pdf_path.exists():
        console.print(f"[bold green]✓ PDF saved to:[/bold green]    {pdf_path}")
    excel_path = run_data.run_dir / "execution-report.xlsx"
    pdf_path = run_data.run_dir / "final-report.pdf"
    if excel_path.exists():
        console.print(f"[bold green]✓ Excel saved to:[/bold green]  {excel_path}")
    if pdf_path.exists():
        console.print(f"[bold green]✓ PDF saved to:[/bold green]    {pdf_path}")


@app.command()
def run(
    url: str = typer.Option("", "--url", "-u", help="Target web app URL"),
    depth: int = typer.Option(int(os.getenv("QA_MAX_DEPTH", "3")), "--depth", "-d", help="BFS crawl depth"),
    browsers: str = typer.Option(os.getenv("QA_BROWSERS", "chromium"), "--browsers", "-b", help="Comma-separated browser list"),
    headed: bool = typer.Option(False, "--headed", help="Run in headed (visible) mode", is_flag=True),
    no_a11y: bool = typer.Option(False, "--no-a11y", help="Disable accessibility audit", is_flag=True),
    visual_diff: bool = typer.Option(False, "--visual-diff", help="Capture visual diffs", is_flag=True),
    interactive: bool = typer.Option(False, "--interactive", help="Open trace viewer on failure", is_flag=True),
    log_level: str = typer.Option(os.getenv("QA_LOG_LEVEL", "INFO"), "--log-level", help="Logging level"),
    srs: str = typer.Option("", "--srs", help="Optional SRS/requirements file"),
    pen: str = typer.Option("", "--pen", help="Optional .pen UI design file"),
) -> None:
    """
    Run the full autonomous QA agent against a URL.

    Example: qa-agent run --url https://example.com --depth 3 --a11y
    """
    if not url:
        console.print("[red]Error: --url is required[/red]")
        raise typer.Exit(1)

    _setup_logging(log_level)

    headless = not headed
    a11y = not no_a11y
    browser_list = [b.strip() for b in browsers.split(",") if b.strip()]

    console.print(
        Panel(
            f"[bold]🤖 AutonomousQA Agent[/bold]\n"
            f"[dim]URL:[/dim] {url}\n"
            f"[dim]Depth:[/dim] {depth} | "
            f"[dim]Browsers:[/dim] {', '.join(browser_list)} | "
            f"[dim]Headless:[/dim] {headless} | "
            f"[dim]A11y:[/dim] {a11y} | [dim]SRS:[/dim] {bool(srs)} | [dim].pen:[/dim] {bool(pen)}",
            border_style="cyan",
        )
    )

    asyncio.run(
        _full_run(
            url=url,
            depth=depth,
            browsers=browser_list,
            headless=headless,
            a11y=a11y,
            visual_diff=visual_diff,
            interactive=interactive,
            log_level=log_level,
            srs_path=srs,
            pen_path=pen,
        )
    )


@app.command()
def codegen(
    url: str = typer.Argument(help="Target URL for codegen session"),
) -> None:
    """
    Run Playwright codegen against a URL and save the scaffold.

    Example: qa-agent codegen http://localhost:5000
    """
    from src.cli_bridge import PlaywrightCLI

    _setup_logging("INFO")

    async def _run() -> None:
        cli = PlaywrightCLI()
        reports_dir = _get_reports_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = reports_dir / f"codegen_{timestamp}.py"

        console.print(f"[cyan]Starting codegen for {url}...[/cyan]")
        result = await cli.codegen(url, output_path)
        console.print(f"[green]✓ Codegen saved to: {result.script_path}[/green]")
        console.print(f"  Actions recorded: {result.actions_recorded}")

    asyncio.run(_run())


@app.command()
def screenshot(
    url: str = typer.Argument(help="URL to screenshot"),
    output: str = typer.Option("", "--output", "-o", help="Output PNG path"),
) -> None:
    """
    Capture a full-page screenshot of a URL.

    Example: qa-agent screenshot https://example.com --output screen.png
    """
    from src.cli_bridge import PlaywrightCLI

    _setup_logging("INFO")

    async def _run() -> None:
        cli = PlaywrightCLI()
        output_path = Path(output) if output else _get_reports_dir() / "screenshot.png"
        result = await cli.screenshot(url, output_path, full_page=True)
        console.print(f"[green]✓ Screenshot saved: {result.path} ({result.file_size_kb:.1f} KB)[/green]")

    asyncio.run(_run())


@app.command()
def report(
    last: bool = typer.Option(False, "--last", help="Open the most recent report"),
    list_all: bool = typer.Option(False, "--list", help="List all saved reports"),
) -> None:
    """
    Manage saved QA reports.

    qa-agent report --last     → opens most recent report in browser
    qa-agent report --list     → lists all reports with summaries
    """
    reports_dir = _get_reports_dir()

    if last:
        run_dirs = sorted(
            [d for d in reports_dir.iterdir() if d.is_dir() and d.name.startswith("run_")],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        if not run_dirs:
            console.print("[yellow]No reports found[/yellow]")
            raise typer.Exit(1)

        html_path = run_dirs[0] / "report.html"
        if html_path.exists():
            console.print(f"[green]Opening: {html_path}[/green]")
            webbrowser.open(str(html_path.absolute()))
        else:
            console.print(f"[red]Report not found: {html_path}[/red]")

    elif list_all:
        run_dirs = sorted(
            [d for d in reports_dir.iterdir() if d.is_dir() and d.name.startswith("run_")],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        table = Table(title="QA Reports", header_style="bold cyan")
        table.add_column("Run ID", width=24)
        table.add_column("URL", width=40)
        table.add_column("Pass Rate", width=12)
        table.add_column("Severity", width=24)

        for run_dir in run_dirs:
            json_path = run_dir / "report.json"
            if json_path.exists():
                try:
                    data = json.loads(json_path.read_text())
                    summary = data.get("summary", {})
                    sev = summary.get("severity_breakdown", {})
                    table.add_row(
                        data.get("run_id", run_dir.name),
                        data.get("url", "—")[:38],
                        f"{summary.get('pass_rate', 0):.0f}%",
                        f"C:{sev.get('CRITICAL',0)} H:{sev.get('HIGH',0)} M:{sev.get('MEDIUM',0)} L:{sev.get('LOW',0)}",
                    )
                except Exception:
                    table.add_row(run_dir.name, "—", "—", "—")

        console.print(table)


@app.command()
def clean() -> None:
    """Delete all contents of the reports directory (with confirmation)."""
    reports_dir = _get_reports_dir()
    run_dirs = [d for d in reports_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]

    if not run_dirs:
        console.print("[yellow]No run directories to clean[/yellow]")
        return

    confirmed = typer.confirm(f"Delete {len(run_dirs)} run director{'ies' if len(run_dirs) > 1 else 'y'}?")
    if confirmed:
        import shutil
        for d in run_dirs:
            shutil.rmtree(d)
        console.print(f"[green]✓ Deleted {len(run_dirs)} run directories[/green]")
    else:
        console.print("[dim]Cancelled[/dim]")


@app.command()
def install_browsers() -> None:
    """Install all Playwright browsers (chromium, firefox, webkit)."""
    from src.cli_bridge import PlaywrightCLI

    _setup_logging("INFO")

    async def _run() -> None:
        cli = PlaywrightCLI()
        console.print("[cyan]Installing browsers...[/cyan]")
        result = await cli.install_browsers(["chromium", "firefox", "webkit"])
        console.print(f"[green]✓ Installed: {', '.join(result.browsers_installed)}[/green]")
        console.print(f"  Version: {result.version}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
