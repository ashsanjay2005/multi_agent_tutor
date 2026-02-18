.PHONY: help build up down logs restart clean backend-shell health

help:
	@echo "AI STEM Tutor — Development Commands"
	@echo ""
	@echo "make build         - Build Docker containers"
	@echo "make up            - Start all services"
	@echo "make down          - Stop all services"
	@echo "make logs          - View logs (all services)"
	@echo "make backend-logs  - View backend logs only"
	@echo "make restart       - Restart all services"
	@echo "make clean         - Remove containers and volumes"
	@echo "make backend-shell - Open shell in backend container"
	@echo "make health        - Check backend health"
	@echo "make setup         - Create .env from template"

build:
	docker compose build

up:
	docker compose up -d
	@echo ""
	@echo "✅ Services started!"
	@echo "Backend API: http://localhost:8000"
	@echo "API Docs:    http://localhost:8000/docs"

down:
	docker compose down

logs:
	docker compose logs -f

backend-logs:
	docker compose logs -f backend

restart:
	docker compose restart

clean:
	docker compose down -v
	@echo "✅ Cleaned up containers and volumes"

backend-shell:
	docker compose exec backend /bin/bash

# Check service health
health:
	@echo "Checking backend health..."
	@curl -s http://localhost:8000/health | python3 -m json.tool

# Example API request
test-text:
	@echo "Testing text analysis..."
	@curl -X POST http://localhost:8000/v1/analyze \
		-H "Content-Type: application/json" \
		-d '{"type": "text", "content": "Solve: 2x + 5 = 13", "user_id": "test"}' \
		| python3 -m json.tool

# Setup environment
setup:
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ .env file created from .env.example"; \
		echo "⚠️  Please edit .env and add your API keys"; \
	else \
		echo "⚠️  .env file already exists"; \
	fi
