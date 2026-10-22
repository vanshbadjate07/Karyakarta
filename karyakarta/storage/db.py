"""SQLite storage for tasks, activity events and structured steps.

Credentials, one-time codes and card data never reach this module: callers
only ever pass already-redacted text. The step table is also the raw material
for the replayable benchmark and for fine-tuning data later.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

TERMINAL_STATUSES = ("completed", "failed", "cancelled")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    instruction TEXT NOT NULL,
    start_url   TEXT,
    status      TEXT NOT NULL DEFAULT 'queued',
    result      TEXT,
    error       TEXT,
    model       TEXT,
    created_at  REAL NOT NULL,
    started_at  REAL,
    finished_at REAL
);
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    seq     INTEGER NOT NULL,
    ts      REAL NOT NULL,
    kind    TEXT NOT NULL,
    message TEXT NOT NULL,
    detail  TEXT,
    UNIQUE (task_id, seq)
);
CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    url         TEXT,
    thought     TEXT,
    action      TEXT,
    mark        INTEGER,
    summary     TEXT,
    ok          INTEGER NOT NULL,
    verified    INTEGER NOT NULL DEFAULT 0,
    detail      TEXT,
    model_ms    INTEGER,
    tokens_out  INTEGER,
    screenshot  TEXT,
    ts          REAL NOT NULL,
    UNIQUE (task_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, seq);
CREATE INDEX IF NOT EXISTS idx_steps_task ON steps(task_id, idx);
"""


class Database:
    def __init__(self, path: Path | str):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _all(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # ---- tasks -----------------------------------------------------------
    def create_task(self, instruction: str, start_url: Optional[str], model: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO tasks (instruction, start_url, model, created_at) VALUES (?, ?, ?, ?)",
                (instruction, start_url, model, time.time()),
            )
            return int(cur.lastrowid)

    def get_task(self, task_id: int) -> Optional[dict]:
        return self._one("SELECT * FROM tasks WHERE id = ?", (task_id,))

    def list_tasks(self, limit: int = 100) -> list[dict]:
        return self._all("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))

    def set_status(
        self,
        task_id: int,
        status: str,
        *,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        now = time.time()
        with self._lock:
            fields, params = ["status = ?"], [status]
            if status == "running":
                fields.append("started_at = COALESCE(started_at, ?)")
                params.append(now)
            if status in TERMINAL_STATUSES:
                fields.append("finished_at = ?")
                params.append(now)
            if result is not None:
                fields.append("result = ?")
                params.append(result)
            if error is not None:
                fields.append("error = ?")
                params.append(error)
            params.append(task_id)
            self._conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", params)

    def delete_task(self, task_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def fail_interrupted_tasks(self) -> int:
        """On startup, anything still queued/running was cut off by a crash or
        quit: mark it failed rather than leaving it looking alive forever."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status='failed', finished_at=?, "
                "error='Karyakarta was closed before this task finished.' "
                "WHERE status IN ('queued','running','awaiting_user')",
                (time.time(),),
            )
            return cur.rowcount

    # ---- events ----------------------------------------------------------
    def add_event(self, task_id: int, kind: str, message: str, detail: Optional[dict[str, Any]] = None) -> dict:
        with self._lock:
            seq = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
            ts = time.time()
            self._conn.execute(
                "INSERT INTO events (task_id, seq, ts, kind, message, detail) VALUES (?, ?, ?, ?, ?, ?)",
                (task_id, seq, ts, kind, message, json.dumps(detail) if detail else None),
            )
        return {"task_id": task_id, "seq": seq, "ts": ts, "kind": kind, "message": message, "detail": detail or {}}

    def list_events(self, task_id: int, after: int = 0) -> list[dict]:
        rows = self._all(
            "SELECT seq, ts, kind, message, detail FROM events WHERE task_id = ? AND seq > ? ORDER BY seq",
            (task_id, after),
        )
        for row in rows:
            row["task_id"] = task_id
            row["detail"] = json.loads(row["detail"]) if row["detail"] else {}
        return rows

    # ---- steps -----------------------------------------------------------
    def add_step(self, task_id: int, idx: int, **fields: Any) -> None:
        columns = ["task_id", "idx", "ts"] + list(fields)
        values = [task_id, idx, time.time()] + [
            json.dumps(v) if isinstance(v, (dict, list)) else v for v in fields.values()
        ]
        marks = ", ".join("?" for _ in columns)
        with self._lock:
            self._conn.execute(f"INSERT OR REPLACE INTO steps ({', '.join(columns)}) VALUES ({marks})", values)

    def list_steps(self, task_id: int) -> list[dict]:
        rows = self._all("SELECT * FROM steps WHERE task_id = ? ORDER BY idx", (task_id,))
        for row in rows:
            row["detail"] = json.loads(row["detail"]) if row["detail"] else {}
        return rows
