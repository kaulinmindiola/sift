# Sift

Sift imports large CSV files into a multi-tenant catalog without loading them into memory, without applying half a file, and without applying anything twice.

> **Status: work in progress.** Phase F0 (bootstrap) is complete: project
> skeleton, email-based user model, liveness endpoint, compose stack and CI.
> The import pipeline itself is built in phases F1–F8; nothing below claims
> features that are not merged yet.

## Why

A naive importer reads the whole file into memory, inserts row by row and fails
in four ways: a large file kills the worker, a crash leaves the catalog half
updated, a retry imports the file twice, and the user waits without knowing
what is happening or which rows are wrong. Sift is designed to guarantee
**bounded memory**, **all-or-nothing apply**, **idempotent imports** and
**row-level, live feedback**. The full requirements and design are in
[`docs/srs-sdd.md`](docs/srs-sdd.md).

## Quick start

Requirements: Docker with Compose v2.

```bash
docker compose up --build
```

This builds one image and starts PostgreSQL 17, Redis 7, MinIO, a one-shot
`migrate` service (database migrations and the private bucket), the API, a
Celery worker and Celery beat. No `.env` file is needed: development defaults
are in `docker-compose.yml`.

Check that it is up:

```bash
curl http://localhost:8000/health/live
# {"status": "ok"}
```

| Service | Address on the host |
| --- | --- |
| API | http://localhost:8000 |
| PostgreSQL | localhost:5432 (user `sift`, database `sift`) |
| Redis | localhost:6379 |
| MinIO (S3 API) | http://localhost:9000 |

Stop with `docker compose down`. `docker compose down -v` also deletes the
database and storage volumes.

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for
the project), Docker, and GNU make (optional; on Windows
`winget install ezwinports.make`).

```bash
uv sync --all-groups            # .venv with locked dependencies (uv.lock)
uv run pre-commit install       # ruff and file hygiene on every commit
cp .env.example .env            # settings for running the API and tests natively
docker compose up -d postgres redis minio migrate   # infrastructure only
make check                      # lint + types + tests, as in CI
```

| Command | What it runs |
| --- | --- |
| `make check` | `make lint`, `make types` and `make test`, in order |
| `make lint` | `ruff check`, `ruff format --check`, architecture tests, `makemigrations --check` |
| `make types` | `mypy` (strict on the import domain and services) |
| `make test` | `pytest -m "not chaos" --cov` (85% coverage floor) |
| `make api` | the API natively with autoreload on port 8000 |
| `make fmt` | `ruff format` and `ruff check --fix` |

Without make, run the same commands with `uv run`, for example
`uv run pytest -m "not chaos" --cov`. The Celery worker and beat always run in
containers: Celery does not support Windows.

## Project layout

```text
sift/
  accounts/   custom user (email login); organizations and roles in F1
  catalog/    product catalog (F3–F4)
  imports/    import jobs; domain/ holds the pure business rules (NFR-10)
  storage/    S3 access; ensure_bucket command
  common/     settings helpers, ImportSettings, health endpoints
tests/        architecture, unit and integration tests
docs/         SRS/SDD and architecture decision records (docs/adr/)
```

## Architecture decisions

| ADR | Decision |
| --- | --- |
| [001](docs/adr/001-framework.md) | Django 5.2 LTS with DRF and Channels |
| [007](docs/adr/007-redis-broker.md) | Redis as Celery broker, channel layer and ticket store |
| [010](docs/adr/010-code-structure.md) | Services and selectors around a pure domain package |
| [015](docs/adr/015-local-object-storage.md) | Chainguard MinIO pinned by digest; bucket created by `ensure_bucket` |

The remaining ADRs are written in the phase that implements them.

## License

[MIT](LICENSE)
