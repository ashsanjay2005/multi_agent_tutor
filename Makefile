.PHONY: help build up down logs restart clean test backend-shell db-shell

help:
	@echo "AI Math Tutor - Development Commands"
	@echo ""
	@echo "make build        - Build Docker containers"
	@echo "make up           - Start all services"
	@echo "make down         - Stop all services"
	@echo "make logs         - View logs (all services)"
	@echo "make backend-logs - View backend logs only"
	@echo "make restart      - Restart all services"
	@echo "make clean        - Remove containers and volumes"
	@echo "make backend-shell- Open shell in backend container"
	@echo "make db-shell     - Open PostgreSQL shell"
	@echo "make test         - Run tests (TODO)"
	@echo "make lint         - Run linters (backend)"

build:
	docker-compose build

up:
	docker-compose up -d
	@echo ""
	@echo "✅ Services started!"
	@echo "Backend API: http://localhost:8000"
	@echo "API Docs: http://localhost:8000/docs"
	@echo "PostgreSQL: localhost:5432"

down:
	docker-compose down

logs:
	docker-compose logs -f

backend-logs:
	docker-compose logs -f backend

restart:
	docker-compose restart

clean:
	docker-compose down -v
	@echo "✅ Cleaned up containers and volumes"

backend-shell:
	docker-compose exec backend /bin/bash

db-shell:
	docker-compose exec postgres psql -U postgres -d math_tutor

# Local development (without Docker)
install:
	cd backend && poetry install

run-local:
	cd backend && poetry run python main.py

# Linting and formatting
lint:
	cd backend && poetry run ruff check .
	cd backend && poetry run mypy .

format:
	cd backend && poetry run black .

# Testing
test:
	cd backend && poetry run pytest -v

# Database migrations (for future use)
db-migrate:
	@echo "TODO: Add migration tool (e.g., Alembic)"

# Check service health
health:
	@echo "Checking backend health..."
	@curl -s http://localhost:8000/health | python -m json.tool

# Example API requests
test-text:
	@echo "Testing text analysis..."
	@curl -X POST http://localhost:8000/v1/analyze \
		-H "Content-Type: application/json" \
		-d '{"type": "text", "content": "Solve: 2x + 5 = 13", "user_id": "test"}' \
		| python -m json.tool

# Setup environment
setup:
	@if [ ! -f .env ]; then \
		echo "Creating .env file..."; \
		echo "POSTGRES_USER=postgres" > .env; \
		echo "POSTGRES_PASSWORD=postgres" >> .env; \
		echo "POSTGRES_DB=math_tutor" >> .env; \
		echo "POSTGRES_PORT=5432" >> .env; \
		echo "BACKEND_PORT=8000" >> .env; \
		echo "ENVIRONMENT=development" >> .env; \
		echo "OPENAI_API_KEY=your_openai_api_key_here" >> .env; \
		echo "GOOGLE_API_KEY=your_google_api_key_here" >> .env; \
		echo ""; \
		echo "✅ .env file created!"; \
		echo "⚠️  Please edit .env and add your API keys"; \
	else \
		echo "⚠️  .env file already exists"; \
	fi


