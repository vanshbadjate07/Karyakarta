from __future__ import annotations

import functools
import http.server
import json
import re
import threading
from pathlib import Path

import pytest

from karyakarta.agent.events import EventBus
from karyakarta.agent.loop import AgentRunner
from karyakarta.agent.manager import TaskManager
from karyakarta.ai.client import ModelReply
from karyakarta.browser.session import BrowserManager
from karyakarta.config import Settings
from karyakarta.storage.db import Database

SITE_DIR = Path(__file__).parent / "site"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # keep test output clean
        pass


@pytest.fixture(scope="session")
def site():
    handler = functools.partial(_QuietHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        api_token="test-token",
        headless=True,
        max_steps=14,
        allow_private_hosts=True,  # the test site lives on 127.0.0.1
    )


@pytest.fixture
def db(settings):
    settings.ensure_dirs()
    database = Database(settings.db_path)
    yield database
    database.close()


@pytest.fixture
async def browser(settings):
    manager = BrowserManager(settings)
    yield manager
    await manager.close()


class ScriptedModel:
    """Stands in for the local model. Each step it returns the next scripted
    action; a label like "Full name" is turned into the element number shown in
    the prompt, exactly like the real model has to read it."""

    model = "scripted"

    def __init__(self, steps: list[dict]):
        self.steps = list(steps)
        self.prompts: list[str] = []

    async def chat_json(self, system, user_text, images, **kwargs) -> ModelReply:
        self.prompts.append(user_text)
        step = dict(self.steps.pop(0)) if self.steps else {"action": "fail", "value": "script ended"}
        label = step.pop("label", None)
        if label is not None:
            step["mark"] = self._mark_for(user_text, label)
        step.setdefault("thought", "scripted step")
        return ModelReply(content=json.dumps(step), latency_ms=5, tokens_in=10, tokens_out=10)

    @staticmethod
    def _mark_for(prompt: str, label: str) -> int:
        for line in prompt.splitlines():
            match = re.match(r"\[(\d+)\] (\S+)(?: \"(.*?)\")?", line)
            if match and match.group(3) and label.lower() in match.group(3).lower():
                return int(match.group(1))
        raise AssertionError(f"no element labelled {label!r} in prompt:\n{prompt}")

    async def status(self):
        return {"engine_running": True, "engine_version": "test", "model": "scripted", "model_installed": True, "installed_models": []}

    async def aclose(self):
        pass


@pytest.fixture
def make_runner(settings, db, browser):
    def build(steps: list[dict]):
        bus = EventBus(db)
        model = ScriptedModel(steps)
        runner = AgentRunner(settings, db, bus, model, browser)
        manager = TaskManager(db, bus, runner, "scripted")
        return runner, manager, model, bus

    return build
