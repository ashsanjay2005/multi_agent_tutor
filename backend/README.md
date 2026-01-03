# AI Math Tutor - Backend Service

LangGraph-powered backend for the AI Math Tutor Chrome Extension. This service provides intelligent math problem analysis, step-by-step teaching, and human-in-the-loop workflows.

## Architecture

See [ARCHITECTURE.md](../ARCHITECTURE.md) for the complete system design.

### Key Features
- **Multi-modal Input**: Accepts both text and image (screenshot) inputs
- **Intelligent Classification**: Routes to specialized text or vision classifiers
- **Confidence-Based Routing**: 
  - Low confidence → Request clarification
  - Medium confidence → Disambiguation (user selects topic)
  - High confidence → Generate full teaching response
- **Parallel Execution**: Three teaching agents run concurrently:
  - Worked Example Agent
  - Practice Problem Agent
  - Video Resource Agent
- **State Persistence**: PostgreSQL-backed state management for stateless scaling

## Tech Stack

- **Python 3.11+**
- **FastAPI** - REST API framework
- **LangGraph** - Agentic workflow orchestration
- **LangChain** - LLM integration layer
- **PostgreSQL** - State persistence via `langgraph-checkpoint-postgres`
- **Docker & Docker Compose** - Containerization

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.11+ (for local development)
- Poetry (for dependency management)

### 1. Environment Setup

Create a `.env` file in the project root:

```bash
cp ../.env.example ../.env
```

Edit `.env` and add your API keys:
```env
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
```

### 2. Run with Docker Compose

From the project root:

```bash
docker-compose up --build
```

This starts:
- PostgreSQL database on port 5432
- Backend API on port 8000

### 3. Verify the Service

```bash
curl http://localhost:8000/health
```

Visit the interactive docs:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## API Endpoints

### `POST /v1/analyze`
Analyze a math problem from text or image.

**Request:**
```json
{
  "type": "text",
  "content": "Solve: 2x + 5 = 13",
  "user_id": "user_123",
  "thread_id": "thread_abc"
}
```

**Response (High Confidence):**
```json
{
  "thread_id": "thread_abc",
  "status": "completed",
  "requires_user_action": false,
  "final_response_html": "<html>...</html>",
  "topic": "Algebra - Linear Equations",
  "confidence_score": 0.95
}
```

**Response (Disambiguation Needed):**
```json
{
  "thread_id": "thread_abc",
  "status": "requires_disambiguation",
  "requires_user_action": true,
  "candidate_topics": [
    "Calculus - Derivatives",
    "Calculus - Integrals",
    "Differential Equations"
  ],
  "confidence_score": 0.55
}
```

### `POST /v1/resume`
Resume a paused workflow after user topic selection.

**Request:**
```json
{
  "thread_id": "thread_abc",
  "selected_topic": "Calculus - Derivatives"
}
```

**Response:**
```json
{
  "thread_id": "thread_abc",
  "status": "completed",
  "requires_user_action": false,
  "final_response_html": "<html>...</html>",
  "topic": "Calculus - Derivatives",
  "confidence_score": 1.0
}
```

### `POST /v1/explain_step`
Get detailed explanation for a specific step (micro-service).

**Request:**
```json
{
  "step_text": "Multiply both sides by 2",
  "context": "Solving 2x + 5 = 13",
  "topic": "Algebra"
}
```

## Local Development

### Install Dependencies

```bash
cd backend
poetry install
```

### Run Locally (without Docker)

1. Start PostgreSQL:
```bash
docker run -d \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=math_tutor \
  -p 5432:5432 \
  postgres:15-alpine
```

2. Activate virtual environment:
```bash
poetry shell
```

3. Run the server:
```bash
python main.py
```

Or with uvicorn directly:
```bash
uvicorn main:app --reload --port 8000
```

## Project Structure

```
backend/
├── main.py              # FastAPI application & endpoints
├── graph.py             # LangGraph workflow definition
├── state.py             # GraphState TypedDict
├── config.py            # Configuration management
├── pyproject.toml       # Poetry dependencies
├── Dockerfile           # Container definition
└── README.md            # This file
```

## Testing

### Manual Testing with curl

**Text Analysis:**
```bash
curl -X POST http://localhost:8000/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "type": "text",
    "content": "Find the derivative of f(x) = x^2 + 3x + 2",
    "user_id": "test_user"
  }'
```

**Image Analysis (Base64):**
```bash
curl -X POST http://localhost:8000/v1/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "type": "image",
    "content": "iVBORw0KGgoAAAANSUhEUg...",
    "user_id": "test_user"
  }'
```

**Resume Workflow:**
```bash
curl -X POST http://localhost:8000/v1/resume \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "THREAD_ID_FROM_ANALYZE",
    "selected_topic": "Calculus - Derivatives"
  }'
```

### Unit Tests (TODO)

```bash
poetry run pytest
```

## Current State: Mock Implementation

⚠️ **Important:** The current implementation uses **mock LLM responses** for rapid testing of the workflow logic.

To enable real LLM calls, update these node functions in `graph.py`:
- `text_classifier_node` - Add LangChain ChatOpenAI call
- `vision_classifier_node` - Add GPT-4o vision call
- `teaching_architect_node` - Add teaching plan generation
- `worked_example_node` - Add step-by-step solution generation
- `practice_node` - Add practice problem generation
- `video_node` - Add YouTube Data API integration

Example LLM integration:
```python
from langchain_openai import ChatOpenAI

async def text_classifier_node(state: GraphState) -> GraphState:
    llm = ChatOpenAI(model="gpt-4o-mini")
    prompt = f"Classify this math problem: {state['input_content']}"
    response = await llm.ainvoke(prompt)
    # Parse response and extract topic, confidence
    return {...}
```

## Configuration

Edit `config.py` or set environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |
| `OPENAI_API_KEY` | - | OpenAI API key |
| `GOOGLE_API_KEY` | - | Google AI API key |
| `CONFIDENCE_THRESHOLD_LOW` | 0.4 | Below this = clarification |
| `CONFIDENCE_THRESHOLD_HIGH` | 0.75 | Above this = full teaching |
| `VISION_MODEL` | `gpt-4o` | Vision model name |
| `TEXT_MODEL` | `gpt-4o-mini` | Text model name |

## Deployment

### Google Cloud Run

1. Build and push image:
```bash
gcloud builds submit --tag gcr.io/PROJECT_ID/math-tutor-backend
```

2. Deploy:
```bash
gcloud run deploy math-tutor-backend \
  --image gcr.io/PROJECT_ID/math-tutor-backend \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars DATABASE_URL=...,OPENAI_API_KEY=...
```

### Environment Variables in Cloud Run

Set these via the Cloud Run console or CLI:
- `DATABASE_URL` (use Cloud SQL connection)
- `OPENAI_API_KEY`
- `GOOGLE_API_KEY`

## Troubleshooting

### Database Connection Issues

Check PostgreSQL is running:
```bash
docker ps | grep postgres
```

Test connection:
```bash
psql $DATABASE_URL -c "SELECT 1"
```

### Graph Not Initializing

Check logs:
```bash
docker-compose logs backend
```

Ensure checkpoint tables exist:
```bash
psql $DATABASE_URL -c "\dt"
```

## License

[Your License Here]


