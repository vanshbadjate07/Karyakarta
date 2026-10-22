# Karyakarta Backend

The agent service: local model runtime client, browser control, policy firewall, storage and the local HTTP/WebSocket interface used by the desktop app.

The full project description, safety model and roadmap are in the repository's main README.

## Run

```bash
uv sync
uv run playwright install chromium
ollama pull qwen3-vl:2b-instruct
uv run python -m karyakarta
```

The service listens on `127.0.0.1:8765` and prints a `KARYAKARTA_TOKEN=...` line. Send it as the `X-Karyakarta-Token` header (WebSocket: `?token=`). Set `KARYAKARTA_API_TOKEN` to use a fixed token.

## Test

```bash
uv run pytest              # fast suite (real Chromium, scripted model)
uv run pytest -m live -s   # real local model on the test sites
```

## Layout

```
karyakarta/api       local HTTP interface and live stream
karyakarta/agent     agent loop, task queue, events, error wording
karyakarta/ai        local model client, prompts, action validation
karyakarta/browser   browser session, page capture, action executor
karyakarta/safety    policy firewall, injection filter, secret-field checks
karyakarta/storage   SQLite storage
tests/               unit, browser, agent, interface, chaos and live tests
tests/site/          local test websites
```
