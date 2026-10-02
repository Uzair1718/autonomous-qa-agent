"""Real Pencil .pen vs live-site visual comparison."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from PIL import Image, ImageChops, ImageEnhance
from playwright.async_api import async_playwright


def _load_pages(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(errors="replace"))
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            typ = str(node.get("type", "")).lower()
            if typ in {"page", "frame", "artboard"} and node.get("name"):
                found.append(node)
            for child in node.get("children", []) or []:
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    # Prefer actual pages; otherwise top-level frames/artboards.
    pages = [x for x in found if str(x.get("type", "")).lower() == "page"]
    return pages or found


def _slug(value: str) -> str:
    value = value.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def _route_score(name: str, url: str) -> int:
    n = _slug(name)
    parsed = urlparse(url)
    path = _slug(parsed.path or "/")
    score = 0
    if n and n == path:
        score += 100
    if n and n in path:
        score += 60
    for token in n.split("-"):
        if len(token) > 2 and token in path:
            score += 10
    if n in {"home", "homepage", "landing", "dashboard"} and path in {"", "/"}:
        score += 50
    return score


def _match_url(name: str, urls: list[str], used: set[str]) -> str | None:
    candidates = sorted(
        ((u, _route_score(name, u)) for u in urls if u not in used),
        key=lambda x: x[1],
        reverse=True,
    )
    if not candidates or candidates[0][1] < 10:
        return None
    return candidates[0][0]


def _export_pen_page(pen_file: Path, page_name: str, output: Path) -> tuple[bool, str]:
    cli = os.getenv("PEN_CLI", "openpencil")
    cmd = [
        cli, "export", str(pen_file),
        "--format", "png",
        "--scale", os.getenv("PEN_EXPORT_SCALE", "1"),
        "--page", page_name,
        "--output", str(output),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=180, check=False
        )
    except Exception as exc:
        return False, str(exc)
    return proc.returncode == 0 and output.exists(), (proc.stderr or proc.stdout)[-3000:]


def _compare(expected: Path, actual: Path, diff_path: Path) -> dict[str, Any]:
    e = Image.open(expected).convert("RGB")
    a = Image.open(actual).convert("RGB")
    if e.size != a.size:
        a = a.resize(e.size, Image.Resampling.LANCZOS)

    diff = ImageChops.difference(e, a)
    histogram = diff.histogram()
    total = sum(histogram)
    weighted = sum(i * histogram[i] for i in range(256))
    mean_abs = weighted / max(total, 1)
    similarity = max(0.0, 1.0 - mean_abs / 255.0)

    # Amplified diff makes the evidence human-readable.
    amplified = ImageEnhance.Contrast(diff).enhance(4.0)
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    amplified.save(diff_path)

    bbox = diff.getbbox()
    changed_ratio = 0.0
    if bbox:
        changed_pixels = sum(
            1 for pixel in diff.getdata() if max(pixel) > 16
        )
        changed_ratio = changed_pixels / max(e.size[0] * e.size[1], 1)

    return {
        "expected_size": f"{e.width}x{e.height}",
        "actual_size": f"{Image.open(actual).width}x{Image.open(actual).height}",
        "similarity": round(similarity * 100, 2),
        "changed_ratio": round(changed_ratio * 100, 2),
        "status": "PASS" if similarity >= float(os.getenv("PEN_VISUAL_PASS", "0.90")) else "FAIL",
    }


async def run_pen_visual_audit(
    pen_file: Path,
    urls: list[str],
    output_dir: Path,
    headless: bool = True,
) -> list[dict[str, Any]]:
    if pen_file.suffix.lower() != ".pen":
        return [{
            "screen": pen_file.name,
            "status": "NOT_RUN",
            "reason": "Visual renderer requires a native .pen file.",
        }]

    pages = _load_pages(pen_file)
    output_dir.mkdir(parents=True, exist_ok=True)
    used: set[str] = set()
    results: list[dict[str, Any]] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page(viewport={"width": 1440, "height": 1000})
        for index, design in enumerate(pages):
            name = str(design.get("name", f"Screen {index + 1}"))
            url = _match_url(name, urls, used)
            expected = output_dir / f"{index:03d}-{_slug(name) or 'screen'}-design.png"
            actual = output_dir / f"{index:03d}-{_slug(name) or 'screen'}-live.png"
            diff = output_dir / f"{index:03d}-{_slug(name) or 'screen'}-diff.png"

            exported, export_log = _export_pen_page(pen_file, name, expected)
            if not exported:
                results.append({
                    "screen": name,
                    "url": url or "",
                    "status": "NOT_RUN",
                    "reason": f".pen export failed: {export_log}",
                    "design_screenshot": str(expected),
                })
                continue

            if not url:
                results.append({
                    "screen": name,
                    "url": "",
                    "status": "UNMAPPED",
                    "reason": "No crawled URL matched this design screen name.",
                    "design_screenshot": str(expected),
                })
                continue

            try:
                used.add(url)
                design_image = Image.open(expected).convert("RGB")
                await page.set_viewport_size({
                    "width": max(320, design_image.width),
                    "height": max(240, min(design_image.height, 1600)),
                })
                await page.goto(url, wait_until="networkidle", timeout=60000)
                await page.screenshot(path=str(actual), full_page=False)
                metrics = _compare(expected, actual, diff)
                results.append({
                    "screen": name,
                    "url": url,
                    "status": metrics["status"],
                    "similarity": metrics["similarity"],
                    "changed_ratio": metrics["changed_ratio"],
                    "expected_size": metrics["expected_size"],
                    "actual_size": metrics["actual_size"],
                    "design_screenshot": str(expected),
                    "live_screenshot": str(actual),
                    "diff_screenshot": str(diff),
                })
            except Exception as exc:
                results.append({
                    "screen": name,
                    "url": url,
                    "status": "ERROR",
                    "reason": str(exc),
                    "design_screenshot": str(expected),
                    "live_screenshot": str(actual),
                })

        await browser.close()

    (output_dir / "visual-audit.json").write_text(json.dumps(results, indent=2))
    return results
