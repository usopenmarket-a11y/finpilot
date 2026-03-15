.PHONY: install dev lint type-check test clean

install:
	uv sync --all-groups

dev:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

lint:
	uv run ruff check .
	uv run ruff format --check .

type-check:
	uv run mypy app

test:
	uv run pytest

clean:
	rm -rf .venv __pycache__ dist *.egg-info
