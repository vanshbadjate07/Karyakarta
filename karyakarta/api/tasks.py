from __future__ import annotations

import asyncio
import shutil
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from karyakarta.agent.manager import NoPendingRequest, QueueFull
from karyakarta.api.security import require_token, websocket_token_ok
from karyakarta.safety.policy import parse_target
from karyakarta.storage.db import TERMINAL_STATUSES

router = APIRouter(prefix="/api", tags=["tasks"])


class TaskCreate(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)
    start_url: Optional[str] = Field(default=None, max_length=2000)


def _clean_task(body: TaskCreate) -> tuple[str, Optional[str]]:
    instruction = " ".join(body.instruction.split())
    if len(instruction) < 3:
        raise HTTPException(422, "Describe the task in a few words.")
    url = (body.start_url or "").strip()
    if not url:
        return instruction, None
    parsed = parse_target(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(422, "The starting address must be a normal website address (http or https).")
    return instruction, parsed.geturl()


class Confirmation(BaseModel):
    approved: bool


class Credential(BaseModel):
    value: str = Field(min_length=1, max_length=512)


class Answer(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


def _state(request: Request):
    return request.app.state


def _task_or_404(request: Request, task_id: int) -> dict:
    task = _state(request).db.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found.")
    return task


@router.post("/tasks", status_code=201, dependencies=[Depends(require_token)])
def create_task(body: TaskCreate, request: Request) -> dict:
    instruction, start_url = _clean_task(body)
    try:
        task_id = _state(request).manager.submit(instruction, start_url)
    except QueueFull as exc:
        raise HTTPException(429, str(exc)) from exc
    return _state(request).db.get_task(task_id)


@router.get("/tasks", dependencies=[Depends(require_token)])
def list_tasks(request: Request, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    return _state(request).db.list_tasks(limit)


@router.get("/tasks/{task_id}", dependencies=[Depends(require_token)])
def get_task(task_id: int, request: Request) -> dict:
    task = _task_or_404(request, task_id)
    task["steps"] = _state(request).db.list_steps(task_id)
    return task


@router.get("/tasks/{task_id}/events", dependencies=[Depends(require_token)])
def get_events(task_id: int, request: Request, after: int = Query(0, ge=0)) -> list[dict]:
    _task_or_404(request, task_id)
    return _state(request).db.list_events(task_id, after)


@router.get("/tasks/{task_id}/screenshots/{name}", dependencies=[Depends(require_token)])
def get_screenshot(task_id: int, name: str, request: Request):
    _task_or_404(request, task_id)
    if not name.endswith(".jpg") or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Bad file name.")
    path = _state(request).settings.runs_dir / str(task_id) / name
    if not path.is_file():
        raise HTTPException(404, "Screenshot not found.")
    return FileResponse(path, media_type="image/jpeg")


@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(require_token)])
def cancel_task(task_id: int, request: Request) -> dict:
    _task_or_404(request, task_id)
    if not _state(request).manager.cancel(task_id):
        raise HTTPException(409, "That task is not running.")
    return {"ok": True}


def _respond(request: Request, task_id: int, fn, *args) -> dict:
    _task_or_404(request, task_id)
    try:
        fn(task_id, *args)
    except NoPendingRequest as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True}


@router.post("/tasks/{task_id}/confirm", dependencies=[Depends(require_token)])
def confirm(task_id: int, body: Confirmation, request: Request) -> dict:
    return _respond(request, task_id, _state(request).manager.respond_confirmation, body.approved)


@router.post("/tasks/{task_id}/credential", dependencies=[Depends(require_token)])
def credential(task_id: int, body: Credential, request: Request) -> dict:
    return _respond(request, task_id, _state(request).manager.respond_credential, body.value)


@router.post("/tasks/{task_id}/answer", dependencies=[Depends(require_token)])
def answer(task_id: int, body: Answer, request: Request) -> dict:
    return _respond(request, task_id, _state(request).manager.respond_answer, body.message)


@router.delete("/tasks/{task_id}", status_code=204, dependencies=[Depends(require_token)])
def delete_task(task_id: int, request: Request) -> None:
    task = _task_or_404(request, task_id)
    if task["status"] not in TERMINAL_STATUSES:
        raise HTTPException(409, "Stop the task before deleting it.")
    state = _state(request)
    state.db.delete_task(task_id)
    shutil.rmtree(state.settings.runs_dir / str(task_id), ignore_errors=True)


@router.websocket("/ws/tasks/{task_id}")
async def stream_task(websocket: WebSocket, task_id: int, after: int = 0) -> None:
    if not websocket_token_ok(websocket):
        await websocket.close(code=4401)
        return
    state = websocket.app.state
    if not state.db.get_task(task_id):
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue = state.bus.subscribe(task_id)
    try:
        last = after
        for event in state.db.list_events(task_id, after):
            await websocket.send_json(event)
            last = event["seq"]
        task = state.db.get_task(task_id)
        while True:
            if task and task["status"] in TERMINAL_STATUSES and queue.empty():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=15)
            except asyncio.TimeoutError:
                await websocket.send_json({"kind": "ping", "seq": last, "message": "", "detail": {}})
                task = state.db.get_task(task_id)
                continue
            if event["seq"] > last:
                await websocket.send_json(event)
                last = event["seq"]
            task = state.db.get_task(task_id)
    except WebSocketDisconnect:
        pass
    finally:
        state.bus.unsubscribe(task_id, queue)
        try:
            await websocket.close()
        except Exception:
            pass
