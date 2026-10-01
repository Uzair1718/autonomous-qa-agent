"""Excel QA report exporter."""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from src.models import RunData


class ExcelReporter:
    """Export execution, scenario, bug, and summary data to Excel."""

    def generate(self, run_data: RunData) -> Path:
        out = run_data.run_dir / "execution-report.xlsx"
        workbook = Workbook()

        tests = workbook.active
        tests.title = "Test Cases"
        headers = ["Test Name", "Status", "Duration (s)", "Page URL", "Error"]
        tests.append(headers)
        for cell in tests[1]:
            cell.font = Font(bold=True)

        execution = run_data.execution_result
        for test in execution.tests if execution else []:
            tests.append(
                [
                    test.name,
                    test.status,
                    round(test.duration, 3),
                    test.page_url,
                    test.error_message,
                ]
            )

        bugs = workbook.create_sheet("Bugs")
        bug_headers = [
            "Bug ID", "Bug Name", "Issue", "Steps to Reproduce", "Expected Result",
            "Actual Result", "Severity", "Priority", "Page", "Browser", "User Role",
            "Screenshot", "Video", "Trace", "Console Error", "Status",
        ]
        bugs.append(bug_headers)
        for cell in bugs[1]:
            cell.font = Font(bold=True)

        for index, failure in enumerate(run_data.scored_failures, 1):
            original = next(
                (
                    test
                    for test in (execution.tests if execution else [])
                    if test.name == failure.test_name
                ),
                None,
            )
            bugs.append(
                [
                    f"BUG-{index:03d}",
                    failure.test_name,
                    failure.reason,
                    "\n".join(failure.reproduction_steps),
                    "Expected behavior per test flow",
                    original.error_message if original else failure.original_error,
                    failure.severity,
                    failure.severity,
                    original.page_url if original else "",
                    run_data.config.browsers[0] if run_data.config.browsers else "",
                    "",
                    "",
                    "",
                    str(original.trace_path) if original and original.trace_path else "",
                    "",
                    "Open",
                ]
            )

        scenarios = workbook.create_sheet("Test Scenarios")
        scenarios.append(["Scenario", "Priority", "Description", "Expected Outcome"])
        for cell in scenarios[1]:
            cell.font = Font(bold=True)
        for flow in run_data.flows:
            scenarios.append(
                [flow.name, flow.priority, flow.description, flow.expected_outcome]
            )

        summary = workbook.create_sheet("Summary")
        summary.append(["Metric", "Value"])
        summary["A1"].font = summary["B1"].font = Font(bold=True)
        summary.append(["URL", run_data.config.url])
        summary.append(["Pages", run_data.crawl_result.total_pages if run_data.crawl_result else 0])
        summary.append(["Flows", len(run_data.flows)])
        summary.append(["Tests", execution.total if execution else 0])
        summary.append(["Passed", execution.passed if execution else 0])
        summary.append(["Failed", execution.failed if execution else 0])
        summary.append(["Pass Rate", round(run_data.pass_rate, 2)])

        for sheet in workbook.worksheets:
            for column in sheet.columns:
                letter = column[0].column_letter
                width = max((len(str(cell.value or "")) for cell in column), default=10) + 2
                sheet.column_dimensions[letter].width = min(max(width, 12), 60)

        workbook.save(out)
        return out
