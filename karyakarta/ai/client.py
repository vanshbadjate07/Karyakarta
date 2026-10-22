"""Client for the local model runtime (Ollama's HTTP interface on this
machine). Nothing here talks to the internet except the one-time model
download, which the user starts explicitly.

Every failure is raised as a ModelError subclass carrying a message that is
safe and useful to show the user as-is: failures must be loud and specific,
never silently turned into a fake answer.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator, Optional

import httpx
from pydantic import ValidationError

from karyakarta.models import ACTION_SCHEMA, AgentAction


class ModelError(Exception):
    """A model problem described in words a user can act on."""


class ModelUnavailableError(ModelError):
    pass


class ModelMissingError(ModelError):
    pass


class ModelOutputError(ModelError):
    pass


@dataclass
class ModelReply:
    content: str
    latency_ms: int
    tokens_in: int
    tokens_out: int


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        num_ctx: int = 6144,
        temperature: float = 0.1,
        timeout_s: float = 240.0,
        keep_alive: str = "30m",
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.model = model
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.keep_alive = keep_alive
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_s, connect=3.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---- status -----------------------------------------------------------
    async def status(self) -> dict[str, Any]:
        try:
            version = (await self._http.get("/api/version")).json().get("version")
            tags = (await self._http.get("/api/tags")).json().get("models", [])
        except httpx.HTTPError:
            return {"engine_running": False, "engine_version": None, "model": self.model,
                    "model_installed": False, "installed_models": []}
        names = [m.get("name", "") for m in tags]
        wanted = self.model if ":" in self.model else self.model + ":latest"
        return {
            "engine_running": True,
            "engine_version": version,
            "model": self.model,
            "model_installed": wanted in names,
            "installed_models": names,
        }

    # ---- chat -------------------------------------------------------------
    async def chat_json(
        self,
        system: str,
        user_text: str,
        images: list[bytes],
        *,
        schema: dict = ACTION_SCHEMA,
        temperature: Optional[float] = None,
        max_tokens: int = 400,
    ) -> ModelReply:
        user_message: dict[str, Any] = {"role": "user", "content": user_text}
        if images:
            user_message["images"] = [base64.b64encode(img).decode("ascii") for img in images]
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, user_message],
            "stream": False,
            "format": schema,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_ctx": self.num_ctx,
                "num_predict": max_tokens,
            },
        }
        try:
            resp = await self._http.post("/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise ModelUnavailableError(
                "The local AI engine is not running. Start Ollama and try again."
            ) from exc
        except httpx.TimeoutException as exc:
            raise ModelError(
                "The local model took too long to answer. Close other heavy apps and try again."
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelError(f"Could not reach the local AI engine: {exc}") from exc

        if resp.status_code == 404:
            raise ModelMissingError(
                f"The model '{self.model}' is not installed yet. Download it from Settings."
            )
        if resp.status_code >= 400:
            detail = _error_text(resp)
            raise ModelError(f"The local AI engine returned an error: {detail}")

        data = resp.json()
        content = (data.get("message") or {}).get("content", "")
        return ModelReply(
            content=content,
            latency_ms=int((data.get("total_duration") or 0) / 1_000_000),
            tokens_in=int(data.get("prompt_eval_count") or 0),
            tokens_out=int(data.get("eval_count") or 0),
        )

    # ---- model download ---------------------------------------------------
    async def pull(self) -> AsyncIterator[dict[str, Any]]:
        """Streams download progress dicts: {status, total, completed}."""
        try:
            async with self._http.stream(
                "POST", "/api/pull", json={"model": self.model, "stream": True},
                timeout=httpx.Timeout(None, connect=3.0),
            ) as resp:
                if resp.status_code >= 400:
                    raise ModelError(f"Model download failed: {(await resp.aread()).decode()[:200]}")
                async for line in resp.aiter_lines():
                    if line.strip():
                        yield json.loads(line)
        except httpx.ConnectError as exc:
            raise ModelUnavailableError(
                "The local AI engine is not running. Start Ollama and try again."
            ) from exc
        except httpx.HTTPError as exc:
            raise ModelError(f"Model download was interrupted: {exc}") from exc


def _error_text(resp: httpx.Response) -> str:
    try:
        return str(resp.json().get("error", resp.text))[:300]
    except ValueError:
        return resp.text[:300]


_JSON_OBJECT = re.compile(r"\{.*\}", re.S)


def parse_action(content: str) -> AgentAction:
    """Turns the model's reply into an AgentAction or raises ModelOutputError."""
    text = (content or "").strip()
    if not text:
        raise ModelOutputError("The model returned an empty answer.")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(text)
        if not match:
            raise ModelOutputError("The model's answer was not valid JSON.")
        try:
            raw = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ModelOutputError("The model's answer was not valid JSON.") from exc
    if not isinstance(raw, dict):
        raise ModelOutputError("The model's answer was not a JSON object.")
    try:
        return AgentAction.model_validate(raw)
    except ValidationError as exc:
        raise ModelOutputError(f"The model's answer did not match the action format: {exc.errors()[0]['msg']}") from exc
