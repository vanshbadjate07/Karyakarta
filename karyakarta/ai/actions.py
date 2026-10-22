"""Checks a proposed action against the live page BEFORE anything is run, so
a hallucinated element number or a missing argument comes back to the model
as a clear reason instead of becoming a confusing browser error."""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse

from karyakarta.models import TEXT_KINDS, AgentAction, Observation
from karyakarta.safety.policy import allowed_keys


def validate_action(action: AgentAction, obs: Observation) -> Optional[str]:
    """Returns a reason the action is unusable, or None if it is well-formed."""
    name = action.action
    elements = obs.by_ref()

    if name in ("click", "type", "select", "press"):
        if action.mark is None:
            return f"'{name}' needs a mark (an element number from the list)."
        if action.mark not in elements:
            return f"Element [{action.mark}] does not exist. Choose a number from the list."
        element = elements[action.mark]
        if name == "click" and element.kind in TEXT_KINDS:
            return f"[{action.mark}] is a {element.kind} field, not a button. To fill it use type with mark {action.mark} and the value to enter."
        if name == "click" and element.kind == "select":
            return f"[{action.mark}] is a dropdown. Use select with mark {action.mark} and the option text."
        if name == "type":
            if element.kind in ("button", "link", "checkbox", "radio", "select"):
                return f"[{action.mark}] is a {element.kind}, not a text field. Use click or select instead."
            if element.readonly:
                return f"[{action.mark}] is read-only and cannot be typed into."
            if not element.is_secret and (action.value is None or action.value == ""):
                return "type needs a value (the text to enter)."
        if name == "select":
            if element.kind != "select":
                return f"[{action.mark}] is a {element.kind}, not a dropdown."
            if not action.value:
                return "select needs a value (the option text)."
        if name == "press" and (action.value or "Enter") not in allowed_keys():
            return f"Key '{action.value}' is not allowed. Use one of: {', '.join(sorted(allowed_keys()))}."
        return None

    if name == "scroll":
        if (action.value or "down").lower() not in ("up", "down"):
            return "scroll value must be 'up' or 'down'."
        return None

    if name == "navigate":
        value = (action.value or "").strip()
        if not value:
            return "navigate needs a full web address as value."
        parsed = urlparse(value if "://" in value else "https://" + value)
        if not parsed.netloc and not parsed.hostname:
            return "That is not a usable web address."
        return None

    if name in ("ask_user", "fail") and not (action.value or "").strip():
        return f"{name} needs a value explaining what you are asking or why."

    if name == "extract" and action.mark is not None and action.mark not in elements:
        return f"Element [{action.mark}] does not exist."

    return None
