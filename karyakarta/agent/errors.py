"""Turns raw browser and network errors into plain sentences. The original
text is never swallowed: unknown errors keep their first line so a real
problem is still visible instead of being hidden behind a generic message."""
from __future__ import annotations

_RULES: list[tuple[tuple[str, ...], str]] = [
    (("Executable doesn't exist", "playwright install"),
     "The browser component is not installed yet. Run the Karyakarta setup to download it."),
    (("ERR_NAME_NOT_RESOLVED",),
     "That website address could not be found. Check the spelling and your internet connection."),
    (("ERR_INTERNET_DISCONNECTED", "ERR_NETWORK_CHANGED", "ERR_NETWORK_ACCESS_DENIED"),
     "There is no internet connection."),
    (("ERR_CONNECTION_REFUSED", "ERR_CONNECTION_RESET", "ERR_CONNECTION_CLOSED", "ERR_CONNECTION_TIMED_OUT", "ERR_TIMED_OUT"),
     "The website could not be reached. It may be down or blocking connections."),
    (("ERR_CERT", "ERR_SSL"),
     "The website's security certificate is not valid, so the page was not opened."),
    (("intercepts pointer events",),
     "Another element is covering it (a popup or banner may be in the way)."),
    (("is not visible", "outside of the viewport", "element is not stable"),
     "The element is not visible or is still moving."),
    (("Element is not an <input>", "Cannot type into", "not an input"),
     "That element cannot be typed into."),
    (("Target page, context or browser has been closed", "Target closed", "has been closed"),
     "The browser window was closed."),
    (("profile appears to be in use", "ProcessSingleton", "user data directory is already in use"),
     "Another Karyakarta window is already using the browser. Close it and try again."),
]


def humanize_error(exc: BaseException | str) -> str:
    text = str(exc)
    for needles, message in _RULES:
        if any(n.lower() in text.lower() for n in needles):
            return message
    if "Timeout" in text and ("goto" in text or "navigat" in text.lower()):
        return "The page took too long to load."
    if "Timeout" in text:
        return "The page did not respond in time."
    first = text.strip().splitlines()[0] if text.strip() else type(exc).__name__
    return first[:240]
