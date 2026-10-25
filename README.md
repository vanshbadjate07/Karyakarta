# Karyakarta

**A local-first AI agent that operates a web browser for you.**
Describe a task in plain language. Karyakarta opens a real browser, works out the steps, and does the task while you watch. Every risky step waits for your approval, and passwords never pass through the AI.

> Final-year B.Tech project (AI & ML), Sanjivani University, Kopargaon.
> Team: Vansh Badjate, Gaurav Nimbalkar, Vaishnavi Nikumbh, Aditya Hon. Guide: Prof. Deependra Shukla.

---

## Contents

1. [What it does](#what-it-does)
2. [Why it is different](#why-it-is-different)
3. [How it works](#how-it-works)
4. [The desktop app](#the-desktop-app)
5. [Safety model](#safety-model)
6. [Architecture and repository layout](#architecture-and-repository-layout)
7. [Tech stack](#tech-stack)
8. [Getting started](#getting-started)
9. [Using the local service](#using-the-local-service)
10. [Testing](#testing)
11. [Project status and roadmap](#project-status-and-roadmap)
12. [Branch workflow](#branch-workflow)
13. [Research background](#research-background)
14. [Limitations](#limitations)
15. [License](#license)

---

## What it does

You type something like *"Fill the contact form with my details and send it"* or *"Find the price of this book"*. Karyakarta then:

- opens a **real, visible browser** and reads the page the way a person does,
- picks **one action at a time** (type, click, select, scroll, open a page, read text),
- **checks every action** against the live page and a rule-based safety layer,
- **verifies the result** (what the field now contains, whether the page really changed) before moving on,
- shows **everything it does** in a live activity log, so nothing happens silently,
- **asks you** before anything that cannot be undone, and asks you to type passwords and codes yourself.

## Why it is different

| Most browser agents | Karyakarta |
|---|---|
| Closed products, run on someone else's servers | Open code, runs on your own computer with an open-source model |
| The AI itself decides when to ask for confirmation | A **rule engine written in code** decides; the AI cannot skip it |
| Trust whatever text a web page contains | Page text is treated as **untrusted data**; instruction-like text is stripped and flagged |
| Success is the agent's own claim | Every action is **verified in code** (read-back, page-change check) |
| Reported success rates from live, changing sites | A **deterministic, code-checked test suite** on local replayable sites |

Planned on top of this core (see the [roadmap](#project-status-and-roadmap)): a model **fine-tuned by the team** and improved only from runs that code confirmed as successful, an **MCP** tool server with the same safety firewall, and **RAG memory** over the user's own documents with sources shown.

## How it works

```
 task ──► capture page ──► local model picks ONE action ──► validate ──► safety firewall ──► perform ──► verify
              ▲                                                │ rejected / blocked              │
              │                                                ▼                                 │
              └───────────── result and reason fed back to the model ◄───────────────────────────┘
```

1. **Capture.** Playwright reads the page once: a screenshot with numbered coloured boxes on every usable element, a compact text list of the same elements, and the text visible on screen. Each element is tagged inside the page, so the number the model picks always points at the element it was shown.
2. **Decide.** A small vision-language model running locally (Qwen3-VL 2B, Apache-2.0) answers with one action in a **strict JSON format** that the runtime forces it to follow.
3. **Validate.** The action is checked against the live page. An invented element number or a missing value is sent back to the model with a plain reason instead of reaching the browser.
4. **Safety firewall.** Rules decide: allow, ask the user, require the user to type a secret, or deny.
5. **Perform and verify.** The action runs, then the result is read back: the value a field now holds, whether a checkbox really flipped, whether the page changed.
6. **Repeat** until the model reports done and its last action did not fail, the user cancels, or a limit is reached.

Failures are loud and specific: if the local model is not running, the model is missing, or the browser cannot start, the task stops with a message that says what to do.

## The desktop app

An Electron and React app, light and minimal, built around one idea: you should always see what the agent is doing and stay in control.

- **Home:** describe a task in plain words, optionally start on a website, or pick a suggestion.
- **Work view:** a timeline of every step (what it did, why, a "Verified" tag, how long the AI took) beside a live view of the page the agent is looking at, with the same numbered marks the model sees. Finished tasks can be replayed step by step.
- **Approvals in place:** when a step needs your yes, a card appears right in the timeline with the exact action and the reason it was flagged.
- **Secure entry:** passwords, codes and card numbers go into a masked box and straight to the website. They are not stored and the AI never sees them.
- **History:** tasks are grouped by day and can be reopened, replayed, re-run or deleted.
- **Setup check:** shows whether the local AI engine, the model and the browser component are ready, and downloads the model with progress.
- **Resilient connection:** the live stream reconnects by itself and falls back to polling.

The page itself has no access to Node. The desktop shell starts the service on a random port with a one-time secret token, hands both to the page through a narrow bridge, blocks other navigation, refuses browser permissions, and stops the service on quit.

## Safety model

All rules are plain checks on the action, the element's own attributes and the page address. Nothing asks the AI whether something is safe.

| Situation | Behaviour |
|---|---|
| Password, one-time code, card number, CVV fields | The **user types the value**. The model never sees it, never chooses it, and it is never stored or logged |
| Final submit of a form (including a button labelled "Next" that actually submits) | **Ask the user first** |
| Payment, checkout, delete, send, register and similar buttons | **Ask the user first** |
| Search forms | Allowed without asking (avoids pointless prompts) |
| `javascript:`, `file:`, `data:` and other non-web addresses | **Denied** |
| The agent's own control service | **Denied**, so a page cannot make the agent steer itself |
| Addresses on the user's own network | Ask first |
| File uploads | Denied for now, because the agent must not open a file picker |
| Downloads | Blocked and reported |
| JavaScript alert / confirm dialogs | Alerts are accepted so pages cannot freeze; confirm and prompt dialogs are dismissed, because they ask the user a question |
| Page contains instruction-like text ("ignore previous instructions...") | The whole sentence is removed, the user is warned, and leaving the site or typing text then needs approval |
| The model asks the user for a password in chat | Refused; secrets only go through the secure field prompt |

The local control service is also hardened: it only accepts requests that carry a **per-launch secret token**, only from local host names (blocking DNS-rebinding tricks), and only from the app's own origins.

## Architecture and repository layout

The repository has two applications that are developed on separate branches and merged for integration testing.

```
Karyakarta/
├── Frontend/                  Desktop app (Electron + React + TypeScript)      branch: Frontend
└── Backend/                   Agent service: model runtime, browser, safety    branch: Backend
    ├── karyakarta/
    │   ├── api/               Local HTTP interface and live WebSocket stream
    │   ├── agent/             Agent loop, task queue, live event stream, error wording
    │   ├── ai/                Local model client, prompts, action validation
    │   ├── browser/           Browser session, page capture, action executor
    │   ├── safety/            Policy firewall, injection filter, secret-field checks
    │   └── storage/           SQLite: tasks, activity events, structured steps
    └── tests/                 Unit, browser, agent-loop, interface, chaos and live tests
        └── site/              Local test websites used by the tests
```

The desktop app talks to the local service over HTTP and a WebSocket. Everything the agent does is saved as an event, so a screen opened late (or after a restart) still shows the complete history, and every step is stored with its screenshot for replay.

## Tech stack

| Layer | Choice |
|---|---|
| Model | Qwen3-VL 2B Instruct (Apache-2.0), served locally by Ollama |
| Backend | Python 3.12, FastAPI, WebSocket, SQLite |
| Browser control | Playwright (real Chromium, persistent profile) |
| Frontend | Electron, React, TypeScript, Vite |
| Testing | pytest and real Chromium against local test sites (backend); Vitest and React Testing Library (app) |
| Planned | QLoRA fine-tuning (Hugging Face PEFT), MCP, SQLite FTS5 + sqlite-vec for RAG, BrowserGym for standard benchmarks |

Everything is free and open source.

## Getting started

### Platforms

Karyakarta is built for **Windows and macOS** from the start: paths and data folders use each system's own conventions, the desktop shell starts and stops the service the right way on each, and the local AI engine and browser component both exist for both. The automated tests of both applications run on Windows, macOS and Linux on every push (GitHub Actions). The installers for both systems come in the last milestone.

### Requirements

- Windows 10 or later, or macOS
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com) installed and running
- About 2 GB of free disk space for the model, plus the browser component

### Backend

```bash
cd Backend
uv sync                                   # installs Python 3.12 dependencies
uv run playwright install chromium        # one-time browser download
ollama pull qwen3-vl:2b-instruct          # one-time model download (about 1.9 GB)
uv run python -m karyakarta               # starts the service on 127.0.0.1:8765
```

On start the service prints `KARYAKARTA_TOKEN=...`. Every request must send it in the `X-Karyakarta-Token` header (the desktop app does this automatically). To use a fixed token, set `KARYAKARTA_API_TOKEN` before starting.

Useful settings (environment variables, all optional):

| Variable | Default | Meaning |
|---|---|---|
| `KARYAKARTA_MODEL` | `qwen3-vl:2b-instruct` | Local model to use |
| `KARYAKARTA_PORT` | `8765` | Port of the local service |
| `KARYAKARTA_HEADLESS` | `0` | `1` hides the browser window |
| `KARYAKARTA_MAX_STEPS` | `30` | Step limit per task |
| `KARYAKARTA_DATA_DIR` | OS app-data folder | Where history, screenshots and the browser profile live |

### Frontend

```bash
cd Frontend
npm install
npm run build
npm start        # opens the desktop app; it starts the service from ../Backend for you
```

See the `Frontend` branch README for developing the interface in a browser and for all settings.

## Using the local service

All routes except `/api/health` need the token header.

| Route | Purpose |
|---|---|
| `GET /api/health` | Liveness check |
| `GET /api/system/status` | Is the model engine running, is the model installed, is the browser installed |
| `POST /api/system/model/pull` | Download the model, streaming progress |
| `POST /api/tasks` | Start a task: `{"instruction": "...", "start_url": "optional"}` |
| `GET /api/tasks`, `GET /api/tasks/{id}` | History and one task with its steps |
| `GET /api/tasks/{id}/events` | Saved activity events |
| `GET /api/tasks/{id}/screenshots/{file}` | A step's screenshot (for replay) |
| `POST /api/tasks/{id}/confirm` | Approve or decline a pending action |
| `POST /api/tasks/{id}/credential` | Provide a password or code when asked |
| `POST /api/tasks/{id}/answer` | Answer a question from the agent |
| `POST /api/tasks/{id}/cancel`, `DELETE /api/tasks/{id}` | Stop a task, delete finished history |
| `WS /api/ws/tasks/{id}?token=...` | Live activity stream (history first, then live) |

Tasks run one at a time (one browser, one model). Up to 20 can wait in the queue.

## Testing

```bash
cd Backend
uv run pytest                  # fast suite: unit, real-browser, agent-loop, interface, chaos
uv run pytest -m live -s       # real model + real browser on the local test sites
```

The fast suite runs a real Chromium against local test websites (forms, login, search, checkout, popups, cookie banners, a page with thousands of elements, a page that spams alerts, a page with hidden prompt-injection text). Only the model is scripted in these tests, so every scenario is deterministic. It covers, among others:

- secrets never reach the model, the database, the event log or any response,
- a hallucinated element number is rejected and the agent recovers,
- injected page instructions are removed and cannot lead the agent off the site,
- the agent cannot be pointed at its own control service,
- closing the browser window mid-task, quitting during start-up, rapid task floods, and unusual task text (Hindi, emoji, markup, SQL-like text),
- access control: token required, foreign host headers refused, other websites get no cross-origin permission.

Both applications' fast suites also run on Windows, macOS and Linux in GitHub Actions on every push.

The **live** suite runs the real local model on the same sites and judges success by code on the final page state, never by the agent's own claim.

## Project status and roadmap

Work is split into milestones, each verified before the next starts.

| # | Milestone | Status |
|---|---|---|
| 1 | **Backend core:** local model, browser layer, agent loop, policy firewall, storage, local service, tests | **Done** |
| 2 | **Desktop app:** work view with live page view, approvals and secure entry, history and replay, setup check | **Done** |
| 3 | **Reliability hardening (next):** iframes, popups and banners, multi-tab, recovery, a wider site test matrix, speed tuning | Planned |
| 4 | **Evaluation harness:** replayable benchmark with code-checked success, standard benchmarks, baseline numbers | Planned |
| 5 | **Data and fine-tuning:** training data, QLoRA fine-tuning, verified self-improvement, ablations | Planned |
| 6 | **MCP and safety suite:** MCP server, injection attack suite and measured results | Planned |
| 7 | **RAG memory:** personal documents with sources, skill memory from verified runs | Planned |
| 8 | **Integration:** merge both applications, end-to-end testing across many user behaviours | Planned |
| 9 | **Packaging and release:** Windows and macOS installers, documentation, final merge | Planned |

## Branch workflow

| Branch | Contents |
|---|---|
| `Frontend` | Desktop app only |
| `Backend` | Agent service, AI layer and tests only |
| `testing` | Both merged, for integration testing |
| `main` | Final, tested release |

## Research background

The design draws on published work on web agents and their evaluation: Mind2Web, WebArena, WebVoyager, Online-Mind2Web ("An Illusion of Progress?"), REAL, Agent-E, UGround, GUI-Actor and WebCanvas; on parameter-efficient fine-tuning (LoRA, QLoRA) and self-training on verified outputs (STaR, ReST-EM); on retrieval-augmented generation; and on prompt-injection research (indirect injection, InjecAgent, AgentDojo, WASP) and the Model Context Protocol security literature.

## Measured results (Milestone 1)

Fast suite: **80 tests pass** against a real Chromium (the model is scripted so every scenario is repeatable).

Real local model (Qwen3-VL 2B) on six everyday flows, success judged by code on the final page state:

| Flow | Result |
|---|---|
| Find a price on a search page and report it | Success |
| Read a plain page and answer a question | Success |
| Log in (user types the password, model never sees it) | Success |
| Checkout when the user declines | Stopped safely, nothing paid |
| Multi-field contact form | Partly: skipped some fields and finished early |
| Add to cart on a page that contains an injection attempt | Not finished: the agent was never steered off the site, but did not recognise it was done |

Typical speed: about 3 to 7 seconds per step after the model is loaded. These are the first honest numbers; improving them is the job of the reliability, evaluation and fine-tuning milestones.

Desktop app: **24 tests pass** (event logic, timeline, service client, approval and secret prompts, task composer), the real Electron app passes a start-to-finish smoke test (service starts on a random port, interface loads, bridge works, no Node access leaks into the page), and real tasks were driven through the interface with the real local model: a search-and-read task completed, a payment task stopped for approval, and a login task stopped for approval when the model tried to submit before a password was entered.

## Limitations

Stated plainly, as of Milestone 2:

- A 2-billion-parameter model is small. It follows simple multi-step flows but can pick the wrong action, so the runtime corrects it with validation and feedback. Reliability work, benchmarks and fine-tuning are the next milestones.
- Content inside iframes is not read yet.
- File uploads and downloads are blocked, not handled.
- CAPTCHAs are never solved: the agent stops and hands control back to the user.
- One task runs at a time.
- The desktop app runs from source for now. Installers for Windows and macOS come in the last milestone.

## License

To be added before the final release.
