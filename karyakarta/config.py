"""Runtime settings. Everything is overridable with KARYAKARTA_* environment
variables so tests and packaged builds never touch the user's real data."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "Karyakarta"
DEFAULT_MODEL = "qwen3-vl:2b-instruct"


def _env(name: str, default: str) -> str:
    return os.environ.get(f"KARYAKARTA_{name}", default)


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, "1" if default else "0").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765
    api_token: str = ""
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = DEFAULT_MODEL
    num_ctx: int = 6144
    temperature: float = 0.1
    model_timeout_s: float = 240.0
    keep_alive: str = "30m"
    headless: bool = False
    viewport_width: int = 1280
    viewport_height: int = 800
    max_steps: int = 30
    max_consecutive_failures: int = 4
    allow_private_hosts: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_dir / "karyakarta.db"

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(_env("DATA_DIR", user_data_dir(APP_NAME, appauthor=False)))
        return cls(
            data_dir=data_dir,
            host=_env("HOST", "127.0.0.1"),
            port=int(_env("PORT", "8765")),
            api_token=_env("API_TOKEN", "") or secrets.token_urlsafe(32),
            ollama_url=_env("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/"),
            model=_env("MODEL", DEFAULT_MODEL),
            num_ctx=int(_env("NUM_CTX", "6144")),
            headless=_env_bool("HEADLESS", False),
            viewport_width=int(_env("VIEWPORT_WIDTH", "1280")),
            viewport_height=int(_env("VIEWPORT_HEIGHT", "800")),
            max_steps=int(_env("MAX_STEPS", "30")),
            allow_private_hosts=_env_bool("ALLOW_PRIVATE_HOSTS", False),
        )

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.profile_dir, self.runs_dir):
            path.mkdir(parents=True, exist_ok=True)
