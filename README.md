# AI STEM Tutor

A Chrome extension that identifies STEM problems from text or screenshots and teaches you how to solve them step-by-step, with persistent memory across sessions.

## What It Does

Students encounter STEM problems online but don't know which specific concept to study. Generic searches like "help with this math" don't work — you need to know it's "Cross Product" or "Gaussian Elimination" to find good tutorials.

The extension classifies your problem, generates a full step-by-step solution, and remembers your learning history to personalize future explanations.

---

## Features

### Core Tutoring
- **Granular topic detection** — Identifies specific operations (Cross Product, Eigenvalues, Stoichiometry) not just broad subjects
- **Step-by-step solutions** — Numbered steps with clickable breakdowns (expandable up to 3 levels deep)
- **LaTeX math rendering** — Properly formatted equations using KaTeX
- **Screenshot / image support** — Paste text or upload a screenshot; images are extracted and analyzed by Gemini Vision
- **Confidence routing** — High confidence → instant solution; low confidence → asks for clarification or disambiguation

### Learning & Memory
- **Persistent memory** — Powered by [Backboard.io](https://backboard.io) LoCoMo; remembers past problems across sessions
- **Adaptive explanations** — Adjusts detail level based on your strengths and weaknesses per topic
- **Practice problem generator** — Generates 3 related practice questions after each solution
- **Parallel Execution**: Three teaching agents run concurrently:
  - Worked Example Agent
  - Practice Problem Agent
  - Video Resource Agent
- **State Persistence**: PostgreSQL-backed state management for stateless scaling
- **YouTube video search** — Finds relevant tutorial videos for the detected topic (AI-ranked, paginated)

### History & Organization
- **Session history** — All solved problems saved locally and synced to Supabase
- **Smart folder grouping** — Semantic folder suggestions using Backboard memory
- **Batch operations** — Multi-select sessions to move, mark reviewed, or delete

### Infrastructure
- **Supabase Auth** — Google OAuth sign-in; anonymous fallback for unauthenticated users
- **Rate limiting** — Per-user request limits (free: 5/min, pro: 50/min) backed by Redis
- **Image offloading** — Screenshots uploaded to Supabase Storage (not stored in DB) to keep checkpoint data lean
- **Dual LangGraph** — Lightweight graph for standard requests; checkpointed graph only for disambiguation resumption

---

## Tech Stack

**Backend:**
- Python 3.11 + FastAPI
- LangGraph (workflow orchestration, dual graph: lightweight + checkpointed)
- Google Gemini 2.0 Flash (vision + text)
- Supabase (PostgreSQL + Auth + Storage)
- Redis (rate limiting)
- Backboard.io SDK (long-term LoCoMo memory)
- Docker Compose

**Extension:**
- React 18 + TypeScript + Vite
- Chrome Manifest V3 (side panel)
- KaTeX (math rendering)
- Tailwind CSS + Lucide icons
- `@supabase/supabase-js` (auth + data sync)

---

## Repo Structure

```
backend/
  main.py                   # FastAPI app + all endpoints
  graph.py                  # LangGraph workflow (classify → route → teach)
  youtube_resources_graph.py # YouTube search sub-graph
  backboard_client.py       # Backboard.io memory integration
  supabase_client.py        # Supabase helpers (sessions, problems, storage)
  cache.py                  # PostgreSQL video cache
  rate_limiter.py           # Redis-backed rate limiting
  config.py                 # Pydantic settings (env vars)
  state.py                  # LangGraph state schema
  Dockerfile
  requirements.txt

extension/
  src/
    App.tsx                 # Main app shell + state machine
    components/             # SolutionView, PracticeView, HistoryView, YouTubeVideosView, ...
    lib/
      api.ts                # Backend API calls
      auth.ts               # Supabase auth helpers
      storage.ts            # Local + Supabase session storage
      types.ts              # Shared TypeScript types

supabase_migration.sql      # Full DB schema (run once in Supabase SQL Editor)
docker-compose.yml          # Services: backend + Redis
Makefile                    # Dev shortcuts
```

---

## Setup

### Prerequisites
- Docker + Docker Compose
- Node.js 18+
- A [Supabase](https://supabase.com) project (free tier works)
- A [Google AI Studio](https://aistudio.google.com) API key (Gemini)
- Optional: [YouTube Data API v3](https://console.cloud.google.com) key, [Backboard.io](https://backboard.io) API key

### 1. Supabase Setup

1. Create a new Supabase project
2. In **SQL Editor**, run `supabase_migration.sql` to create all tables
3. In **Authentication → Providers**, enable Google OAuth
4. In **Storage**, the `problem-images` bucket is created automatically on first backend start

### 2. Backend

```bash
# Copy env template and fill in your keys
cp .env.example .env
```

Required `.env` variables:

```env
# Supabase
DATABASE_URL=postgresql://postgres.xxx:password@aws-0-us-east-1.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...   # Service role key (Settings → API)

# AI
GOOGLE_API_KEY=AIza...

# Optional
YOUTUBE_API_KEY=AIza...       # For YouTube video search
BACKBOARD_API_KEY=...         # For persistent long-term memory
REDIS_URL=redis://redis:6379  # Defaults to bundled Redis container

# Confidence routing (optional)
CONFIDENCE_THRESHOLD_LOW=0.4
CONFIDENCE_THRESHOLD_HIGH=0.75
```

```bash
# Start backend + Redis
docker compose up -d --build

# Verify
curl http://localhost:8000/health
```

### 3. Extension

```bash
cd extension
npm install
npm run build

# Load in Chrome:
# chrome://extensions → Enable Developer Mode → Load unpacked → select extension/dist/
```

Point the extension at your backend by setting `VITE_API_URL` in `extension/.env`:

```env
VITE_API_URL=http://localhost:8000
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/v1/quota` | Rate limit status for a user |
| `POST` | `/v1/analyze` | Classify + solve a problem (text or image) |
| `POST` | `/v1/resume` | Resume after disambiguation selection |
| `POST` | `/v1/expand_step` | Break a solution step into sub-steps |
| `POST` | `/v1/explain_step` | Get a plain-English explanation of a step |
| `POST` | `/v1/practice` | Generate practice questions for a topic |
| `POST` | `/v1/resources` | Fetch YouTube videos for a topic |
| `POST` | `/v1/log_breakdown` | Log when a student requests a step breakdown |
| `POST` | `/v1/log_quiz_result` | Log a practice quiz answer |
| `POST` | `/v1/suggest_folder` | Semantic folder suggestion for a problem |
| `POST` | `/v1/sync_folder` | Sync folder definition to Backboard memory |
| `POST` | `/v1/delete_folder` | Remove folder from Backboard memory |
| `POST` | `/v1/delete_problem` | Remove problem from Backboard memory |

Full interactive docs: `http://localhost:8000/docs`

---

## Usage

1. **Click the extension icon** in Chrome toolbar (opens as a side panel)
2. **Sign in** with Google (or continue anonymously)
3. **Paste a problem** or **upload a screenshot**
4. **Wait for classification** — e.g., "Math - Linear Algebra - Matrix Powers and Limits"
5. **View the step-by-step solution** — click any step to expand it further
6. **Generate practice problems** or **find YouTube tutorials** from the solution view
7. **Browse history** in the History tab — organize into folders, batch delete, etc.

---

## License

TBD
