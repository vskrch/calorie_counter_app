# Calorie Counter (FastAPI + Next.js)

Code-first calorie counter with AI meal analysis.

## Features
- Name-only onboarding, no signup or password.
- One-time secret access code generation and code-based login.
- User mode: upload food photo from phone camera and estimate dish, calories, protein, fiber, nutrients, and chemicals.
- Manual mode: use Perplexity web UI, then paste JSON output to parse/store.
- Optional free-model path via OpenRouter vision models.
- Meal history + 7-day summary from SQLite.
- Admin interface for user stats, code reset, and user deletion.
- Security hardening: rate limiting + response security headers.
- No food image storage. No request logs persisted in DB.

## Stack
- Backend: FastAPI + SQLite
- Frontend: Next.js (App Router, static export)
- Deployment: Docker container (`heroku.yml` compatible)

## Project Structure
- `backend/app/main.py`: API routes + static serving
- `backend/app/services.py`: auth, DB logic, AI integration
- `backend/app/db.py`: SQLite schema + connection
- `frontend/app/page.tsx`: full UI (auth, user, admin)

## Local Run
### 1) Backend
```bash
cd /Users/venkatasai/Desktop/codex
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# Edit backend/.env with your ADMIN_CODE and API keys
export $(grep -v '^#' backend/.env | xargs)
uvicorn backend.app.main:app --reload --port 8000
```

### 2) Frontend (dev mode)
```bash
cd /Users/venkatasai/Desktop/codex/frontend
npm install
cp .env.example .env.local
# set NEXT_PUBLIC_API_BASE=http://localhost:8000
npm run dev
```

## Docker Run
```bash
cd /Users/venkatasai/Desktop/codex
docker build -t calorie-counter .
docker run --rm -p 8000:8000 \
  -e ADMIN_CODE=admin-secret \
  -e CODE_PEPPER=pepper-123 \
  -e PERPLEXITY_API_KEY=your_key \
  -v calorie-data:/data \
  calorie-counter
```

Open [http://localhost:8000](http://localhost:8000).

## Docker Compose (Recommended Local Run)
```bash
cd /Users/venkatasai/Desktop/codex
cp backend/.env.example backend/.env
# set ADMIN_CODE, CODE_PEPPER and API keys in backend/.env
docker compose up --build
```

This uses a named volume (`calorie_data`) so SQLite data persists across restarts.

## Bootstrap Script
Generate admin secrets and optionally pre-create users:

```bash
cd /Users/venkatasai/Desktop/codex
python -m backend.scripts.bootstrap \
  --env-file backend/.env \
  --user "Alice" \
  --user "Bob" \
  --with-sample-meal
```

- Prints generated `ADMIN_CODE` and `CODE_PEPPER`.
- Writes/updates those values in `backend/.env` when `--env-file` is provided.
- Prints one-time user access codes for each created user.

## Heroku Container Deploy
### 1) Set app stack to container
```bash
heroku create <your-app-name>
heroku stack:set container -a <your-app-name>
```

### 2) Set env vars
```bash
heroku config:set ADMIN_CODE=admin-secret -a <your-app-name>
heroku config:set CODE_PEPPER=pepper-123 -a <your-app-name>
heroku config:set PERPLEXITY_API_KEY=<your-perplexity-key> -a <your-app-name>
```

Optional OpenRouter free model:
```bash
heroku config:set OPENROUTER_API_KEY=<key> -a <your-app-name>
```

### 3) Deploy
```bash
git add .
git commit -m "Build end-to-end calorie counter"
git push heroku main
```

## Notes
- SQLite in Heroku container is ephemeral unless you add persistent storage; restarts can reset DB state.
- Access codes are stored as hashes in SQLite, not plaintext.
- Admin reset reveals a new code once; share it with the user immediately.
- API endpoints include in-memory IP rate limiting and security headers by default.
