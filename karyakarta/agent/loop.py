"""The agent loop: look at the page, let the local model pick ONE action,
check it against the live page and the policy firewall, ask the user when
needed, perform it, then verify what really happened before the next step.

The model never gets the last word. Every action is validated against the
page, then judged by the firewall, and every result is checked in code. A task
is only reported finished when the model says so AND its last action did not
fail; no model reply can turn a failed action into a success.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Optional, TypeVar
from urllib.parse import urlparse

from karyakarta.agent.errors import humanize_error
from karyakarta.agent.events import EventBus
from karyakarta.ai.actions import validate_action
from karyakarta.ai.client import ModelError, ModelOutputError, OllamaClient, parse_action
from karyakarta.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from karyakarta.browser import executor
from karyakarta.browser.perception import observe
from karyakarta.browser.session import BrowserManager, BrowserStartError, TaskBrowser
from karyakarta.config import Settings
from karyakarta.models import ACTION_SCHEMA, TEXT_KINDS, ActionResult, AgentAction, Element, Observation
from karyakarta.safety.policy import Decision, PolicyContext, evaluate
from karyakarta.safety.sensitive import mentions_secret
from karyakarta.storage.db import Database

log = logging.getLogger("karyakarta.agent")
T = TypeVar("T")

HISTORY_WINDOW = 8
NO_EFFECT_HINT_AT = 2
NO_EFFECT_FAIL_AT = 6
MAX_DECLINES = 2


def _narrow_schema(actions: list[str], marks: list[int]) -> dict:
    """The strict reply format, narrowed so only valid choices are possible
    (the runtime enforces it while the model writes, it cannot be ignored)."""
    schema = copy.deepcopy(ACTION_SCHEMA)
    schema["properties"]["action"]["enum"] = actions
    if marks:
        schema["properties"]["mark"] = {"type": "integer", "enum": sorted(marks)}
    else:
        schema["properties"].pop("mark")
    return schema


class TaskCancelled(Exception):
    pass


@dataclass
class Pending:
    kind: str  # "confirmation" | "credential" | "answer"
    future: "asyncio.Future[Any]"


@dataclass
class TaskControl:
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    pending: Optional[Pending] = None


@dataclass
class _PendingStep:
    idx: int
    action: AgentAction
    label: str
    result: ActionResult
    fingerprint_before: str
    thought: str
    url: str
    shot: str
    model_ms: int
    tokens_out: int
    history_index: int
    notes: list[str]


class AgentRunner:
    def __init__(self, settings: Settings, db: Database, bus: EventBus, model: OllamaClient, browser: BrowserManager):
        self.settings = settings
        self.db = db
        self.bus = bus
        self.model = model
        self.browser = browser

    # ------------------------------------------------------------------ run
    async def run(self, task_id: int, instruction: str, start_url: Optional[str], control: TaskControl) -> None:
        try:
            await self._run(task_id, instruction, start_url, control)
        except TaskCancelled:
            self._finish(task_id, "cancelled", "Task cancelled.")
        except _Stuck as exc:
            self._finish(task_id, "failed", str(exc))
        except asyncio.CancelledError:
            self._finish(task_id, "cancelled", "Task stopped because Karyakarta is shutting down.")
            raise
        except (ModelError, BrowserStartError) as exc:
            self._finish(task_id, "failed", str(exc))
        except Exception as exc:
            log.exception("Unhandled error in task %s", task_id)
            self._finish(task_id, "failed", humanize_error(exc))

    def _finish(self, task_id: int, status: str, message: str, detail: Optional[dict] = None) -> None:
        kind = {"completed": "task_complete", "failed": "task_error", "cancelled": "task_cancelled"}[status]
        if status == "completed":
            self.db.set_status(task_id, status, result=message)
        else:
            self.db.set_status(task_id, status, error=message)
        self.bus.emit(task_id, kind, message, detail)

    # ---------------------------------------------------------------- helpers
    async def _cancellable(self, coro: Awaitable[T], control: TaskControl) -> T:
        if control.cancel.is_set():
            getattr(coro, "close", lambda: None)()
            raise TaskCancelled()
        work = asyncio.ensure_future(coro)
        stop = asyncio.ensure_future(control.cancel.wait())
        try:
            done, _ = await asyncio.wait({work, stop}, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            work.cancel()
            stop.cancel()
            await asyncio.gather(work, stop, return_exceptions=True)
            raise
        if work in done:
            stop.cancel()
            return work.result()
        work.cancel()
        await asyncio.gather(work, return_exceptions=True)
        raise TaskCancelled()

    async def _wait_user(self, task_id: int, control: TaskControl, kind: str, event_kind: str, message: str, detail: dict) -> Any:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        control.pending = Pending(kind, future)
        self.db.set_status(task_id, "awaiting_user")
        self.bus.emit(task_id, event_kind, message, detail)
        try:
            return await self._cancellable(future, control)
        finally:
            control.pending = None
            if not control.cancel.is_set():
                self.db.set_status(task_id, "running")

    def _save_shot(self, task_id: int, idx: int, data: bytes) -> str:
        if not data:
            return ""
        folder = self.settings.runs_dir / str(task_id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"step_{idx:02d}.jpg"
        path.write_bytes(data)
        return f"{task_id}/{path.name}"

    @staticmethod
    def _describe(action: AgentAction, element: Optional[Element]) -> str:
        """What this action does, in words a person understands. Secret values
        are never included."""
        name = element.label if element is not None and element.label else (element.kind if element else "")
        quoted = f'"{name}"' if name else "the element"
        value = (action.value or "").strip()
        value = value if len(value) <= 60 else value[:57] + "..."
        if action.action == "click":
            return f"Click the {element.kind if element else 'element'} {quoted}"
        if action.action == "type":
            if element is not None and element.is_secret:
                return f"Enter your {'password' if element.is_password else 'code' if element.is_otp else 'payment detail'} in {quoted} (you type it yourself)"
            return f'Type "{value}" into {quoted}'
        if action.action == "select":
            return f'Choose "{value}" in {quoted}'
        if action.action == "press":
            return f"Press {value or 'Enter'} in {quoted}"
        if action.action == "scroll":
            return f"Scroll {(value or 'down').lower()}"
        if action.action == "navigate":
            return f"Open {value}"
        if action.action == "extract":
            return "Read the text on the page"
        if action.action == "wait":
            return "Wait for the page"
        return action.action

    @staticmethod
    def _label(action: AgentAction, element: Optional[Element]) -> str:
        """Description safe to store and show: secret values are never included."""
        if element is not None and element.is_secret and action.action == "type":
            return f"type [{action.mark}] (secret field, entered by you)"
        return action.short()

    # ------------------------------------------------------------------ main
    async def _run(self, task_id: int, instruction: str, start_url: Optional[str], control: TaskControl) -> None:
        s = self.settings
        self.db.set_status(task_id, "running")
        self.bus.emit(task_id, "task_started", "Task started.", {"model": s.model})

        tb: TaskBrowser = await self._cancellable(self.browser.open(start_url), control)
        try:
            await self._loop(task_id, instruction, start_url, control, tb)
        finally:
            tb.detach()

    async def _loop(self, task_id: int, instruction: str, start_url: Optional[str], control: TaskControl, tb: TaskBrowser) -> None:
        s = self.settings
        history: list[str] = []
        answers: list[str] = []
        ctx = PolicyContext(
            start_host=(urlparse(start_url).hostname or "").lower() if start_url else "",
            allow_private_hosts=s.allow_private_hosts,
            own_ports=frozenset({s.port}),
        )
        pending: Optional[_PendingStep] = None
        extracted: Optional[str] = None
        notices: list[str] = []
        failures = 0
        no_effect = 0
        declines = 0
        done_challenged = False
        done_empty_challenged = False
        last_ok = True
        warned_injection = False
        total_failed_steps = 0
        blocked: Optional[tuple] = None  # an action that worked but changed nothing: must not be repeated

        for idx in range(1, s.max_steps + 1):
            if control.cancel.is_set():
                raise TaskCancelled()

            obs = await self._cancellable(self._observe(tb), control)
            if pending is not None:
                no_effect, total_failed_steps = self._finalize(task_id, pending, obs, history, no_effect, total_failed_steps)
                noop = "nothing visibly changed" in history[pending.history_index] or "view did not change" in history[pending.history_index]
                blocked = (pending.action.action, pending.action.mark) if noop else None
                pending = None

            ctx.injection_suspected = bool(obs.injection)
            if obs.injection and not warned_injection:
                warned_injection = True
                self.bus.emit(task_id, "warning", "This page contains text that tries to give the agent instructions. It was removed and will be ignored.", {"found": obs.injection[:3]})
            self.bus.emit(task_id, "observe", f"Reading page: {obs.title or obs.url}", {"url": obs.url, "elements": len(obs.elements)})

            hints: list[str] = []
            if no_effect >= NO_EFFECT_HINT_AT:
                hints.append(f"Your last {no_effect} actions had no effect. Do not repeat them. If the task is already complete, use done and put the result in value. Otherwise try a different element or approach.")
            if no_effect >= NO_EFFECT_FAIL_AT:
                raise _Stuck("The agent kept trying without making progress, so it stopped. Try rewording the task or give a starting website.")
            if failures >= s.max_consecutive_failures:
                raise _Stuck("The agent could not choose a valid action several times in a row, so it stopped.")

            prompt = build_user_prompt(
                instruction,
                self._window(history),
                obs,
                answers=answers,
                notices=notices + tb.take_notes(),
                hints=hints,
                extracted=extracted,
            )
            notices, extracted = [], None

            try:
                action, reply = await self._cancellable(self._decide(prompt, obs), control)
            except ModelOutputError as exc:
                failures += 1
                total_failed_steps += 1
                history.append(f"{idx}. (no valid action) -> {exc}")
                self.bus.emit(task_id, "warning", f"The model gave an unusable answer: {exc}", {})
                self.db.add_step(task_id, idx, url=obs.url, thought="", action="invalid", summary=str(exc), ok=0, verified=0)
                continue

            corrected = await self._correct(prompt, obs, action, blocked, control)
            if corrected is not None:
                action, reply = corrected
                self.bus.emit(task_id, "notice", "The model's first choice was not usable, so it was asked again with only valid options.", {"step": idx})

            shot = self._save_shot(task_id, idx, obs.screenshot)
            element = obs.by_ref().get(action.mark) if action.mark is not None else None
            label = self._label(action, element)
            desc = self._describe(action, element)
            self.bus.emit(task_id, "thought", action.thought or "(no explanation)", {"step": idx})

            problem = validate_action(action, obs)
            if problem is None and action.action == "ask_user" and mentions_secret(action.value or ""):
                problem = "Never ask the user to type a password, code or card number in chat. Use type on the secret field instead."
            if problem:
                failures += 1
                total_failed_steps += 1
                history.append(f"{idx}. {label} -> rejected: {problem}")
                self.bus.emit(task_id, "warning", f"Skipped an invalid action ({label}): {problem}", {"step": idx})
                self.db.add_step(task_id, idx, url=obs.url, thought=action.thought, action=action.action, mark=action.mark, summary=f"rejected: {problem}", ok=0, verified=0, screenshot=shot, model_ms=reply.latency_ms, tokens_out=reply.tokens_out)
                continue
            failures = 0

            # ---- terminal and conversational actions -----------------------------
            if action.action == "fail":
                self.db.add_step(task_id, idx, url=obs.url, thought=action.thought, action="fail", summary=action.value, ok=1, verified=1, screenshot=shot)
                self._finish(task_id, "failed", f"The agent could not finish: {action.value}", {"steps": idx})
                return

            if action.action == "done":
                if not last_ok and not done_challenged:
                    done_challenged = True
                    history.append(f"{idx}. done -> not accepted yet: your last action failed. Look at the page and confirm the task is really complete.")
                    self.bus.emit(task_id, "warning", "The model said it was done, but its last action had failed. Asking it to double-check.", {"step": idx})
                    continue
                if not (action.value or "").strip() and not done_empty_challenged:
                    done_empty_challenged = True
                    history.append(f"{idx}. done -> not accepted: value was empty. Put the answer or a short summary of what you did in value.")
                    self.bus.emit(task_id, "warning", "The model said it was done without giving a result. Asking it for one.", {"step": idx})
                    continue
                result_text = (action.value or "").strip() or "Task finished."
                self.db.add_step(task_id, idx, url=obs.url, thought=action.thought, action="done", summary=result_text, ok=1, verified=1, screenshot=shot, model_ms=reply.latency_ms, tokens_out=reply.tokens_out)
                self._finish(task_id, "completed", result_text, {"steps": idx, "failed_steps": total_failed_steps, "url": obs.url})
                return

            if action.action == "ask_user":
                answer = await self._wait_user(task_id, control, "answer", "question", action.value or "", {"step": idx})
                answers.append(str(answer)[:500])
                history.append(f"{idx}. ask_user -> the user answered (see USER ANSWERS)")
                self.db.add_step(task_id, idx, url=obs.url, thought=action.thought, action="ask_user", summary=action.value, ok=1, verified=1, screenshot=shot)
                last_ok = True
                continue

            # ---- policy firewall --------------------------------------------------
            verdict = evaluate(action, element, obs.url, ctx)
            secret_value: Optional[str] = None
            self.bus.emit(task_id, "policy", f"Safety check: {verdict.decision.value}" + (f" ({'; '.join(verdict.reasons)})" if verdict.reasons else ""), {"step": idx, "decision": verdict.decision.value, "category": verdict.category})

            if verdict.decision == Decision.DENY:
                failures += 1
                total_failed_steps += 1
                history.append(f"{idx}. {label} -> blocked by safety rules: {'; '.join(verdict.reasons)}")
                self.db.add_step(task_id, idx, url=obs.url, thought=action.thought, action=action.action, mark=action.mark, summary="blocked: " + "; ".join(verdict.reasons), ok=0, verified=0, screenshot=shot)
                last_ok = False
                continue

            if verdict.decision == Decision.ASK:
                approved = await self._wait_user(
                    task_id, control, "confirmation", "confirmation_request",
                    f"Karyakarta wants to: {desc}", {"step": idx, "action": desc, "reasons": verdict.reasons, "category": verdict.category, "url": obs.url},
                )
                if not approved:
                    declines += 1
                    history.append(f"{idx}. {label} -> the user declined this action. Do not try it again.")
                    self.bus.emit(task_id, "notice", "You declined that action.", {"step": idx})
                    self.db.add_step(task_id, idx, url=obs.url, thought=action.thought, action=action.action, mark=action.mark, summary="declined by user", ok=0, verified=0, screenshot=shot)
                    if declines >= MAX_DECLINES:
                        self._finish(task_id, "failed", "Stopped because you declined the agent's actions.", {"steps": idx})
                        return
                    last_ok = False
                    continue
                if element is not None and element.form_id:
                    ctx.approved_forms.add(element.form_id)

            if verdict.decision == Decision.CREDENTIAL:
                kind = "password" if element and element.is_password else "code" if element and element.is_otp else "payment"
                secret_value = await self._wait_user(
                    task_id, control, "credential", "credential_request",
                    f"Karyakarta needs you to enter: {element.label if element else 'a secret value'}",
                    {"step": idx, "label": element.label if element else "", "kind": kind, "is_otp": bool(element and element.is_otp)},
                )
                if element is not None and element.form_id:
                    ctx.credentials_given_forms.add(element.form_id)

            # ---- act ----------------------------------------------------------------
            self.bus.emit(task_id, "action", desc, {"step": idx})
            result = await self._cancellable(
                executor.execute(tb.page, action, element, secret_value=secret_value, viewport_height=s.viewport_height), control
            )
            secret_value = None
            if await tb.adopt_new_page():
                result.new_page = True
            result.notes += tb.take_notes()
            last_ok = result.ok
            if action.action == "extract" and result.answer:
                extracted = result.answer

            self.bus.emit(task_id, "step_result", result.detail, {"step": idx, "ok": result.ok})
            for note in result.notes:
                self.bus.emit(task_id, "notice", note, {"step": idx})
                notices.append(note)

            history.append(f"{idx}. {label} -> (checking...)")
            pending = _PendingStep(
                idx=idx, action=action, label=label, result=result, fingerprint_before=obs.fingerprint,
                thought=action.thought, url=obs.url, shot=shot, model_ms=reply.latency_ms,
                tokens_out=reply.tokens_out, history_index=len(history) - 1, notes=list(result.notes),
            )

        if pending is not None:
            try:
                last = await self._cancellable(self._observe(tb), control)
                self._finalize(task_id, pending, last, history, no_effect, total_failed_steps)
            except Exception:
                pass
        self._finish(task_id, "failed", f"The agent reached the step limit ({s.max_steps}) without finishing.", {"steps": s.max_steps})

    # ---------------------------------------------------------------- pieces
    async def _observe(self, tb: TaskBrowser) -> Observation:
        try:
            return await observe(tb.page)
        except RuntimeError:
            if await tb.adopt_new_page():
                return await observe(tb.page)
            raise

    async def _decide(self, prompt: str, obs: Observation, schema: Optional[dict] = None):
        last: Optional[ModelOutputError] = None
        for attempt in range(2):
            reply = await self.model.chat_json(
                SYSTEM_PROMPT, prompt, [obs.screenshot] if obs.screenshot else [],
                temperature=None if attempt == 0 else 0.5,
                **({"schema": schema} if schema else {}),
            )
            try:
                return parse_action(reply.content), reply
            except ModelOutputError as exc:
                last = exc
        raise last  # type: ignore[misc]

    async def _correct(self, prompt: str, obs: Observation, action: AgentAction, blocked: Optional[tuple], control: TaskControl):
        """If the model picked something unusable or a pointless repeat, ask once
        more with the reply format narrowed to valid choices only."""
        elements = obs.by_ref()
        element = elements.get(action.mark) if action.mark is not None else None
        if action.action == "click" and element is not None and (element.kind in TEXT_KINDS or element.kind == "select"):
            want = "select" if element.kind == "select" else "type"
            marks = [e.ref for e in obs.elements if not e.readonly and ((e.kind == "select") == (want == "select")) and (e.kind in TEXT_KINDS or e.kind == "select")]
            note = f"Your last answer was invalid: [{action.mark}] is a {element.kind} field. To fill a field you must use {want} with a value."
            schema = _narrow_schema([want], marks)
        elif blocked is not None and (action.action, action.mark) == blocked and action.mark is not None:
            marks = [r for r in elements if r != action.mark]
            note = "That exact action already worked but changed nothing, so do not repeat it. If the task is complete use done and put the result in value; otherwise choose a different element."
            schema = _narrow_schema(["click", "type", "select", "done", "fail", "scroll"], marks) if marks else _narrow_schema(["done", "fail"], [])
        else:
            return None
        try:
            return await self._cancellable(self._decide(prompt + f"\nNOTE: {note}", obs, schema), control)
        except ModelOutputError:
            return None

    @staticmethod
    def _window(history: list[str]) -> list[str]:
        if len(history) <= HISTORY_WINDOW:
            return history
        return [f"(... {len(history) - HISTORY_WINDOW} earlier steps omitted)"] + history[-HISTORY_WINDOW:]

    def _finalize(self, task_id: int, p: _PendingStep, obs: Observation, history: list[str], no_effect: int, total_failed: int) -> tuple[int, int]:
        """Judge the previous action by what the page now looks like."""
        changed = obs.fingerprint != p.fingerprint_before
        name = p.action.action
        if not p.result.ok:
            outcome = f"FAILED: {p.result.detail}"
            no_effect += 1
            total_failed += 1
        elif name in ("click", "press", "select", "navigate") and not changed:
            outcome = "ok, but nothing visibly changed"
            no_effect += 1
        elif name == "scroll" and not changed:
            outcome = "ok, but the view did not change"
            no_effect += 1
        elif name == "extract":
            outcome = f"ok, read {len(p.result.answer or '')} characters (shown below)"
            no_effect = 0
        elif name == "type":
            match = re.search(r"\((.*)\)$", p.result.detail)
            outcome = f"ok, field now {match.group(1)}" if match else "ok"
            no_effect = 0
        else:
            outcome = "ok" + (", page changed" if changed and name in ("click", "press", "navigate") else "")
            no_effect = 0
        if p.result.new_page:
            outcome += " (opened a new tab)"
        history[p.history_index] = f"{p.idx}. {p.label} -> {outcome}"
        self.db.add_step(
            task_id, p.idx, url=p.url, thought=p.thought, action=name, mark=p.action.mark,
            summary=p.result.detail, ok=int(p.result.ok), verified=int(p.result.ok and (changed or name in ("type", "extract", "wait"))),
            detail={"changed": changed, "outcome": outcome, "notes": p.notes},
            screenshot=p.shot, model_ms=p.model_ms, tokens_out=p.tokens_out,
        )
        return no_effect, total_failed


class _Stuck(Exception):
    pass
