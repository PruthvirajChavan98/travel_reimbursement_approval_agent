.PHONY: install dev-api dev-web test build up down

install:
	cd backend && uv sync
	cd frontend && npm install

dev-api:
	cd backend && uv run uvicorn app.api:app --reload --port 8000

dev-web:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest

build:
	cd frontend && npm run build

up:
	docker compose up -d

down:
	docker compose down
