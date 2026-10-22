"""Starts the local service:  python -m karyakarta"""
import os

import uvicorn

from karyakarta.config import Settings
from karyakarta.main import create_app


def main() -> None:
    settings = Settings.from_env()
    if not os.environ.get("KARYAKARTA_API_TOKEN"):
        print(f"KARYAKARTA_TOKEN={settings.api_token}", flush=True)
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
