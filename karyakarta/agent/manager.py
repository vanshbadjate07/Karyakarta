"""Runs tasks one at a time (one browser, one local model), keeps the queue,
and routes the user's answers (confirm, credential, reply, cancel) to the
task that asked."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from karyakarta.agent.events import EventBus
from karyakarta.agent.loop import AgentRunner, TaskControl
from karyakarta.storage.db import Database

MAX_QUEUE = 20


class QueueFull(Exception):
    pass


class NoPendingRequest(Exception):
    """The task is not currently waiting for that kind of answer."""


class TaskManager:
    def __init__(self, db: Database, bus: EventBus, runner: AgentRunner, model_name: str):
        self._db = db
        self._bus = bus
        self._runner = runner
        self._model_name = model_name
        self._controls: dict[int, TaskControl] = {}
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._worker: Optional[asyncio.Task] = None
        self.current: Optional[int] = None

    async def start(self) -> None:
        self._db.fail_interrupted_tasks()
        self._worker = asyncio.create_task(self._work(), name="karyakarta-worker")

    async def stop(self) -> None:
        if self.current is not None and self.current in self._controls:
            self._controls[self.current].cancel.set()
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except (asyncio.CancelledError, Exception):
                pass

    # ------------------------------------------------------------------ submit
    def submit(self, instruction: str, start_url: Optional[str]) -> int:
        if self._queue.qsize() >= MAX_QUEUE:
            raise QueueFull("Too many tasks are waiting. Wait for some to finish.")
        task_id = self._db.create_task(instruction, start_url, self._model_name)
        self._controls[task_id] = TaskControl()
        self._queue.put_nowait(task_id)
        position = self._queue.qsize() + (1 if self.current is not None else 0)
        self._bus.emit(task_id, "task_queued", "Waiting to start." if position > 1 else "Starting.", {"position": position})
        return task_id

    async def _work(self) -> None:
        while True:
            task_id = await self._queue.get()
            task = self._db.get_task(task_id)
            control = self._controls.get(task_id)
            if not task or task["status"] != "queued" or control is None:
                self._controls.pop(task_id, None)
                continue
            self.current = task_id
            try:
                await self._runner.run(task_id, task["instruction"], task["start_url"], control)
            finally:
                self.current = None
                self._controls.pop(task_id, None)

    # --------------------------------------------------------------- controls
    def is_active(self, task_id: int) -> bool:
        return task_id in self._controls

    def cancel(self, task_id: int) -> bool:
        control = self._controls.get(task_id)
        if control is None:
            return False
        task = self._db.get_task(task_id)
        control.cancel.set()
        if task and task["status"] == "queued":
            self._db.set_status(task_id, "cancelled", error="Task cancelled before it started.")
            self._bus.emit(task_id, "task_cancelled", "Task cancelled before it started.")
        return True

    def _resolve(self, task_id: int, kind: str, value: Any) -> None:
        control = self._controls.get(task_id)
        pending = control.pending if control else None
        if pending is None or pending.kind != kind or pending.future.done():
            raise NoPendingRequest(f"Task {task_id} is not waiting for that.")
        pending.future.set_result(value)

    def respond_confirmation(self, task_id: int, approved: bool) -> None:
        self._resolve(task_id, "confirmation", bool(approved))

    def respond_credential(self, task_id: int, value: str) -> None:
        self._resolve(task_id, "credential", value)

    def respond_answer(self, task_id: int, message: str) -> None:
        self._resolve(task_id, "answer", message)
