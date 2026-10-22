"""Policy firewall: every action the model proposes passes through here
before it touches the browser.

All rules are plain checks on the action, the target element's own
attributes and the page address. Nothing here asks the model whether
something is safe, and nothing the model writes (its thought, a "safe" flag)
can lower a decision. A page can say anything it likes; it cannot change
these rules.
"""
from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from karyakarta.models import AgentAction, Element


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"                # needs the user's yes before running
    CREDENTIAL = "credential"  # the user must type the value; the model never sees it
    DENY = "deny"              # never allowed


@dataclass
class Verdict:
    decision: Decision
    reasons: list[str] = field(default_factory=list)
    category: str = ""


@dataclass
class PolicyContext:
    start_host: str = ""
    allow_private_hosts: bool = False
    own_ports: frozenset[int] = frozenset()
    injection_suspected: bool = False
    credentials_given_forms: set[str] = field(default_factory=set)
    approved_forms: set[str] = field(default_factory=set)


_IRREVERSIBLE = re.compile(
    r"\b(submit|pay|pay\s*now|buy|buy\s*now|purchase|place\s*(your\s*)?order|check\s*out|checkout|"
    r"confirm\s*(order|payment|purchase|booking|reservation)|delete|remove\s*(account|all)|deactivate|"
    r"close\s*account|cancel\s*(order|subscription|booking|membership)|unsubscribe|transfer|withdraw|"
    r"send\s*money|donate|book\s*now|complete\s*(purchase|order|booking)|finali[sz]e|sign\s*up|"
    r"register|create\s*account|send(\s*message)?|post(\s*comment)?|publish|apply\s*(now|for)|"
    r"subscribe|agree\s*(and|&)\s*(continue|pay))\b",
    re.I,
)
_PAYMENT_URL = re.compile(r"checkout|payment|billing|\bpay\b|stripe\.com|paypal\.com|razorpay|paytm", re.I)
_ALLOWED_KEYS = frozenset(
    {"Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight", "PageDown", "PageUp", "Space", "Backspace"}
)


def allowed_keys() -> frozenset[str]:
    return _ALLOWED_KEYS


def classify_form(fields: list[dict]) -> str:
    """Names what kind of form this is from its own fields.
    fields: [{'kind': 'password'|'search'|'text'|..., 'name': str, 'is_payment': bool, 'role': str}]"""
    if not fields:
        return ""
    if any(f.get("is_payment") for f in fields):
        return "payment"
    passwords = sum(1 for f in fields if f.get("kind") == "password")
    if passwords >= 2:
        return "signup"
    if passwords == 1:
        text_like = sum(1 for f in fields if f.get("kind") in ("text", "email", "tel"))
        return "signup" if text_like >= 3 else "login"
    if any(f.get("role") == "search" for f in fields):
        return "search"
    inputs = [f for f in fields if f.get("kind") in ("text", "search", "email", "tel", "number", "textarea", "select")]
    if len(inputs) == 1 and (
        inputs[0].get("kind") == "search"
        or re.fullmatch(r"(q|s|search|query|keyword|keywords|term|text)", (inputs[0].get("name") or "").lower())
    ):
        return "search"
    return "generic"


_EXPLICIT_SCHEME = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):(?!\d+(?:/|$))")


def parse_target(url: str):
    """Parses an address the way a person means it: 'example.com' is a website,
    'localhost:3000' is a host and port, but 'javascript:...' and 'data:...' are
    real schemes and must never be mistaken for a website."""
    url = (url or "").strip()
    if "://" in url:
        return urlparse(url)
    match = _EXPLICIT_SCHEME.match(url)
    if match:
        return urlparse(url)
    return urlparse("https://" + url)


def normalize_url(url: str) -> str:
    return parse_target(url).geturl()


def _host_is_private(host: str) -> bool:
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def _evaluate_navigation(url: str, page_host: str, ctx: PolicyContext) -> Verdict:
    parsed = parse_target(url)
    if parsed.scheme not in ("http", "https"):
        return Verdict(Decision.DENY, [f"Blocked: '{parsed.scheme or 'unknown'}' addresses are not allowed"], "navigation")
    host = (parsed.hostname or "").lower()
    if not host:
        return Verdict(Decision.DENY, ["Blocked: the address has no website name"], "navigation")
    if _host_is_private(host):
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port in ctx.own_ports:
            return Verdict(Decision.DENY, ["Blocked: that address is Karyakarta's own control service"], "navigation")
        if not ctx.allow_private_hosts and host != ctx.start_host:
            return Verdict(Decision.ASK, [f"This opens an address on your own computer or network ({host})"], "navigation")
    if _PAYMENT_URL.search(url):
        return Verdict(Decision.ASK, ["This opens what looks like a payment or checkout page"], "payment")
    if ctx.injection_suspected and host != page_host:
        return Verdict(Decision.ASK, ["The page contained suspicious instructions and now wants to open another site"], "injection")
    return Verdict(Decision.ALLOW)


def _submit_verdict(element: Element, ctx: PolicyContext, what: str) -> Optional[Verdict]:
    kind = element.form_kind
    if kind == "search":
        return None
    if kind == "login":
        if element.form_id in ctx.credentials_given_forms or element.form_id in ctx.approved_forms:
            return None
        return Verdict(Decision.ASK, [f"{what} would log in to an account"], "login")
    if element.form_id in ctx.approved_forms:
        return None
    labels = {
        "payment": "would send payment details",
        "signup": "would create an account",
        "generic": "would submit a form",
    }
    return Verdict(Decision.ASK, [f"{what} {labels.get(kind, 'would submit a form')}"], "submit")


def evaluate(action: AgentAction, element: Optional[Element], page_url: str, ctx: PolicyContext) -> Verdict:
    name = action.action
    page_host = (urlparse(page_url).hostname or "").lower()

    if name == "navigate":
        return _evaluate_navigation(action.value or "", page_host, ctx)

    if name in ("wait", "scroll", "extract", "ask_user", "done", "fail"):
        return Verdict(Decision.ALLOW)

    if element is None:
        return Verdict(Decision.ALLOW)

    if element.kind == "file":
        return Verdict(Decision.DENY, ["File uploads are not supported yet, so the agent will not open a file picker"], "upload")

    label = element.label.strip() or element.kind

    if name == "type":
        if element.is_secret:
            kind = "password" if element.is_password else "one-time code" if element.is_otp else "payment detail"
            return Verdict(Decision.CREDENTIAL, [f"'{label}' is a {kind} field. You must enter it yourself"], "credential")
        if ctx.injection_suspected:
            return Verdict(Decision.ASK, ["The page contained suspicious instructions and now wants text typed into it"], "injection")
        return Verdict(Decision.ALLOW)

    if name == "press":
        if (action.value or "") == "Enter" and element.form_id and element.kind not in ("button", "link"):
            verdict = _submit_verdict(element, ctx, f"Pressing Enter in '{label}'")
            if verdict:
                return verdict
        return Verdict(Decision.ALLOW)

    if name == "select":
        if ctx.injection_suspected:
            return Verdict(Decision.ASK, ["The page contained suspicious instructions"], "injection")
        return Verdict(Decision.ALLOW)

    if name == "click":
        if element.kind == "link" and _PAYMENT_URL.search(element.href or ""):
            return Verdict(Decision.ASK, [f"Link '{label}' leads to what looks like a payment page"], "payment")
        if element.submits_form:
            return _submit_verdict(element, ctx, f"Button '{label}'") or Verdict(Decision.ALLOW)
        if element.kind in ("button", "link") and _IRREVERSIBLE.search(element.label or "") and element.form_kind != "search":
            return Verdict(Decision.ASK, [f"'{label}' looks like an action that cannot be undone"], "irreversible")
        if ctx.injection_suspected and element.kind == "link" and element.href and not element.href.startswith("/"):
            host = element.href.split("/")[0].lower()
            if host and host != page_host:
                return Verdict(Decision.ASK, ["The page contained suspicious instructions and this link leaves the site"], "injection")
        return Verdict(Decision.ALLOW)

    return Verdict(Decision.ALLOW)

    return Verdict(Decision.ALLOW)
