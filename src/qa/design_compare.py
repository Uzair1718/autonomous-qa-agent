"""Requirements/design to live-DOM comparison helpers."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

class DesignComparator:
    """Extracts testable design requirements from .pen and compares them with live DOM data."""
    def load_pen(self, path: Path) -> dict[str, Any]:
        raw=path.read_text(encoding="utf-8")
        try:
            value=json.loads(raw)
            return value if isinstance(value,dict) else {"document":value}
        except json.JSONDecodeError:
            return {"raw":raw}
    def compare(self, pen: dict[str,Any], live_pages: list[dict[str,Any]]) -> dict[str,Any]:
        text_blob=json.dumps(pen,ensure_ascii=False).lower()
        live_blob=json.dumps(live_pages,ensure_ascii=False).lower()
        tokens=[]
        for key in ("button","login","signup","register","dashboard","profile","search","email","password"):
            if key in text_blob:
                tokens.append({"element":key,"design_present":True,"live_keyword_present":key in live_blob})
        return {
            "design_elements_checked":len(tokens),
            "matches":sum(1 for x in tokens if x["live_keyword_present"]),
            "potential_mismatches":[x for x in tokens if not x["live_keyword_present"]],
            "note":"This is semantic DOM/design comparison. Exact pixel comparison requires a rendered .pen screenshot."
        }
