# AI STEM Tutor — Backend

LangGraph-powered backend for the AI STEM Tutor Chrome Extension.

## Quick Start

```bash
# From project root
cp .env.example .env   # Edit with your API keys
docker compose up -d
curl http://localhost:8000/health
```

API docs: http://localhost:8000/docs

## Project Structure

```
backend/
├── main.py                  # FastAPI app + all API endpoints
├── graph.py                 # LangGraph workflow (classify → route → solve)
├── state.py                 # GraphState TypedDict
├── config.py                # Pydantic settings (env vars)
├── supabase_client.py       # Supabase database helpers
├── backboard_client.py      # Backboard.io memory integration
├── cache.py                 # Video cache (Supabase-backed)
├── rate_limiter.py          # Redis rate limiting
├── youtube_resources_graph.py # YouTube video search sub-graph
├── Dockerfile               # Container definition
└── requirements.txt         # Python dependencies
```

## Key Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/analyze` | Classify + solve a STEM problem |
| `POST` | `/v1/resume` | Resume after topic disambiguation |
| `POST` | `/v1/expand_step` | Break a step into sub-steps |
| `POST` | `/v1/practice` | Generate practice questions |
| `POST` | `/v1/resources` | Search YouTube videos |
| `GET` | `/v1/quota` | Rate limit status |
| `GET` | `/v1/sessions` | List user sessions |

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the full system design, all endpoints, and database schema.

## Configuration

All config is via environment variables (see `.env.example`). Key settings:

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | Supabase PostgreSQL connection string |
| `SUPABASE_URL` | ✅ | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | ✅ | Supabase service role key |
| `GOOGLE_API_KEY` | ✅ | Google AI Studio API key |
| `YOUTUBE_API_KEY` | Optional | YouTube Data API v3 key |
| `BACKBOARD_API_KEY` | Optional | Backboard.io key for long-term memory |
| `REDIS_URL` | Optional | Defaults to bundled Redis container |
