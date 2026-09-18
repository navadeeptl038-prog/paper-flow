# PaperFlow AI — Test Foundation

This folder holds the Stage 6 test foundation. It verifies scaffolding that already exists and reserves placeholders for features that are not implemented yet.

## What is covered now

| Area | Status |
|------|--------|
| Backend health endpoint | Runnable |
| Env example / CORS config validation | Runnable |
| Auth / documents / search / retrieval / RAG / requirements | Explicitly **skipped** until those stages land |
| Live Supabase / Gemini / OAuth | Skipped unless safe local config is present |

## Prerequisites

From `paperflow-ai/`:

```bash
python -m pip install -r backend/requirements.txt
python -m pip install -r requirements-dev.txt
```

Frontend (for build/structure checks):

```bash
cd frontend
npm install
```

Do **not** put production secrets or personal documents into tests.

## Run backend tests

From `paperflow-ai/`:

```bash
python -m pytest
```

Useful variants:

```bash
# Verbose with skip reasons
python -m pytest -rs

# Only foundation suites that should pass without external services
python -m pytest tests/test_health.py tests/test_config.py -rs
```

### Interpreting results

- **PASSED** — assertion ran and succeeded
- **SKIPPED** — feature not implemented yet, or required config is missing (see `-rs` reason)
- **FAILED** — assertion ran and failed; fix before claiming green

Tests that need `SUPABASE_URL` use `pytest.skip` when it is unset. They do not invent credentials.

## Run frontend checks

From `paperflow-ai/frontend/`:

```bash
npm test
```

This runs:

1. `test:structure` — required files and scripts exist; `api.js` exposes `healthCheck` / `apiRequest`
2. `test:build` — production Vite build

### Frontend → backend health (Stage 7)

Requires the API running and `frontend/.env` with `VITE_API_URL` set (local default documented as `http://127.0.0.1:8000`):

```bash
# terminal A
cd backend
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

# terminal B
cd frontend
npm run test:health
```

Expected: `Frontend→backend health OK: ... {"status":"ok"}`

## Security notes

- Never commit `.env` files with real keys
- Never load real passports, IDs, or personal PDFs into fixtures
- Prefer empty `.env.example` values (names only)
