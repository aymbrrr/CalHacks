# Redundant Dashboard

React/Vite frontend for the Redundant runtime firewall. Consumes the FastAPI
backend at `../backend` and falls back to a checked-in fixture so the demo
works even when the backend wobbles.

## Setup

```bash
cd frontend
npm install
```

## Develop

Two terminals:

```bash
# terminal 1 — backend
cd backend && uvicorn redundant.api:app --reload --port 8000

# terminal 2 — frontend
cd frontend && npm run dev
```

Open <http://localhost:5173>. The Vite dev server proxies `/api`, `/findings`,
and `/alerts` to `:8000`.

## Static fallback

If the backend is offline, the dashboard still renders from
`public/fixtures/findings.json`. Force it explicitly:

```
http://localhost:5173/?source=static
```

## Build

```bash
npm run build       # emits dist/
npm run preview     # serves the production build
```

To ship as a single process, point FastAPI at `dist/` via
`StaticFiles(html=True)` — see `BACKEND_INTEGRATION_PLAN.md` §"Setup".
