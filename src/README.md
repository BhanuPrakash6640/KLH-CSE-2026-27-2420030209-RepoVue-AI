# RepoVue — AI Codebase Doctor

Two folders, one project.

```
backend/    Python · FastAPI · Postgres/pgvector
frontend/   React · TypeScript · Vite
```

## Quickest start — Docker (runs everything)

```bash
cd backend
cp .env.example .env          # add ANTHROPIC_API_KEY and GITHUB_TOKEN
docker compose up --build
# API  → http://localhost:8000/docs
# Web  → http://localhost:3000
```

## Running them separately

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set DATABASE_URL, ANTHROPIC_API_KEY
python -m app.db.init_db
uvicorn app.main:app --reload
# http://localhost:8000/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev
# http://localhost:5173  (proxies /api → localhost:8000)
```

## Tests

```bash
cd backend  &&  pytest -q          # 56 tests, no DB/key/Docker needed
cd frontend &&  npm test           # 14 tests
```
