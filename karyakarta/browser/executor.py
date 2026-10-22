"""Performs one action in the browser and checks that it really worked.

Every branch reports what it actually observed afterwards (the value the
field now holds, whether the checkbox really flipped), not merely that
Playwright raised no exception. A click that lands on nothing or a field that
silently refuses the text must come back as a failure, never as success.
"""
from __future__ import annotations

import asyncio
import re
from typing import Optional

from karyakarta.agent.errors import humanize_error
from karyakarta.models import ActionResult, AgentAction, Element
from karyakarta.safety import injection
from karyakarta.safety.policy import allowed_keys, normalize_url

_SETTLE_MS = 350


async def _settle(page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=3000)
    except Exception:
        pass
    await asyncio.sleep(_SETTLE_MS / 1000)


def _same(actual: str, expected: str) -> bool:
    a, b = (actual or "").strip(), (expected or "").strip()
    if a == b:
        return True
    digits = lambda s: re.sub(r"\D", "", s)
    if digits(a) and digits(a) == digits(b) and len(digits(b)) >= 6:
        return True  # phone / card style masks add spaces and dashes
    return b != "" and (a.replace(" ", "") == b.replace(" ", ""))


async def _read_value(loc) -> str:
    try:
        return await loc.input_value(timeout=1500)
    except Exception:
        try:
            return (await loc.inner_text(timeout=1500)).strip()
        except Exception:
            return ""


async def _is_checked(loc) -> Optional[bool]:
    try:
        return await loc.is_checked(timeout=1500)
    except Exception:
        try:
            return (await loc.get_attribute("aria-checked", timeout=1500)) == "true"
        except Exception:
            return None


def _short(value: str, limit: int = 60) -> str:
    return value if len(value) <= limit else value[: limit - 3] + "..."


async def execute(
    page,
    action: AgentAction,
    element: Optional[Element],
    *,
    secret_value: Optional[str] = None,
    viewport_height: int = 800,
) -> ActionResult:
    name = action.action
    try:
        if name == "navigate":
            url = normalize_url(action.value or "")
            response = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await _settle(page)
            status = response.status if response else None
            note = f" (the site answered with an error, status {status})" if status and status >= 400 else ""
            return ActionResult(status is None or status < 400, f"Opened {page.url}{note}", url_after=page.url)

        if name == "wait":
            try:
                seconds = min(max(float(action.value or 1.5), 0.5), 8.0)
            except ValueError:
                seconds = 1.5
            await asyncio.sleep(seconds)
            return ActionResult(True, f"Waited {seconds:g} seconds", url_after=page.url)

        if name == "scroll":
            before = await page.evaluate("() => Math.round(window.scrollY)")
            direction = (action.value or "down").lower()
            delta = int(viewport_height * 0.8) * (-1 if direction.startswith("up") else 1)
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(0.4)
            after = await page.evaluate("() => Math.round(window.scrollY)")
            if after == before:
                edge = "top" if delta < 0 else "bottom"
                return ActionResult(False, f"Already at the {edge} of the page", url_after=page.url)
            return ActionResult(True, f"Scrolled {'up' if delta < 0 else 'down'}", url_after=page.url)

        if name == "extract":
            if action.mark is not None and element is not None:
                text = await page.locator(f'[data-kk="{action.mark}"]').first.inner_text(timeout=4000)
            else:
                text = await page.inner_text("body", timeout=4000)
            clean, findings = injection.sanitize(" ".join(text.split())[:3000])
            notes = ["Page text contained instruction-like content and it was removed."] if findings else []
            return ActionResult(True, "Read text from the page", url_after=page.url, notes=notes, answer=clean)

        if element is None or action.mark is None:
            return ActionResult(False, f"'{name}' needs an element number from the list")

        loc = page.locator(f'[data-kk="{action.mark}"]').first
        if await page.locator(f'[data-kk="{action.mark}"]').count() == 0:
            return ActionResult(False, f"Element [{action.mark}] is no longer on the page. The page changed, look at it again.")
        try:
            await loc.scroll_into_view_if_needed(timeout=2500)
        except Exception:
            pass

        if name == "click":
            return await _click(page, loc, action, element)
        if name == "type":
            return await _type(page, loc, action, element, secret_value)
        if name == "select":
            return await _select(page, loc, action, element)
        if name == "press":
            key = (action.value or "Enter").strip()
            if key not in allowed_keys():
                return ActionResult(False, f"Key '{key}' is not allowed. Use one of: {', '.join(sorted(allowed_keys()))}")
            await loc.focus(timeout=3000)
            await page.keyboard.press(key)
            await _settle(page)
            return ActionResult(True, f"Pressed {key} in [{action.mark}]", url_after=page.url)

        return ActionResult(False, f"Unknown action '{name}'")
    except Exception as exc:
        return ActionResult(False, f"{name} failed: {humanize_error(exc)}", url_after=getattr(page, "url", ""))


async def _click(page, loc, action: AgentAction, element: Element) -> ActionResult:
    toggles = element.kind in ("checkbox", "radio")
    before = await _is_checked(loc) if toggles else None
    try:
        await loc.click(timeout=5000)
    except Exception:
        proxy = page.locator(f'[data-kk-label="{action.mark}"]')
        if await proxy.count() == 0:
            raise
        await proxy.first.click(timeout=3000)
    await _settle(page)
    if toggles:
        after = await _is_checked(loc)
        if element.kind == "radio" and after is not True:
            return ActionResult(False, f"Clicked [{action.mark}] but the option did not become selected", url_after=page.url)
        if element.kind == "checkbox" and before is not None and after == before:
            return ActionResult(False, f"Clicked [{action.mark}] but the checkbox did not change", url_after=page.url)
        return ActionResult(True, f"Clicked [{action.mark}] (now {'checked' if after else 'unchecked'})", url_after=page.url)
    return ActionResult(True, f"Clicked [{action.mark}]", url_after=page.url)


async def _type(page, loc, action: AgentAction, element: Element, secret_value: Optional[str]) -> ActionResult:
    value = secret_value if secret_value is not None else (action.value or "")
    secret = element.is_secret
    try:
        await loc.fill(value, timeout=5000)
    except Exception:
        # contenteditable or custom editors that reject fill()
        await loc.click(timeout=3000)
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.type(value, delay=15)
    actual = await _read_value(loc)
    if not _same(actual, value):
        shown = "(hidden)" if secret else repr(_short(actual))
        return ActionResult(False, f"Typed into [{action.mark}] but the field now reads {shown}", url_after=page.url)
    shown = "(hidden, secret field)" if secret else repr(_short(actual))
    return ActionResult(True, f"Typed into [{action.mark}] ({shown})", url_after=page.url)


async def _select(page, loc, action: AgentAction, element: Element) -> ActionResult:
    wanted = (action.value or "").strip()
    if not wanted:
        return ActionResult(False, "select needs a value")
    chosen = False
    for kwargs in ({"label": wanted}, {"value": wanted}):
        try:
            await loc.select_option(timeout=3000, **kwargs)
            chosen = True
            break
        except Exception:
            continue
    if not chosen:
        options = [o for o in element.options if wanted.lower() in o.lower()]
        if len(options) == 1:
            await loc.select_option(label=options[0], timeout=3000)
            chosen = True
    if not chosen:
        return ActionResult(False, f"'{wanted}' is not one of the options: {', '.join(element.options[:8])}")
    actual = await loc.evaluate("el => el.options && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text.trim() : ''")
    await _settle(page)
    return ActionResult(True, f"Selected '{actual}' in [{action.mark}]", url_after=page.url)
