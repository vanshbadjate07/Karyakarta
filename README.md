# Karyakarta Desktop App

The desktop app for Karyakarta: describe a task, watch an agent work in a real browser, and approve anything risky. It is an Electron shell around a React interface, and it talks to the local Karyakarta service in the Backend branch.

The full project description, safety model and roadmap are in the repository's main README.

## What it does

- **Home:** describe a task in plain words, optionally pick a starting website.
- **Work view:** a timeline of every step (action, reasoning, "Verified" tag, AI time) next to a live view of the page the agent is looking at. Finished tasks can be replayed step by step.
- **Approvals where they are needed:** the agent stops and asks before anything that cannot be undone, and shows exactly what it wants to do and why.
- **Secure entry:** passwords, codes and card numbers are typed into a masked box and go straight to the website. They are not stored, and the AI never sees them.
- **History:** every task is kept, grouped by day, and can be reopened, replayed, re-run or deleted.
- **Setup check:** shows whether the local AI engine, the model and the browser component are ready, and downloads the model with progress.
- Light interface only.

## Run it

Start the Backend first (see its README), or let the app start it:

```bash
npm install
npm run build
npm start            # opens the desktop app and starts the service for you
```

By default the app starts the service from `../Backend` (a sibling folder). Settings, all optional:

| Variable | Meaning |
|---|---|
| `KARYAKARTA_BACKEND_DIR` | Folder of the Backend project |
| `KARYAKARTA_PYTHON` | Python to run the service with |
| `KARYAKARTA_URL` and `KARYAKARTA_API_TOKEN` | Use a service that is already running instead of starting one |
| `KARYAKARTA_DEV_URL` | Load the interface from a dev server, for example `http://127.0.0.1:5173` |

### Developing the interface in a browser

```bash
# terminal 1, in Backend
KARYAKARTA_API_TOKEN=dev-token uv run python -m karyakarta
# terminal 2, in Frontend
npm run web          # then open http://127.0.0.1:5173/?token=dev-token&port=8765
```

The token in the address only works in development builds.

## Test

```bash
npm test             # unit and component tests
npm run typecheck
npm run smoke        # launches the real app: service starts, interface loads, bridge works
```

## Layout

```
electron/   desktop shell: starts and stops the service, secure bridge to the page
src/lib/    service client, live stream, timeline, hooks
src/components/   home, work view, live view, prompts, setup, sidebar
tests/      logic, client and component tests
```

## Security

The page has no access to Node. It can only ask the desktop app for the service address and token, and to open the engine download page. Navigation away from the app and new windows are blocked, camera and other permissions are refused, and the access token is kept in memory.
