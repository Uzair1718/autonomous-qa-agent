"""HTTP API consumed by the n8n workflow."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from src.runner_service import run_qa

app = FastAPI(title="Autonomous QA Runner", version="0.2.0")


class QARunRequest(BaseModel):
    web_url: str = Field(min_length=1)
    admin_url: str = Field(min_length=1)
    admin_username: str = Field(min_length=1)
    admin_password: str = Field(min_length=1)
    srs_filename: str = "requirements.bin"
    srs_mime: str = "application/octet-stream"
    srs_base64: str = Field(min_length=1)
    pen_filename: str = "design.pen"
    pen_mime: str = "application/octet-stream"
    pen_base64: str = Field(min_length=1)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "autonomous-qa-runner"}


@app.post("/run")
async def run(request: QARunRequest) -> FileResponse:
    try:
        report = await run_qa(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not report.exists():
        raise HTTPException(status_code=500, detail="QA report was not generated")

    return FileResponse(
        path=report,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=report.name,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.api_server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )
