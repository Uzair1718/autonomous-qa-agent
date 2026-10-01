"""Bounded exploratory browser loop driven by a local LLM."""
from __future__ import annotations
import json, logging
from pathlib import Path
from typing import Any
from playwright.async_api import Browser, Page
from src.llm.ollama import OllamaClient

logger=logging.getLogger(__name__)

class ExploratoryAgent:
    """Chooses next safe UI actions from observed page state; Playwright executes them."""
    def __init__(self, client: Any | None=None, model: str="qwen3:8b", max_steps: int=30):
        self.client=client or OllamaClient()
        self.model=model
        self.max_steps=max_steps

    async def run(self, page: Page, run_dir: Path, context: str="") -> list[dict[str,Any]]:
        findings=[]
        trace_dir=run_dir/"exploratory"
        trace_dir.mkdir(parents=True,exist_ok=True)
        for i in range(self.max_steps):
            state=await page.locator("body").inner_text(timeout=5000)
            controls=await page.locator("button,a,input,select,textarea").evaluate_all(
                """els => els.slice(0,80).map((e,i)=>({i,tag:e.tagName,text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').slice(0,120),type:e.getAttribute('type'),href:e.getAttribute('href')}))"""
            )
            prompt=f"""Choose ONE next UI action to discover a defect. Do not repeat no-op actions.
Return JSON object {{action,target,value,reason,expected}}. action is click|fill|select|press|navigate|stop.
Never submit destructive irreversible actions unless clearly required by the SRS.
Context:{context[:6000]}
Page:{page.url}
Controls:{json.dumps(controls)}
Visible text:{state[:5000]}"""
            try:
                r=await self.client.chat.completions.create(model=self.model,temperature=0,messages=[{"role":"system","content":"You are a careful senior exploratory SDET. Return only JSON."},{"role":"user","content":prompt}],response_format={"type":"json_object"})
                a=json.loads(r.choices[0].message.content or '{"action":"stop"}')
            except Exception as exc:
                logger.warning("Exploration planner failed: %s",exc); break
            if a.get("action")=="stop": break
            try:
                target=a.get("target","")
                if a["action"]=="click": await page.locator(target).first.click(timeout=5000)
                elif a["action"]=="fill": await page.locator(target).first.fill(a.get("value",""))
                elif a["action"]=="select": await page.locator(target).first.select_option(a.get("value",""))
                elif a["action"]=="press": await page.locator(target).first.press(a.get("value","Enter"))
                elif a["action"]=="navigate": await page.goto(a.get("value",page.url),wait_until="domcontentloaded")
                await page.wait_for_timeout(300)
                findings.append({"step":i+1,"action":a,"url":page.url})
            except Exception as exc:
                shot=trace_dir/f"step_{i+1}_failure.png"
                await page.screenshot(path=str(shot),full_page=True)
                findings.append({"step":i+1,"action":a,"error":str(exc),"screenshot":str(shot),"url":page.url})
        (trace_dir/"actions.json").write_text(json.dumps(findings,indent=2),encoding="utf-8")
        return findings
