"""PDF summary exporter using ReportLab."""
from __future__ import annotations
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from src.models import RunData

class PDFReporter:
    def generate(self, run_data: RunData) -> Path:
        out = run_data.run_dir / "final-report.pdf"
        doc = SimpleDocTemplate(str(out), pagesize=A4, rightMargin=36,leftMargin=36,topMargin=36,bottomMargin=36)
        styles = getSampleStyleSheet()
        story = [Paragraph("Autonomous QA Final Report", styles["Title"]), Spacer(1,12),
                 Paragraph(f"URL: {run_data.config.url}", styles["BodyText"]),
                 Paragraph(f"Run: {run_data.run_id}", styles["BodyText"]), Spacer(1,12)]
        ex = run_data.execution_result
        rows = [["Metric","Value"],["Pages",str(run_data.crawl_result.total_pages if run_data.crawl_result else 0)],
                ["Flows",str(len(run_data.flows))],["Tests",str(ex.total if ex else 0)],
                ["Passed",str(ex.passed if ex else 0)],["Failed",str(ex.failed if ex else 0)],
                ["Pass rate",f"{run_data.pass_rate:.1f}%"]]
        table=Table(rows,colWidths=[180,180])
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#eeeeee")),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("GRID",(0,0),(-1,-1),0.5,colors.grey),("PADDING",(0,0),(-1,-1),6)]))
        story += [table, Spacer(1,16), Paragraph("Findings", styles["Heading2"])]
        for i,f in enumerate(run_data.scored_failures,1):
            story.append(Paragraph(f"{i}. {f.test_name} — {f.severity}", styles["Heading3"]))
            story.append(Paragraph(f.reason or f.original_error or "Failure requires manual review.", styles["BodyText"]))
        doc.build(story)
        return out
