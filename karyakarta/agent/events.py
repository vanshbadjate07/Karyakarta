"""Live activity stream. Every event is saved first, then pushed to anyone
watching, so a screen opened late (or after a restart) still shows the full
history. Nothing the agent does is silent."""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from karyakarta.storage.db import Database


class EventBus:
    def __init__(self, db: Database):
        self._db = db
        self._subscribers: dict[int, set[asyncio.Queue]] = {}

    def emit(self, task_id: int, kind: str, message: str, detail: Optional[dict[str, Any]] = None) -> dict:
        event = self._db.add_event(task_id, kind, message, detail)
        for queue in list(self._subscribers.get(task_id, ())):
            queue.put_nowait(event)
        return event

    def subscribe(self, task_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(task_id, set()).add(queue)
        return queue

    def unsubscribe(self, task_id: int, queue: asyncio.Queue) -> None:
        subscribers = self._subscribers.get(task_id)
        if subscribers:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(task_id, None)
