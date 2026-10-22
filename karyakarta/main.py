from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from karyakarta import __version__
from karyakarta.agent.events import EventBus
from karyakarta.agent.loop import AgentRunner
from karyakarta.agent.manager import TaskManager
from karyakarta.ai.client import OllamaClient
from karyakarta.api import system, tasks
from karyakarta.api.security import TOKEN_HEADER, LocalHostOnly
from karyakarta.browser.session import BrowserManager
from karyakarta.config import Settings
from karyakarta.storage.db import Database

# Origins the desktop app and its dev server load from. The token is the real
# protection; this list only stops browsers from sending requests elsewhere.
ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "null", "app://karyakarta"]


def create_app(
    settings: Optional[Settings] = None,
    *,
    model: Optional[OllamaClient] = None,
    browser: Optional[BrowserManager] = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.ensure_dirs()
        db = Database(settings.db_path)
        bus = EventBus(db)
        client = model or OllamaClient(
            settings.ollama_url, settings.model, num_ctx=settings.num_ctx,
            temperature=settings.temperature, timeout_s=settings.model_timeout_s, keep_alive=settings.keep_alive,
        )
        browsers = browser or BrowserManager(settings)
        runner = AgentRunner(settings, db, bus, client, browsers)
        manager = TaskManager(db, bus, runner, settings.model)
        app.state.db, app.state.bus, app.state.model = db, bus, client
        app.state.browser, app.state.manager = browsers, manager
        await manager.start()
        try:
            yield
        finally:
            await manager.stop()
            await asyncio.shield(browsers.close())
            await client.aclose()
            db.close()

    app = FastAPI(title="Karyakarta", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST", "DELETE"],
        allow_headers=[TOKEN_HEADER, "Content-Type"],
    )
    app.add_middleware(LocalHostOnly, port=settings.port)
    app.include_router(system.router)
    app.include_router(tasks.router)
    return app
