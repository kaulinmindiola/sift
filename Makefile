# Recipes start with ">" instead of a tab, so copying this file never breaks it.
.RECIPEPREFIX := >
.DEFAULT_GOAL := help

.PHONY: help install up down infra api fmt lint types test check

help:
> @echo "install  sync all dependency groups and install the pre-commit hook"
> @echo "up       build and start the full compose stack"
> @echo "down     stop the compose stack"
> @echo "infra    start postgres, redis, minio and run migrations"
> @echo "api      run the API natively with autoreload"
> @echo "fmt      format and autofix"
> @echo "lint     ruff, format check and migrations check"
> @echo "types    mypy"
> @echo "test     pytest without chaos tests, with coverage"
> @echo "check    lint + types + test (run before every commit)"

install:
> uv sync --all-groups
> uv run pre-commit install

up:
> docker compose up --build -d

down:
> docker compose down

infra:
> docker compose up -d postgres redis minio migrate

api:
> uv run uvicorn sift.asgi:application --reload

fmt:
> uv run ruff format .
> uv run ruff check --fix .

lint:
> uv run ruff check .
> uv run ruff format --check .
> uv run python manage.py makemigrations --check --dry-run

types:
> uv run mypy

test:
> uv run pytest -m "not chaos" --cov

check: lint types test
