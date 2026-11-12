# syntax=docker/dockerfile:1

# One image for every Python process: migrate, api, worker and beat (and, later,
# the tests and demo profiles). Dependencies come only from uv.lock (NFR-9).

# --- Build stage: resolve the locked runtime dependencies into /app/.venv -----
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# --- Runtime stage: no build tools, non-root user ------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

RUN groupadd --system sift \
    && useradd --system --gid sift --home-dir /app --no-create-home sift

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY manage.py ./
COPY sift ./sift

USER sift
EXPOSE 8000

CMD ["uvicorn", "sift.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
