"""Owns the real browser. One persistent profile lives in Karyakarta's data
folder, so a site the user logs in to once stays logged in for later tasks,
while their everyday browser is never touched."""
from __future__ import annotations

import asyncio
from typing import Optional

from playwright.async_api import BrowserContext, Page, async_playwright

from karyakarta.agent.errors import humanize_error
from karyakarta.config import Settings


class BrowserStartError(Exception):
    pass


class TaskBrowser:
    """The browser as one task sees it: a current tab, plus notes about
    things that happened on their own (dialogs, blocked downloads, new tabs)."""

    def __init__(self, context: BrowserContext, page: Page):
        self._context = context
        self.page = page
        self._notes: list[str] = []
        self._new_pages: list[Page] = []
        self._attach(page)
        context.on("page", self._on_new_page)

    def detach(self) -> None:
        try:
            self._context.remove_listener("page", self._on_new_page)
        except Exception:
            pass

    def _attach(self, page: Page) -> None:
        page.on("dialog", self._on_dialog)
        page.on("download", self._on_download)

    def _on_new_page(self, page: Page) -> None:
        self._attach(page)
        self._new_pages.append(page)

    async def _on_dialog(self, dialog) -> None:
        # Alerts and leave-page prompts are accepted so they cannot freeze the
        # page. Confirm and prompt dialogs are dismissed: they ask the user a
        # question the agent has no right to answer.
        accept = dialog.type in ("alert", "beforeunload")
        message = (dialog.message or "")[:200]
        self._notes.append(f'A "{dialog.type}" dialog appeared ("{message}") and was {"accepted" if accept else "dismissed"}.')
        try:
            await (dialog.accept() if accept else dialog.dismiss())
        except Exception:
            pass

    def _on_download(self, download) -> None:
        self._notes.append(f"A file download ({download.suggested_filename}) was blocked.")

    def take_notes(self) -> list[str]:
        notes, self._notes = self._notes, []
        return notes

    async def adopt_new_page(self) -> bool:
        """If an action opened a new tab, follow it. Returns True if switched."""
        while self._new_pages:
            page = self._new_pages.pop()
            if page.is_closed():
                continue
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            self.page = page
            self._new_pages.clear()
            self._notes.append("The action opened a new tab; the agent is now working in it.")
            return True
        return False

    async def goto(self, url: str, timeout_ms: int = 25000):
        return await self.page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)


class BrowserManager:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._playwright = None
        self._starter = None
        self._context: Optional[BrowserContext] = None

    @property
    def running(self) -> bool:
        return self._context is not None

    async def _ensure_started(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        self._settings.ensure_dirs()
        starter = async_playwright()
        try:
            self._playwright = await starter.start()
            self._starter = starter
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self._settings.profile_dir),
                headless=self._settings.headless,
                viewport={"width": self._settings.viewport_width, "height": self._settings.viewport_height},
                accept_downloads=False,
                args=["--deny-permission-prompts", "--disable-features=Translate"],
            )
            # If the user closes the window, forget it so the next task starts a fresh one.
            self._context.on("close", lambda *_: setattr(self, "_context", None))
        except BaseException as exc:
            # Includes being cancelled while starting (app quit mid-launch): never
            # leave the helper process behind.
            await asyncio.shield(self._stop_starter(starter))
            self._context = self._playwright = None
            if isinstance(exc, Exception):
                raise BrowserStartError(humanize_error(exc)) from exc
            raise
        return self._context

    @staticmethod
    async def _stop_starter(starter) -> None:
        try:
            await starter.__aexit__(None, None, None)
        except Exception:
            pass

    async def open(self, start_url: Optional[str] = None) -> TaskBrowser:
        context = await self._ensure_started()
        for old in list(context.pages):
            try:
                await old.close()
            except Exception:
                pass
        page = await context.new_page()
        browser = TaskBrowser(context, page)
        if start_url:
            await browser.goto(start_url)
        return browser

    async def close(self) -> None:
        context, starter = self._context, self._starter
        self._context, self._playwright, self._starter = None, None, None
        try:
            if context is not None:
                await context.close()
        except Exception:
            pass
        if starter is not None:
            await asyncio.shield(self._stop_starter(starter))
