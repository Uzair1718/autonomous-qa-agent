from datetime import UTC, datetime
from pathlib import Path
from src.models import AgentConfig, ExecutionResult, RunData, TestResult, UserFlow
from src.reporting.excel_reporter import ExcelReporter
from src.reporting.pdf_reporter import PDFReporter

def make_run(tmp_path: Path) -> RunData:
    config = AgentConfig(url="https://example.com", run_id="run_test", reports_dir=tmp_path)
    return RunData(
        run_id="run_test",
        config=config,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        run_dir=tmp_path,
        flows=[UserFlow(name="Login", steps=[])],
        execution_result=ExecutionResult(
            total=1, passed=1, tests=[TestResult(name="test_login", status="passed")]
        ),
    )

def test_excel_reporter_creates_workbook(tmp_path: Path) -> None:
    path = ExcelReporter().generate(make_run(tmp_path))
    assert path.exists()
    assert path.stat().st_size > 0

def test_pdf_reporter_creates_pdf(tmp_path: Path) -> None:
    path = PDFReporter().generate(make_run(tmp_path))
    assert path.exists()
    assert path.stat().st_size > 0
