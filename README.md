# AI STEM Tutor

Chrome extension that identifies STEM problems from text or screenshots and teaches you how to solve them step-by-step.

## Problem

Students encounter STEM problems online but don't know which specific concept to study. Generic searches like "help with this math" don't work—you need to know it's "Cross Product" or "Gaussian Elimination" to find good tutorials.

## Features

- **Granular topic detection** — Identifies specific operations (Cross Product, Eigenvalues, Stoichiometry) not just broad subjects
- **Step-by-step solutions** — Shows numbered steps with clickable explanations for each one
- **LaTeX math rendering** — Properly formatted equations using KaTeX
- **Screenshot support** — Paste text or capture your screen
- **Confidence routing** — High confidence → instant solution; low confidence → asks for clarification

## Tech Stack

**Backend:**
- Python 3.11 + FastAPI
- LangGraph for workflow orchestration
- Google Gemini 2.0 Flash (or OpenAI GPT-4)
- PostgreSQL for state persistence
- Docker Compose

**Extension:**
- React + TypeScript + Vite
- Chrome Manifest V3
- KaTeX for math rendering
- Tailwind CSS

## Repo Structure

```
backend/           # FastAPI + LangGraph agent workflow
extension/         # Chrome extension (React)
docker-compose.yml # Services (Postgres, backend API)
Makefile           # Dev commands
```

## How to Run

**1. Backend:**
```bash
# Copy .env template and add your API keys
cp .env.example .env
# Edit .env: add GOOGLE_API_KEY or OPENAI_API_KEY

# Start services
docker-compose up -d --build

# Verify: http://localhost:8000/docs
```

**2. Extension:**
```bash
cd extension
npm install
npm run build

# Load in Chrome:
# chrome://extensions → Enable Developer Mode → Load unpacked → select extension/dist/
```

## Configuration

Add to `.env`:

```env
GOOGLE_API_KEY=your_key_here
# Or use OpenAI:
# OPENAI_API_KEY=sk-...

# Optional:
CONFIDENCE_THRESHOLD_LOW=0.4   # Below this → ask for clarification
CONFIDENCE_THRESHOLD_HIGH=0.75 # Above this → generate solution
```

Backend defaults to Gemini 2.0 Flash. To switch models, edit `backend/config.py`.

## Usage

1. **Click extension icon** in Chrome toolbar
2. **Paste a problem** (e.g., `[9 8 3] x [2 1 4]`) or take a screenshot
3. **Wait for classification** — sees "Math - Linear Algebra - Cross Product"
4. **View solution** — 6 steps with matrix determinant method
5. **Click any step** to expand and see detailed explanation

## Status

**Working:**
- Topic classification for Math, Physics, Chemistry (50+ specific operations)
- Step-by-step solution generation with LaTeX
- Chrome extension with screenshot capture
- Backend API with LangGraph workflow

**Not implemented:**
- Practice problem generator
- YouTube video search
- Conversation history

## License

TBD
