.PHONY: install lint test test-backend test-frontend fmt local synth

CDK := npx --yes aws-cdk@2.1145.0

install:
	uv sync
	cd frontend && npm ci
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy
	cd frontend && npm run lint && npm run typecheck

test: test-backend test-frontend

test-backend:
	uv run pytest

test-frontend:
	cd frontend && npm test

fmt:
	uv run ruff check --fix .
	uv run ruff format .

local:
	docker compose up

synth:
	$(CDK) synth --quiet
