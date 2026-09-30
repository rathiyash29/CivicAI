# CivicAI — Government Officer Dashboard

Officer-facing React + TypeScript + Vite app. It reuses the existing CivicAI
FastAPI authentication and intelligence contracts; no new backend endpoints are
introduced.

## Run it

```bash
# terminal 1 — backend (from the repo root)
python -m uvicorn backend.main:app --reload

# terminal 2 — this app
cd frontend/government
npm install
npm run dev
```

Open http://localhost:5174 (the citizen app keeps 5173).

Sign in with an account whose `role` is `officer`. A citizen account is
rejected with an access-denied screen.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Dev server on port 5174 |
| `npm run build` | Type-check (`tsc -b`) and production build |
| `npm run preview` | Serve the production build |
| `npm run lint` | oxlint |

## Backend wiring

Requests go to `<base>/api/...`, and the dev server proxies `/api` to
`http://127.0.0.1:8000` with the prefix stripped (see `vite.config.ts`). That
keeps the app same-origin, so the FastAPI CORS allow-list does not need to be
widened for a second frontend port.

Override the target or the public base URL via environment variables (see
`.env.example`); nothing secret belongs in either file:

| Variable | Used by | Default |
|---|---|---|
| `VITE_API_BASE_URL` | the browser build | empty (same origin) |
| `VITE_BACKEND_URL` | the Vite dev proxy | `http://127.0.0.1:8000` |

## Endpoints consumed

| Endpoint | Use |
|---|---|
| `POST /auth/login` | Officer sign-in → `access_token` |
| `GET /auth/me` | Confirms identity and `role` after sign-in and on refresh |
| `GET /intelligence/stats` | Overview page pipeline totals |

The JWT is stored in `localStorage` under `auth_token`, the same key the citizen
frontend uses. `/intelligence/*` is already gated by `require_officer` on the
backend.

## Current scope

Foundation only: login, officer-only protected routing, the dashboard shell
(sidebar, header, officer identity, logout), and an Overview page wired to
`/intelligence/stats` with loading, empty, and API-error states.

Complaints, Hotspots, Recommendations, Projects, and Impact are routed
placeholders — navigation and access control are real, the content is not built
yet.
