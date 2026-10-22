"""First layer of prompt-injection defence: find and remove instruction-like
text that a web page tries to slip to the agent.

This is deliberately only a first layer. The real protection is structural:
page text is always given to the model as untrusted data, and every action the
model proposes still has to pass the policy firewall no matter what it read.
"""
from __future__ import annotations

import re

_REMOVED = "[removed: instruction-like text from the page]"

_PATTERNS = [
    r"ignore\s+(all\s+|any\s+|the\s+|your\s+)*(previous|prior|above|earlier|preceding)\s+(instructions?|prompts?|messages?|rules?|directions?)",
    r"disregard\s+(all\s+|any\s+|the\s+|your\s+)*(previous|prior|above|earlier|preceding|system)?\s*(instructions?|prompts?|rules?)",
    r"forget\s+(everything|all|your|the)\s+(instructions?|rules?|above|previous)",
    r"(new|updated|additional|override|secret)\s+(system\s+)?(instructions?|prompt|rules?|task)\s*(for|:)",
    r"\b(system|developer)\s+(prompt|message|override|instructions?)\b",
    r"you\s+are\s+(now|no\s+longer)\s+(an?\s+|the\s+)?\w+",
    r"(do\s+not|don'?t|never)\s+(tell|inform|show|alert|notify|reveal\s+(this\s+)?to)\s+(the\s+)?user",
    r"(act|behave|pretend|respond)\s+as\s+(if\s+you\s+(are|were)|an?\s)",
    r"(send|forward|email|post|upload|transfer|submit|leak)\b[^.\n]{0,80}\b(password|credentials?|cookies?|session|token|api\s*key|secret|ssn|card\s*number|personal\s+(data|information))",
    r"<\s*/?\s*(system|assistant|instructions?|prompt)\s*>",
    r"\[\s*/?\s*(system|inst|instructions?)\s*\]",
    r"important\s+(instructions?\s+)?for\s+(the\s+)?(ai|assistant|agent|llm|model|automation)",
    r"\b(ai|llm|agent|assistant|bot)\s*[,:]\s*(please\s+)?(ignore|click|navigate|open|visit|send|type|enter|download|run|execute)",
]
_COMPILED = [re.compile(p, re.I) for p in _PATTERNS]


def find_injections(text: str) -> list[str]:
    """Returns short snippets of any suspicious instruction-like text."""
    findings: list[str] = []
    for pattern in _COMPILED:
        for match in pattern.finditer(text or ""):
            snippet = " ".join(match.group(0).split())[:80]
            if snippet not in findings:
                findings.append(snippet)
    return findings


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LONG_SENTENCE = 300
_TAIL_AFTER_MATCH = 200


def _strip_long(sentence: str) -> str:
    """For a run of text with no sentence breaks, cut only a window around each hit."""
    for pattern in _COMPILED:
        while True:
            match = pattern.search(sentence)
            if not match:
                break
            end = min(len(sentence), match.end() + _TAIL_AFTER_MATCH)
            sentence = sentence[: match.start()] + _REMOVED + sentence[end:]
    return sentence


def _sanitize_line(line: str) -> str:
    out: list[str] = []
    for sentence in _SENTENCE_END.split(line):
        if not any(p.search(sentence) for p in _COMPILED):
            out.append(sentence)
        elif len(sentence) > _LONG_SENTENCE:
            out.append(_strip_long(sentence))
        elif not out or out[-1] != _REMOVED:
            out.append(_REMOVED)
    return " ".join(out)


def sanitize(text: str) -> tuple[str, list[str]]:
    """Returns the text with every sentence that contains an injection attempt
    replaced (not just the trigger phrase, so the payload after it goes too),
    plus what was found. Block breaks (newlines) are kept, so removing one
    paragraph never swallows the real content next to it."""
    findings = find_injections(text)
    if not findings:
        return text or "", []
    return "\n".join(_sanitize_line(line) for line in text.split("\n")), findings
