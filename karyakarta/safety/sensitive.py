"""Plain pattern checks that decide whether a form field holds a secret.
No model is involved: these run on the field's own attributes."""
from __future__ import annotations

import re

_OTP = re.compile(
    r"one[\s_-]?time|\botp\b|verification[\s_-]?code|auth(entication)?[\s_-]?code|\b2fa\b|"
    r"sms[\s_-]?code|passcode|security[\s_-]?token",
    re.I,
)
_PAYMENT = re.compile(
    r"card[\s_-]?number|credit[\s_-]?card|debit[\s_-]?card|\bcvv\b|\bcvc\b|\bcvn\b|"
    r"expir(y|ation)|card[\s_-]?holder|routing[\s_-]?number|bank[\s_-]?account|"
    r"account[\s_-]?number|\biban\b|\bswift\b|\bupi\b",
    re.I,
)
_PASSWORD = re.compile(r"pass(word|wd|code)?\b|\bpwd\b|\bpin\b", re.I)


def _haystack(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def is_password(field_type: str, name: str, id_: str, label: str, autocomplete: str) -> bool:
    if (field_type or "").lower() == "password":
        return True
    if "password" in (autocomplete or "").lower():
        return True
    return False


def is_otp(name: str, id_: str, label: str, placeholder: str, autocomplete: str) -> bool:
    if "one-time-code" in (autocomplete or "").lower():
        return True
    return bool(_OTP.search(_haystack(name, id_, label, placeholder)))


def is_payment(name: str, id_: str, label: str, placeholder: str, autocomplete: str) -> bool:
    if (autocomplete or "").lower().startswith("cc-"):
        return True
    return bool(_PAYMENT.search(_haystack(name, id_, label, placeholder)))


_SECRET_WORDS = re.compile(
    r"pass(word|wd|code)|\bpwd\b|\bpin\b|\botp\b|one[\s_-]?time|verification[\s_-]?code|"
    r"\bcvv\b|\bcvc\b|card[\s_-]?number|credit[\s_-]?card|security[\s_-]?code|\bsecret\b",
    re.I,
)


def mentions_secret(text: str) -> bool:
    """True if text asks for or talks about a password, code or card detail."""
    return bool(_SECRET_WORDS.search(text or ""))
