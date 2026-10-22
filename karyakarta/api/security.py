"""The control service is bound to this computer only, but any web page the
user visits could still try to reach it. Two checks stop that:
  1. every request must carry the per-launch secret token;
  2. the Host header must be a local name (blocks DNS-rebinding tricks).
"""
from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, WebSocket
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

TOKEN_HEADER = "X-Karyakarta-Token"


def _allowed_hosts(port: int) -> set[str]:
    return {f"127.0.0.1:{port}", f"localhost:{port}", "127.0.0.1", "localhost", f"[::1]:{port}"}


class LocalHostOnly(BaseHTTPMiddleware):
    def __init__(self, app, port: int):
        super().__init__(app)
        self._hosts = _allowed_hosts(port)

    async def dispatch(self, request: Request, call_next):
        if (request.headers.get("host") or "").lower() not in self._hosts:
            return JSONResponse({"detail": "Forbidden host."}, status_code=403)
        return await call_next(request)


def require_token(request: Request) -> None:
    expected = request.app.state.settings.api_token
    given = request.headers.get(TOKEN_HEADER, "")
    if not secrets.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="Missing or wrong access token.")


def websocket_token_ok(websocket: WebSocket) -> bool:
    expected = websocket.app.state.settings.api_token
    given = websocket.query_params.get("token", "")
    host = (websocket.headers.get("host") or "").lower()
    port = websocket.app.state.settings.port
    return secrets.compare_digest(given, expected) and host in _allowed_hosts(port)
