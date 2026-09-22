# TVBFundRadar

Autonomous Company Intelligence & Lead Discovery.

> TVBFundRadar is an adaptive web intelligence and qualification platform. It
> autonomously discovers web sources from search queries, researches and
> extracts company candidates with source-backed evidence, qualifies each
> company against explicit criteria, assembles evidence-backed contacts and
> leads, and reports exactly why each company qualified — or did not — without
> using a single API key.

## Overview

TVBFundRadar is a real-time, evidence-driven B2B lead discovery and qualification
platform. It extracts raw web data, evaluates companies against strict,
deterministic criteria (funding/revenue range, tech platform, US presence), and
produces transparent, source-backed qualification decisions, contact
enrichment, and a readable workspace — all from organic web sources, with every
decision traceable to persisted evidence. No fabricated values, no guessed
emails, no paid data providers.

## Features

- **Zero-API-key web discovery** — searches DuckDuckGo organically
- **Deep web research** — fetch validation, HTML parsing, metadata, links, and
  public-email extraction
- **Deterministic candidate extraction** — companies paired with source-backed
  evidence
- **Evidence-backed qualification** — companies evaluated against three fixed
  criteria; every decision saved with its proof
- **Transparent funnel** — company-qualified, near-qualified, and other analyzed
  companies stay visible with reasons
- **Contact enrichment without guessing** — public names and emails recorded
  with their evidence state; blanks stay blank
- **Full pipeline orchestration** — one call runs discovery → research →
  extraction → qualification → contacts → leads
- **Personal workspaces** — email/password accounts, server-side bearer-token
  sessions, and per-user run isolation (Phase 14)
- **Live run monitoring** — a React workspace with create, execute, monitor, and
  results views
- **Durable database** — SQLite for local development, PostgreSQL in production
  (works on ephemeral Render disks via an external database)

## Tech Stack

| Layer        | Choice                                                      |
| ------------ | ----------------------------------------------------------- |
| Frontend     | React 19, TypeScript, Vite 8, react-router-dom 7            |
| Backend      | Python 3.11+, FastAPI, Pydantic                             |
| HTTP / parsing | HTTPX (async) + BeautifulSoup4 / `html.parser` |
| Discovery    | `ddgs` (DuckDuckGo search — no API keys)                    |
| Database     | SQLite (dev) + PostgreSQL 16 (prod) via SQLAlchemy 2.x + psycopg |
| Auth         | bcrypt passwords + server-side bearer-token sessions              |
| Testing      | pytest (537 tests), `npm run typecheck`, `npm run build`          |

## Folder Structure

```
TVBFundRadar/
│
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app + endpoints + lifespan init_db
│   │   ├── core/                    # config, enums, constants
│   │   ├── db/                      # session, base, mappers, orm/ tables
│   │   ├── models/                  # Pydantic contracts (run, source, evidence, …)
│   │   ├── auth/                    # security.py (bcrypt) + service.py (sessions)
│   │   ├── discovery/               # provider interface + DuckDuckGo provider
│   │   ├── research/                # fetcher, parser, extractors, service
│   │   ├── extraction/              # candidate extraction + deterministic extractors
│   │   ├── qualification/           # 3-criteria evaluators + overall policy
│   │   ├── contact/                 # contact assembly + enrichment
│   │   ├── lead/                    # lead assembly (QUALIFIED + PASS only)
│   │   ├── results/                 # funnel + readiness + candidate analysis
│   │   ├── orchestration/           # PipelineOrchestrator
│   │   └── repositories/            # SQLAlchemy repositories
│   ├── requirements.txt
│   └── tests/                       # pytest suite (537 tests, offline-safe)
│
├── frontend/
│   ├── index.html                   # theme bootstrap + app mount
│   ├── vite.config.ts               # dev server + /api proxy to :8000
│   ├── package.json
│   ├── .env.example
│   └── src/
│       ├── main.tsx                 # ThemeProvider → BrowserRouter → AuthProvider
│       ├── App.tsx                  # routes + ProtectedRoute + AppShell
│       ├── api/                     # typed client (credentials: include)
│       ├── context/                 # AuthContext
│       ├── hooks/                   # useRuns · useRun · useRunResults
│       ├── pages/                   # Landing · Login · Register · Runs · NewRun · Results
│       ├── components/              # runs · layout · ui
│       └── theme/                   # design tokens + dark/light themes
│
├── docs/
│   └── architecture.md              # full phase-by-phase engineering guide
│
├── pytest.ini
├── TEST_QUERIES.txt
└── README.md
```

## Installation Guide

### 1. Clone the Repository

```bash
git clone <your-tvbfundradar-repo-url>
cd TVBFundRadar
```

### 2. Set Up the Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Start the Development Server

```bash
uvicorn app.main:app --reload    # http://127.0.0.1:8000
```

### 4. Run the Frontend

```bash
cd frontend
npm install
npm run dev                      # http://127.0.0.1:5173
```

The Vite dev server proxies `/api` and `/health` to `http://127.0.0.1:8000`, so
the browser only ever talks to same-origin URLs in development.

## Environment Variables

Create a `.env` file in the backend directory (or set them in your shell) as
needed:

| Variable                    | Default                              | Purpose                              |
| --------------------------- | ------------------------------------ | ------------------------------------ |
| `DATABASE_URL`              | `sqlite:///./tvbfundradar.db`             | SQLAlchemy URL. Production (Render): your external PostgreSQL URL (`postgresql://…`), automatically normalized onto the bundled psycopg driver |
| `CORS_ORIGINS`              | `http://localhost:5173,http://127.0.0.1:5173` | Allowed cross-origin frontends (comma-separated). Vercel: `https://tvbfundradar.vercel.app` |
| `RESEARCH_TIMEOUT_SECONDS`  | `8.0`                                | Per-page research timeout            |
| `RESEARCH_MAX_RESPONSE_BYTES` | `2000000`                          | Max response bytes to parse          |
| `VITE_API_BASE_URL`         | *(empty)*                            | Frontend build-time backend origin. Vercel: `https://tvbfundradar.onrender.com` |

## Deployment

**No build step is required for the backend** — it is a standard FastAPI app:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Deploy Using

- **Render (Backend)** — create a Web Service from the repo root, run
  `cd backend && pip install -r requirements.txt && uvicorn app.main:app --host 0.0.0.0 --port 8000`,
  and set the environment variables above. **Required for a durable production
  database:**
  - `DATABASE_URL` — your external PostgreSQL URL. Render's default `sqlite:///…`
    lives on an ephemeral filesystem and is erased on every restart/redeploy, so
    accounts and runs would be lost. Use Render Postgres (or any PG) and paste
    its "External" connection string.
  - `CORS_ORIGINS=https://<your-frontend>.vercel.app` — e.g.
    `https://tvbfundradar.vercel.app`.
- **Vercel (Frontend SPA)** — set the build command to `npm run build` (from
  `frontend/`), the output directory to `dist`, and configure `VITE_API_BASE_URL`
  to your backend origin (`https://tvbfundradar.onrender.com`). Auth travels as
  an `Authorization: Bearer <token>` header (no cookies, so no cross-site cookie
  configuration is needed); the backend just has to allow your frontend origin
  via `CORS_ORIGINS`.

## Testing

```bash
# Backend (from the repo root, using the project venv)
.venv/Scripts/python -m pytest -q      # 537 passed, 0 failed — fully offline

# Frontend
cd frontend
npm run typecheck
npm run build
```

The backend suite never touches your developer database — every persistence
test uses an isolated SQLite file, and a session guard asserts the local DB is
untouched.

## API Documentation

### Create an account

```bash
POST /api/auth/register
```

```bash
{
  "email": "you@example.com",
  "password": "your-password",
  "display_name": "You"
}
```

Response:

```json
{
  "token": "a5c32f20-42f1-4d7d-9f74-2a5e0d17b6f1",
  "user": {
    "user_id": "c7fc7d09-4140-439e-9a61-b66762424af4",
    "email": "you@example.com",
    "display_name": "You",
    "created_at": "2026-09-13T18:52:17.193712"
  }
}
```

The `token` appears exactly once. Send it as `Authorization: Bearer <token>`
on every later request (the frontend stores it in `sessionStorage` and the API
client attaches it automatically).

### Create a run

```bash
POST /api/runs
Authorization: Bearer <token>
```

```json
{ "target_lead_count": 5 }
```

Response:

```json
{
  "run_id": "f1356774-ddb7-4c6d-ba79-e75eec7c4cc1",
  "status": "pending",
  "target_lead_count": 5,
  "qualified_lead_count": 0
}
```

### Run the full pipeline

```bash
POST /api/runs/{run_id}/execute
```

```json
{
  "queries": ["Berlin B2B software platform funding"],
  "max_results_per_query": 5
}
```

See [docs/architecture.md](docs/architecture.md) for the complete API surface
(discovery, research, extraction, qualification, contacts, leads, completion,
results, and diagnostics).

## Contributing

Contributions are welcome. Follow the existing phase-driven conventions and keep
the "never fabricate" contract: the system records evidence, it never invents
values.

**Steps to Contribute**

1. Fork the repository
2. Create a new branch

   ```bash
   git checkout -b feature-name
   ```

3. Commit your changes

   ```bash
   git commit -m "Added new feature"
   ```

4. Push to GitHub

   ```bash
   git push origin feature-name
   ```

5. Create a Pull Request

## Security

- **bcrypt password hashing** — cost 12; hashes never appear in API responses
- **Server-side bearer-token sessions** — register/login return a random session
  token once; the browser keeps it in `sessionStorage` and sends it as an
  `Authorization: Bearer` header. No cookie is set, so cross-site (Vercel →
  Render) auth needs no SameSite/Secure cookie configuration
- **Logout revocation** — signing out deletes the session row server-side
- **Per-user ownership** — every run is bound to its owner; foreign or legacy
  unowned runs all return a uniform 404
- **CORS allowlist** — requests only from explicitly configured frontend
  origins; `Authorization` is always allowed by preflight
- **Stateless-ish API** — all state lives in the configured database (SQLite
  locally, PostgreSQL in production); endpoints stay simple and testable

## License

This project is licensed under the MIT License.

## Author

Gudise Sathvika

- GitHub: https://github.com/sathvikagudise
- LinkedIn: https://linkedin.com/in/sathvikayadav
- Email: sathvikayadav3@gmail.com

## Support

If you like this project, give it a star on GitHub.