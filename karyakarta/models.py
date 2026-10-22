"""Shared data types. Kept in one dependency-free module so the model client,
browser layer, safety firewall and agent loop can all use them without
importing each other."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

ACTION_NAMES = (
    "click", "type", "select", "press", "scroll", "navigate",
    "wait", "extract", "ask_user", "done", "fail",
)
TEXT_KINDS = frozenset({"text", "email", "password", "tel", "number", "search", "url", "date", "textarea"})
ActionName = Literal[
    "click", "type", "select", "press", "scroll", "navigate",
    "wait", "extract", "ask_user", "done", "fail",
]

# Strict output format the local model is forced to follow (constrained
# decoding), so every reply is a parseable action or it is rejected.
ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "thought": {"type": "string"},
        "action": {"type": "string", "enum": list(ACTION_NAMES)},
        "mark": {"type": "integer"},
        "value": {"type": "string"},
    },
    "required": ["thought", "action"],
}


class AgentAction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    thought: str = ""
    action: ActionName
    mark: Optional[int] = None
    value: Optional[str] = None

    def short(self) -> str:
        parts = [self.action]
        if self.mark is not None:
            parts.append(f"[{self.mark}]")
        if self.value:
            parts.append(repr(self.value if len(self.value) <= 60 else self.value[:57] + "..."))
        return " ".join(parts)


@dataclass
class Element:
    ref: int
    tag: str
    kind: str
    label: str
    value: str = ""
    checked: Optional[bool] = None
    disabled: bool = False
    readonly: bool = False
    required: bool = False
    href: str = ""
    options: list[str] = field(default_factory=list)
    in_viewport: bool = True
    submits_form: bool = False
    form_kind: str = ""
    form_id: str = ""
    is_password: bool = False
    is_otp: bool = False
    is_payment: bool = False
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)

    @property
    def is_secret(self) -> bool:
        return self.is_password or self.is_otp or self.is_payment

    def line(self) -> str:
        """One compact line for the model prompt. Secrets are never shown."""
        parts = [f"[{self.ref}] {self.kind}"]
        if self.label:
            label = self.label if len(self.label) <= 70 else self.label[:67] + "..."
            parts.append(f'"{label}"')
        if self.is_secret:
            parts.append("(secret field)")
        elif self.value and self.kind not in ("button", "link", "checkbox", "radio"):
            value = self.value if len(self.value) <= 40 else self.value[:37] + "..."
            parts.append(f'value="{value}"')
        if self.checked is not None:
            parts.append("checked" if self.checked else "unchecked")
        if self.options:
            parts.append("options=" + "|".join(self.options[:8]))
        if self.href and self.kind == "link":
            parts.append(f"-> {self.href}")
        if self.required:
            parts.append("required")
        if self.readonly:
            parts.append("readonly")
        if self.kind in TEXT_KINDS:
            parts.append("=> use type")
        elif self.kind == "select":
            parts.append("=> use select")
        else:
            parts.append("=> use click")
        return " ".join(parts)


@dataclass
class Observation:
    url: str
    title: str
    elements: list[Element]
    text: str
    scroll_y: int
    scroll_max: int
    above: int = 0
    below: int = 0
    hidden_in_view: int = 0
    injection: list[str] = field(default_factory=list)
    fingerprint: str = ""
    screenshot: bytes = b""

    def by_ref(self) -> dict[int, Element]:
        return {e.ref: e for e in self.elements}


@dataclass
class ActionResult:
    ok: bool
    detail: str
    changed: bool = False
    url_after: str = ""
    new_page: bool = False
    notes: list[str] = field(default_factory=list)
    answer: Optional[str] = None
