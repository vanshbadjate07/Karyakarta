from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from karyakarta import __version__
from karyakarta.ai.client import ModelError
from karyakarta.api.security import require_token

router = APIRouter(prefix="/api", tags=["system"])

_browser_ready = False


async def browser_installed() -> bool:
    global _browser_ready
    if _browser_ready:
        return True
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            _browser_ready = Path(p.chromium.executable_path).exists()
    except Exception:
        return False
    return _browser_ready


@router.get("/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@router.get("/system/status", dependencies=[Depends(require_token)])
async def status(request: Request) -> dict:
    state = request.app.state
    model = await state.model.status()
    browser = await browser_installed()
    return {
        "version": __version__,
        "engine_running": model["engine_running"],
        "engine_version": model["engine_version"],
        "model": model["model"],
        "model_installed": model["model_installed"],
        "browser_installed": browser,
        "ready": bool(model["engine_running"] and model["model_installed"] and browser),
        "current_task": state.manager.current,
    }


@router.post("/system/model/pull", dependencies=[Depends(require_token)])
async def pull_model(request: Request) -> StreamingResponse:
    model = request.app.state.model

    async def lines():
        try:
            async for item in model.pull():
                total, done = item.get("total"), item.get("completed")
                percent = round(done * 100 / total, 1) if total and done is not None else None
                yield json.dumps({"status": item.get("status", ""), "percent": percent}) + "\n"
            yield json.dumps({"status": "success", "percent": 100}) + "\n"
        except ModelError as exc:
            yield json.dumps({"status": "error", "error": str(exc)}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")
