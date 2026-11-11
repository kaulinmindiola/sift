# Sift — SRS and SDD

Version 0.1 · 2026-11-10 · Status: draft (decisions D1–D12 open, section 19)

**Sift imports large CSV files into a multi-tenant catalog without loading them into memory, without applying half a file, and without applying anything twice.**

## 0. How to read this document

Part I (sections 1–5) is the SRS: what the system must do, written so each item can be verified. Part II (sections 6–18) is the SDD: how it is built. Every requirement has an ID (FR-, NFR-, VR-) that tests, commits and the README evidence table will reference. Priorities follow MoSCoW: **Must** is the two-week MVP, **Should** enters if the MVP is green before day 9, **Could** is backlog.

Items tagged **\[DECISION\]** are open and have a proposed value; section 19 lists them. Until a decision is closed, the proposed value applies. Architecture decisions are only *planned* here (section 18): each ADR is written in `docs/adr/` during the phase that implements it, with what the implementation taught.

---

# Part I — Software Requirements Specification (SRS)

## 1. Introduction

### 1.1 Problem

Back-office teams load data in bulk: a supplier sends a 500,000-row product file, finance exports transactions, someone fixes prices in a spreadsheet. The naive importer reads the whole file into memory, inserts row by row with the ORM, and fails in four ways:

1. **Memory.** A large file kills the worker.
2. **Partial state.** A crash at row 300,000 leaves the catalog half updated, with no way to tell which half.
3. **Duplicates.** A client retry or a redelivered task imports the file twice.
4. **No feedback.** The user waits minutes without knowing whether the job is alive, and gets "error" with no row-level explanation.

Sift guarantees four things: **bounded memory whatever the file size**, **all-or-nothing apply**, **idempotent imports**, and **row-level, live feedback**.

### 1.2 In scope

- Organizations, users, memberships with roles; JWT authentication.
- Direct upload to object storage with presigned POST (MinIO locally).
- Import jobs for one dataset, `products`, with explicit state machine.
- Streaming validation in checkpointed batches; row-level errors; downloadable error report.
- Preview (diff against the current catalog) before apply.
- Atomic apply with `upsert` mode and, if time allows, `sync` mode.
- Live progress over WebSocket; REST equivalents.
- Recovery of crashed jobs (Celery Beat rescuer); housekeeping.
- Data generator with an oracle, demo client, benchmark of 1M rows.
- Observability: structured logs, `/health`, Prometheus metrics.

### 1.3 Out of scope

Web UI beyond a single demo page, XLSX and other formats (backlog), user-defined schemas or rules, self sign-up, billing, Kubernetes, real AWS deployment, antivirus scanning of uploads, PostgreSQL Row Level Security.

### 1.4 Demonstration criteria (non-negotiable)

| # | Criterion | Where it is satisfied |
| --- | --- | --- |
| 1 | Solves a hard problem and says so in the first line | README first line; this document's first line |
| 2 | Tests failures on purpose | VR-4, VR-5, VR-6, VR-13 |
| 3 | Proves the memory claim with a number | VR-16, NFR-1 |
| 4 | Starts with one command | NFR-8 (`docker compose up --build`) |
| 5 | CI is green | NFR-7, section 16 |
| 6 | States honestly what it does not do | Section 17.2 |

### 1.5 Glossary

- **Organization (org)**: a tenant. Every product, upload and job belongs to exactly one.
- **Upload**: an object in storage plus the record that authorizes it.
- **Import job (job)**: one attempt to bring one uploaded file into the catalog.
- **Record**: one CSV data record (a logical row; may span several lines when quoted).
- **Staging**: the `import_rows` table that holds the valid, normalized records of a job before apply.
- **Batch**: `BATCH_SIZE` consecutive records validated and committed together with the checkpoint.
- **Checkpoint**: the number of the last record whose batch committed.
- **Preview**: the diff between staging and the current catalog, computed after validation.
- **Apply**: the transaction that writes staging into the catalog.

## 2. Overall description

### 2.1 Context

```
                    presigned POST (file bytes)
Client ──────────────────────────────────────────────▶ MinIO / S3 (private bucket)
  │                                                          ▲  stream (GET)
  │ HTTPS + JWT            ┌──────────── Celery worker ──────┘
  ├──────────▶ Django API ─┤ enqueue        │  COPY, upsert, checkpoint
  │  (DRF)        │        └──▶ Redis ◀─────┤
  │               ▼            (broker,     ▼
  │          PostgreSQL ◀──── channel   PostgreSQL (source of truth)
  │                           layer)        │
  └── WebSocket ◀── Channels consumer ◀─────┘ progress events (group_send)
                    Celery Beat: rescuer, housekeeping
```

API and WebSocket run in one ASGI process. Worker and Beat are separate processes from the same code base.

### 2.2 Actors

- **Member**: uploads files, creates, previews, applies and cancels imports in their organization.
- **Viewer**: reads jobs, errors, previews and the catalog.
- **Org admin**: member rights plus membership management (Django admin in the MVP).
- **Superuser**: creates organizations and users (Django admin).
- **Monitoring**: probes `/health`, scrapes `/metrics`.

### 2.3 The `products` file contract

UTF-8 (a leading BOM is ignored), comma delimiter, RFC 4180 quoting, one header record. Header names are matched after trimming and lower-casing. Extra columns are ignored and listed in the job's `warnings`.

| Column | Required | Rule | Normalized to |
| --- | --- | --- | --- |
| `sku` | yes | 1–64 chars, `[A-Za-z0-9._-]` | as given (case preserved; uniqueness is case-sensitive) |
| `name` | yes | 1–200 chars after trimming | trimmed text |
| `price` | yes | decimal, `>= 0`, `<= 99999999.99`, at most 2 decimal places, `.` separator, no thousands separator | `Decimal`, never `float` |
| `currency` | yes | ISO 4217 code in the org's allowed list (default `USD, EUR, COP`) | upper case |
| `stock` | yes | integer `0`–`2147483647` | `int` |
| `category` | no | up to 100 chars | trimmed text or null |
| `active` | no | `true/false/1/0/yes/no` (case-insensitive); empty means `true` | `bool` |

Identity of a product is `(organization, sku)`.

### 2.4 Constraints and assumptions

Python 3.12; PostgreSQL 17 single primary; Redis 7; MinIO as S3-compatible storage; Docker Compose for local run. Django version per D8. One dataset type in the MVP; the design keeps the dataset behind a small interface so a second one is additive.

## 3. Functional requirements

### 3.1 Accounts and tenancy (FR-ACC)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-ACC-1 | Users log in with email and password and receive a JWT access token (15 min) and refresh token (7 days, rotated on use). **\[DECISION D4\]** | Must |
| FR-ACC-2 | A user belongs to organizations through memberships with role `viewer`, `member` or `admin`; one membership per (user, org). | Must |
| FR-ACC-3 | Every org-scoped route takes the org slug in the path. A user who is not a member gets `404` (the org's existence is not revealed). | Must |
| FR-ACC-4 | Viewers can only read; members can also upload, create, apply and cancel imports; admins can also manage memberships. Insufficient role in an org the user belongs to → `403`. | Must |
| FR-ACC-5 | Every object (upload, job, error, product) is reachable only through its org; an id from another org → `404`. | Must |
| FR-ACC-6 | Organizations and users are created by a superuser in Django admin; there is no self sign-up. | Must |
| FR-ACC-7 | The login endpoint is throttled (default 10 requests/min per IP) → `429`. | Should |

### 3.2 Uploads (FR-UPL)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-UPL-1 | `POST /orgs/{org}/uploads` with `filename` returns a presigned POST (`url`, `fields`, `expires_at`) valid `UPLOAD_URL_TTL_S` (600 s), restricted to one object key and to `content-length-range` `1..MAX_FILE_BYTES` (200 MiB). | Must |
| FR-UPL-2 | The object key is generated by the server (`orgs/<org_id>/uploads/<upload_id>.csv`); the client never chooses it. | Must |
| FR-UPL-3 | The bucket is private; objects are read only by the worker and through short-lived presigned GETs. | Must |
| FR-UPL-4 | Creating an import verifies the object exists (`HEAD`) and records its size; missing → `422 upload_not_received`. | Must |
| FR-UPL-5 | One upload backs at most one import job; reuse → `409 upload_already_used`. | Must |
| FR-UPL-6 | Uploads never attached to a job are deleted, record and object, after `UPLOAD_EXPIRY_H` (24 h). | Should |

### 3.3 Import jobs (FR-JOB)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-JOB-1 | `POST /orgs/{org}/imports` with `upload_id`, `dataset` (`products`), `mode` (`upsert` or `sync`) and `auto_apply` (default `false`) creates a job in `queued`, enqueues validation after commit, and responds `202` with the job. | Must |
| FR-JOB-2 | Optional `Idempotency-Key` header: same key and same body within 24 h returns the original job (`200`); same key with a different body → `409 idempotency_key_reused`; concurrent requests with one key create one job. | Must |
| FR-JOB-3 | Jobs follow exactly the state machine of section 9. Every transition is written to `job_transitions` with reason and request id. | Must |
| FR-JOB-4 | `GET /orgs/{org}/imports` lists jobs newest first with cursor pagination and filters `status`, `created_by`. `GET .../imports/{id}` returns the job with counts, warnings, failure code and timestamps. | Must |
| FR-JOB-5 | `POST .../imports/{id}/cancel` on `queued`, `validating` or `validated` → `cancelled` (a running validation stops at its next batch boundary); otherwise `409 job_not_cancellable`. | Must |
| FR-JOB-6 | At most `MAX_ACTIVE_JOBS_PER_ORG` (3) jobs per org in `validating`; more wait in `queued`. | Could |

### 3.4 Validation (FR-VAL)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-VAL-1 | The file is streamed from storage and parsed incrementally; it is never fully held in memory or written to local disk. | Must |
| FR-VAL-2 | Header checks: missing required column → job `rejected` with `header_invalid` listing the missing columns; duplicate column names → `header_invalid`; extra columns → warning. | Must |
| FR-VAL-3 | Each record is validated against section 2.3. A valid record is normalized and staged; an invalid record produces one error per failing column (`row_number`, `line`, `column`, `code`, `message`, `value` truncated to 100 chars). | Must |
| FR-VAL-4 | A record with the wrong number of fields → one error `malformed_record`; invalid UTF-8 anywhere → job `rejected` with `encoding_error` and the byte offset. | Must |
| FR-VAL-5 | A file with no data records → `rejected` `empty_file`; more than `MAX_ROWS` (2,000,000) records → reading stops, `rejected` `too_many_rows`. | Must |
| FR-VAL-6 | Records are committed in batches of `BATCH_SIZE` (5,000). Staged rows, errors, counters, checkpoint and heartbeat of a batch commit in one transaction. | Must |
| FR-VAL-7 | After a crash, validation resumes after the checkpoint and produces exactly the staging, errors and counts of an uninterrupted run. | Must |
| FR-VAL-8 | Within a file, the first record of a `sku` is kept; every later one is removed from staging and gets `duplicate_key_in_file` referencing the first row. | Must |
| FR-VAL-9 | If `invalid_rows / total_rows > ERROR_RATE_THRESHOLD` (0.05) the job ends `rejected` `error_rate_exceeded` and nothing can be applied. **\[DECISION D2\]** | Must |
| FR-VAL-10 | Error details are stored up to `MAX_STORED_ERRORS` (10,000) per job; counts per error code are always complete. | Must |
| FR-VAL-11 | `GET .../imports/{id}/errors` lists stored errors by `row_number` with cursor pagination and `code` filter. | Must |
| FR-VAL-12 | At the end of validation (validated or rejected for rows) an error report CSV is written to storage; `GET .../imports/{id}/error-report` returns a presigned GET (60 s). Cells are escaped against formula injection (FR-SEC-2). | Must |
| FR-VAL-13 | The file's SHA-256 and size are recorded. If an earlier job of the org with the same hash and dataset completed in the last 30 days, the job gets warning `identical_to_job` with that job's id; it is not blocked. | Should |

### 3.5 Preview (FR-PRV)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-PRV-1 | When validation succeeds, the job stores a preview: `to_insert`, `to_update`, `unchanged` and, in `sync` mode, `to_deactivate`. | Must |
| FR-PRV-2 | `GET .../imports/{id}/preview` returns the counts and up to 50 sample changes with the changed fields' before and after values. | Should |
| FR-PRV-3 | A `validated` job not applied within `PREVIEW_TTL_H` (24 h) becomes `expired` and its staging is purged. | Must |

### 3.6 Apply (FR-APP)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-APP-1 | `POST .../imports/{id}/apply` on a `validated` job moves it to `applying` and enqueues the apply (`202`); any other state → `409 job_not_validated`. A job created with `auto_apply=true` goes from `validated` to `applying` without the call. **\[DECISION D3\]** | Must |
| FR-APP-2 | Apply is one database transaction: either every staged row of the job reaches the catalog or none does. | Must |
| FR-APP-3 | Applies for the same (org, dataset) are serialized; applies of different orgs run in parallel. | Must |
| FR-APP-4 | The diff is recomputed inside the apply transaction. Final counts are stored next to the preview counts; a difference is reported as warning `catalog_changed_since_preview`. | Must |
| FR-APP-5 | Products are upserted by `(org, sku)`: new rows inserted; existing rows updated only when their content hash differs; unchanged rows are not written (their `updated_at` stays). | Must |
| FR-APP-6 | In `sync` mode, active products of the org whose `sku` is not in staging are set `active = false`. Products are never deleted. **\[DECISION D7\]** | Should |
| FR-APP-7 | Each written product records `last_job_id`. | Must |
| FR-APP-8 | A job's staging rows are deleted when it reaches a terminal state. | Must |

### 3.7 Live progress (FR-RT)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-RT-1 | `POST .../imports/{id}/ws-ticket` returns a single-use ticket valid `WS_TICKET_TTL_S` (30 s) for a user who can read the job. `ws/imports/{id}/?ticket=...` accepts it once; invalid, used or expired → close code 4401. **\[DECISION D4\]** | Must |
| FR-RT-2 | On connect the server sends a `snapshot` built from the database, then `progress` and `status` events, each with a per-job increasing `seq`. | Must |
| FR-RT-3 | `progress` events are sent at most once per `PROGRESS_MIN_INTERVAL_MS` (500 ms) per job and carry `bytes_read`, `total_bytes`, `rows_read`, `valid_rows`, `invalid_rows`. | Must |
| FR-RT-4 | Events are best effort: a lost event never changes job state, and `GET .../imports/{id}` always gives the authoritative state. | Must |
| FR-RT-5 | The server closes the socket (code 1000) after sending a terminal `status` event. | Must |
| FR-RT-6 | `/demo/` is a single HTML page (no build step) that logs in, uploads a file, follows progress live and offers apply. | Should |

### 3.8 Recovery and housekeeping (FR-REC)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-REC-1 | The validating worker updates `heartbeat_at` at every batch commit; the apply sets `lease_until = now() + APPLY_LEASE_S` before it starts. | Must |
| FR-REC-2 | Every `RESCUE_INTERVAL_S` (30 s) Celery Beat runs a rescuer: `queued` jobs older than 60 s, `validating` jobs with `heartbeat_at` older than `HEARTBEAT_STALE_S` (120 s) and `applying` jobs past `lease_until` are re-enqueued with `attempts + 1`; at `MAX_ATTEMPTS` (3) they end `failed` with `attempts_exhausted`. | Must |
| FR-REC-3 | A task starts work only after a compare-and-set claim on `(status, run_token)`; duplicate or stale messages are no-ops. | Must |
| FR-REC-4 | Housekeeping (hourly): expire previews (FR-PRV-3), delete orphan uploads (FR-UPL-6), delete error report objects older than `REPORT_RETENTION_D` (7 days). | Must |

### 3.9 Catalog (FR-CAT)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-CAT-1 | `GET /orgs/{org}/products` lists products with `search` (prefix on `sku` or `name`), `active` and `category` filters and cursor pagination. | Must |
| FR-CAT-2 | `GET /orgs/{org}/products/{sku}` returns one product with `last_job` (id and finished time). | Must |

### 3.10 Observability (FR-OBS)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-OBS-1 | JSON logs include `request_id`, `org_id`, `user_id`, `job_id` when known. The request id comes from `X-Request-Id` (if safe) or is generated, is echoed in the response and travels to Celery tasks as a message header. | Must |
| FR-OBS-2 | `GET /health/live` is 200 while the process answers. `GET /health` checks `db`, `redis` and `storage`: database down → `503 down`; Redis or storage down → `200 degraded`. | Must |
| FR-OBS-3 | `GET /metrics` exposes the metrics in section 15.2; the worker serves its own on `WORKER_METRICS_PORT`. | Should |

### 3.11 Security (FR-SEC)

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-SEC-1 | Secrets come from environment variables and are never logged. File contents and cell values are never logged (they are stored, truncated, only in `import_errors.value`). | Must |
| FR-SEC-2 | In the error report, any cell starting with `=`, `+`, `-`, `@`, tab or carriage return is prefixed with `'` (CSV formula injection, OWASP). | Must |
| FR-SEC-3 | API errors use `application/problem+json` (RFC 9457) with a stable `code`; they never include stack traces or SQL. | Must |

## 4. Non-functional requirements

| ID | Requirement |
| --- | --- |
| NFR-1 | Memory: validating a 1,000,000-record file (about 100 MB) keeps the worker's peak RSS under 300 MB, and the peak does not grow with file size (measured at 100k and 1M records). |
| NFR-2 | Throughput: validate plus apply of 1,000,000 records in under 3 minutes on a dev laptop; measured and reported (target, not a guarantee). |
| NFR-3 | Reliability: no accepted job is lost or partially applied under worker SIGKILL during validation or apply, or a Redis restart. |
| NFR-4 | Isolation: no endpoint returns or changes another org's data (VR-7 runs over every route). |
| NFR-5 | Query budget: every list endpoint runs a constant number of queries whatever the page size. |
| NFR-6 | Latency: p95 under 150 ms for non-upload API endpoints on a dev laptop, measured with 100k products in the catalog. |
| NFR-7 | Quality gates in CI: `ruff check`, `ruff format --check`, `mypy` (strict on `domain` and `services`, with `django-stubs` and `djangorestframework-stubs`), `pytest` with at least 85% line coverage of `sift/` (migrations excluded), `manage.py makemigrations --check`. |
| NFR-8 | `docker compose up --build` starts every service, creates the bucket, applies migrations, loads a demo org and user, and exposes the API. |
| NFR-9 | Python 3.12; dependencies pinned in `uv.lock`; Django per D8. |
| NFR-10 | The `domain` package has no Django, Celery, boto3 or database imports (checked in CI). |
| NFR-11 | README opens with the problem, shows an evidence table and measurements, and lists limitations. |

## 5. Verification matrix

| ID | Test | Covers |
| --- | --- | --- |
| VR-1 | Hypothesis: any generated record yields either one normalized product or at least one error, never both; `price` round-trips exactly as `Decimal`. | FR-VAL-3/4 |
| VR-2 | Hypothesis: validating a generated file with a simulated crash after a random batch, then resuming, gives the same staging, errors and counts as an uninterrupted run. | FR-VAL-6/7 |
| VR-3 | Re-importing an already applied file: `to_update = 0`, `to_insert = 0`, no product's `updated_at` changes. | FR-APP-5, FR-VAL-13 |
| VR-4 | Chaos: a real worker is killed with SIGKILL in the middle of validation; the rescuer re-enqueues the job, it resumes after the checkpoint (not from record 1) and its counts equal the generator's oracle. | FR-VAL-7, FR-REC-1/2/3, NFR-3 |
| VR-5 | Chaos: a real worker is killed during the apply transaction; the catalog shows none of the job's rows; after rescue the job completes and every row is applied once. | FR-APP-2, FR-REC-2, NFR-3 |
| VR-6 | Two jobs of one org applied concurrently: they serialize, no deadlock, final catalog equals applying them one after the other in commit order. A third org's apply is not blocked. | FR-APP-3 |
| VR-7 | Isolation: a test enumerates every URL pattern; a member of org B gets `404` for org A paths and for org A object ids under org B paths; roles get `403` where FR-ACC-4 says. | FR-ACC-3/4/5, NFR-4 |
| VR-8 | Query count: list imports, errors and products with 5 and with 50 items run the same number of queries. | NFR-5 |
| VR-9 | Error rate above threshold → `rejected`, catalog untouched, error report available. Exactly at threshold → `validated`. | FR-VAL-9/12 |
| VR-10 | File-level failures: missing column, duplicate header, invalid UTF-8 (byte offset reported), empty file, `MAX_ROWS + 1` records. | FR-VAL-2/4/5 |
| VR-11 | Duplicate `sku` in a file, including across batch boundaries and after a resume: first kept, later ones flagged with the first row number. | FR-VAL-8 |
| VR-12 | `Idempotency-Key`: same key and body → same job; different body → 409; 16 concurrent requests with one key → one job, one enqueue. | FR-JOB-2 |
| VR-13 | Cancel during validation stops at the next batch; staging purged; catalog untouched; cancel during `applying` → 409. | FR-JOB-5, FR-APP-8 |
| VR-14 | WebSocket: snapshot first, `seq` strictly increasing, terminal status then close; a ticket works once; an expired or foreign ticket is refused. | FR-RT-1 to 5 |
| VR-15 | Error report: cells starting with `=`, `+`, `-`, `@`, tab, CR are prefixed; the file opens as the same table. | FR-SEC-2, FR-VAL-12 |
| VR-16 | Benchmark: peak RSS and duration for 100k and 1M records, Redis up. | FR-VAL-1, NFR-1/2 |
| VR-17 | State machine property: random trigger sequences never produce an illegal transition. | FR-JOB-3 |
| VR-18 | `sync` mode deactivates exactly the active products absent from the file and nothing else. | FR-APP-6 |
| VR-19 | Catalog changed between preview and apply: apply uses the fresh diff and reports both counts. | FR-APP-4 |
| VR-20 | Presigned POST: upload above `MAX_FILE_BYTES` is refused by storage; a different key is refused; an import for an upload of another org → 404. | FR-UPL-1/2/5, FR-ACC-5 |
| VR-21 | API contract tests, one per endpoint: status codes, problem+json `code`s, pagination never repeats or skips, counts and `last_job_id` after apply, error listing capped at `MAX_STORED_ERRORS` with complete counts, missing upload → 422. | FR-ACC-1/2, FR-UPL-4, FR-JOB-1/4, FR-VAL-10/11, FR-PRV-1, FR-APP-1/7, FR-CAT-1/2, FR-OBS-2, FR-SEC-3 |
| VR-22 | Housekeeping with back-dated timestamps: previews expire and purge staging; orphan uploads and old reports are deleted from the database and storage. | FR-PRV-3, FR-UPL-6, FR-REC-4 |
| VR-23 | Hygiene: an anonymous GET on an object is refused by storage; a full import run with captured logs contains no cell value or secret and every line carries `request_id` (worker lines included); no sign-up route exists. | FR-UPL-3, FR-SEC-1, FR-OBS-1, FR-ACC-6 |

Test names start with the VR id (`test_vr04_...`) and docstrings list the FR ids they cover, so the README evidence table and a `grep` give the trace from requirement to test.

---

# Part II — Software Design Description (SDD)

## 6. Architecture

### 6.1 Django apps and layers

```
sift/                       # Django project: settings, urls, asgi, celery app
  accounts/                 # custom User (email login), Organization, Membership, permissions
  catalog/                  # Product model, read API
  imports/
    domain/                 # PURE: records, rules, normalization, row hash, state machine, errors
    services/               # use cases: create_job, validate_job, apply_job, cancel_job, rescue
    selectors.py            # read queries (lists, preview, errors) with explicit select/prefetch
    staging.py              # COPY into import_rows, set-based SQL (duplicates, diff, upsert)
    tasks.py                # Celery tasks: thin, delegate to services
    consumers.py            # Channels consumer
    api/                    # DRF serializers, views, urls
  storage/                  # S3 adapter: presign POST/GET, head, streaming reader with hashing
  common/                   # problem+json errors, request id, logging, pagination, metrics
tools/                      # data generator + oracle, demo client, benchmark
```

Rules: views and tasks call services; services own transactions; `domain` is pure Python (NFR-10) so Hypothesis tests run in milliseconds. This is the services/selectors style for Django, plus a pure domain package. **\[DECISION D9\]**

### 6.2 Processes

| Process | Command | Role |
| --- | --- | --- |
| api | `uvicorn sift.asgi:application` | DRF over HTTP and Channels over WebSocket in one ASGI app **\[DECISION D10\]** |
| worker | `celery -A sift worker -Q imports` | validation and apply |
| beat | `celery -A sift beat` | rescuer and housekeeping |
| migrate | `manage.py migrate && manage.py seed_demo` | one-shot, before api |
| minio-init | `mc mb` | creates the private bucket |

DRF views are synchronous and run in the ASGI thread pool; only the consumer is async.

## 7. Main flows

### 7.1 Upload and create

```
1. POST /orgs/{org}/uploads {filename}          -> Upload(pending) + presigned POST
2. client POSTs the file straight to MinIO      (size and key enforced by the policy)
3. POST /orgs/{org}/imports {upload_id, ...}    + Idempotency-Key
   a. HEAD object -> size; missing -> 422
   b. BEGIN; INSERT job(queued) [unique (org, idempotency_key)]; mark upload used; transition row; COMMIT
   c. after commit: validate_job.delay(job_id, run_token)
4. 202 {job}
```

### 7.2 Validation (one task run)

```
claim: UPDATE import_jobs SET status='validating', run_token=:new, attempts=attempts+1, heartbeat_at=now()
       WHERE id=:id AND status IN ('queued','validating') AND run_token=:expected RETURNING checkpoint_row
       -- 0 rows: stale or duplicate message -> exit
open S3 stream -> HashingReader (sha256, bytes_read) -> UTF-8 decoder -> csv.reader
check header (first run only; stored in job.header)
for each record:
    if record_no <= checkpoint_row: continue          # still hashed; skipped for work
    domain.validate(record) -> NormalizedRow | [RowError]
    append to batch buffers
    if len(batch) == BATCH_SIZE: commit_batch()
commit_batch() for the tail
finalize_validation()

commit_batch():   BEGIN
                    COPY import_rows FROM STDIN (valid rows)
                    INSERT import_errors (until MAX_STORED_ERRORS)
                    UPDATE import_jobs SET checkpoint_row, counters, error_counts, heartbeat_at
                      WHERE id=:id AND run_token=:mine AND NOT cancel_requested   -- 0 rows -> abort
                  COMMIT; then progress event (throttled)

finalize_validation():  BEGIN
                    mark later duplicates (window function), move them to import_errors
                    error-rate check -> rejected | validated
                    compute preview counts (section 12)
                    store sha256, size; identical_to_job warning
                  COMMIT; write error report to S3; status event; if auto_apply -> apply
```

Because the batch, its errors and the checkpoint commit together, a crash loses at most the uncommitted batch, and resuming after `checkpoint_row` reproduces it exactly (VR-2). The whole file is re-read from storage on resume so that the SHA-256 covers every byte; the skipped part costs read and parse time, not validation or writes. **\[ADR-005\]**

### 7.3 Apply

```
claim: UPDATE import_jobs SET run_token=:new, attempts=attempts+1, lease_until=now()+APPLY_LEASE_S
       WHERE id=:id AND status='applying' AND run_token=:expected
BEGIN
  SELECT pg_advisory_xact_lock(hashtext('sift:apply'), :org_lock_key)     -- serializes per org
  SELECT status FROM import_jobs WHERE id=:id FOR UPDATE                    -- completed already? -> no-op
  recompute diff counts (staging vs products)
  INSERT INTO products (...) SELECT ... FROM import_rows WHERE job_id=:id
    ON CONFLICT (organization_id, sku) DO UPDATE SET ...
    WHERE products.row_hash IS DISTINCT FROM EXCLUDED.row_hash
  [sync] UPDATE products SET active=false, last_job_id=:id
         WHERE organization_id=:org AND active AND NOT EXISTS (staging row with that sku)
  DELETE FROM import_rows WHERE job_id=:id
  UPDATE import_jobs SET status='completed', applied counts, finished_at; transition row
COMMIT; status event
```

A worker killed inside the transaction leaves nothing behind (PostgreSQL rolls back); the job stays `applying` until its lease passes and the rescuer re-enqueues it (VR-5). The lease must exceed the longest apply measured in VR-16; the benchmark sets `APPLY_LEASE_S`. **\[ADR-006\]**

### 7.4 Rescue

```
every RESCUE_INTERVAL_S, one transaction with FOR UPDATE SKIP LOCKED:
  queued      and created_at  < now() - 60 s           -> re-enqueue
  validating  and heartbeat_at < now() - HEARTBEAT_STALE_S
  applying    and lease_until  < now()
  attempts >= MAX_ATTEMPTS -> failed (attempts_exhausted), staging purged
  else new run_token, attempts unchanged here (incremented at claim)
publish after commit
```

The new `run_token` invalidates the old worker if it is only slow, not dead: its next batch commit matches 0 rows and it stops. **\[ADR-008\]**

## 8. Data model

PostgreSQL; Django migrations own the schema. Hand-written SQL lives only in `imports/staging.py` and is covered by integration tests.

**accounts\_user**: custom user, `email` unique (login), `full_name`, Django auth fields.

**accounts\_organization**: `id uuid PK, slug unique, name, allowed_currencies text[] default {USD,EUR,COP}, created_at`.

**accounts\_membership**: `id, user_id FK, organization_id FK, role enum(viewer, member, admin), created_at`; `UNIQUE (user_id, organization_id)`.

**storage\_upload**

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid PK | |
| organization\_id | FK | |
| created\_by\_id | FK | |
| object\_key | text unique | server-generated |
| filename | text | display only |
| size\_bytes | bigint null | set by HEAD at job creation |
| status | enum | pending, used, expired |
| created\_at, expires\_at | timestamptz | |

**imports\_job**

| Column | Type | Notes |
| --- | --- | --- |
| id | uuid PK | |
| organization\_id, created\_by\_id, upload\_id | FK | `upload_id` unique |
| dataset | text | `products` |
| mode | enum | upsert, sync |
| auto\_apply | bool | |
| status | enum | section 9 |
| idempotency\_key, request\_fingerprint | text null | `UNIQUE (organization_id, idempotency_key)`; fingerprint = SHA-256 of the canonical body |
| run\_token | uuid | changes at every claim and rescue |
| attempts | int | incremented at claim |
| heartbeat\_at, lease\_until | timestamptz null | |
| cancel\_requested | bool | |
| header | jsonb null | resolved column order |
| checkpoint\_row | int | last committed record number |
| bytes\_read, total\_bytes | bigint | |
| total\_rows, valid\_rows, invalid\_rows | int | |
| error\_counts | jsonb | `{code: n}`, complete |
| stored\_errors | int | capped at `MAX_STORED_ERRORS` |
| preview\_counts, applied\_counts | jsonb null | insert, update, unchanged, deactivate |
| warnings | jsonb | list of `{code, detail}` |
| file\_sha256 | char(64) null | |
| error\_report\_key | text null | |
| failure\_code, failure\_detail | text null | |
| created\_at, started\_at, validated\_at, finished\_at | timestamptz | |

Indexes: `(organization_id, created_at DESC, id)` for listing; partial `(status, heartbeat_at)` where status in active states for the rescuer; `(organization_id, dataset, file_sha256)` where completed.

**imports\_jobtransition**: `id, job_id FK, from_status, to_status, reason, request_id, at`.

**imports\_row** (staging): `job_id, row_number, sku, name, price numeric(10,2), currency char(3), stock int, category, active bool, row_hash bytea`; `PRIMARY KEY (job_id, row_number)`, index `(job_id, sku)`. Declared as a Django model with `managed` migrations so tests and admin see it; written only with `COPY`. Logged vs `UNLOGGED` is measured in F7. **\[ADR-004\]**

**imports\_rowerror**: `id bigserial, job_id FK, row_number, line, column, code, message, value varchar(100), first_row_number null`; index `(job_id, row_number)`.

**catalog\_product**

| Column | Type | Notes |
| --- | --- | --- |
| id | bigint PK | |
| organization\_id | FK | `UNIQUE (organization_id, sku)` |
| sku, name, price, currency, stock, category, active | as in staging | |
| row\_hash | bytea | SHA-256 of the canonical normalized values |
| last\_job\_id | FK null | |
| created\_at, updated\_at | timestamptz | |

Indexes: `(organization_id, sku text_pattern_ops)` and `(organization_id, lower(name) text_pattern_ops)` for prefix search.

**Row hash.** `sha256("\x1f".join(canonical values))` where `Decimal` is formatted with two decimals, booleans as `1/0` and null as empty. Computed in `domain`, so file and catalog compare by bytes, not by type-specific SQL.

## 9. Job state machine

| From | To | Trigger | Guard / action |
| --- | --- | --- | --- |
| (new) | queued | create | upload exists and unused |
| queued | validating | claim | CAS on status and run\_token; attempts+1 |
| validating | validating | claim after rescue | resumes after checkpoint |
| validating | validated | finalize | error rate within threshold |
| validating | rejected | file-level error or error rate exceeded | failure\_code set; staging purged |
| validated | applying | apply call or auto\_apply | |
| applying | completed | apply transaction commits | |
| queued, validating, validated | cancelled | cancel | validating: honored at next batch boundary |
| validated | expired | housekeeping | PREVIEW\_TTL\_H passed |
| queued, validating, applying | failed | rescuer | attempts >= MAX\_ATTEMPTS |

Terminal: `completed`, `rejected`, `cancelled`, `expired`, `failed`. Leaving a terminal state is forbidden; `applying → cancelled` is forbidden (the transaction is either running or committed).

`domain.state_machine.transition(status, trigger, *, attempts, max_attempts) -> Transition` decides; services apply it with a compare-and-set `UPDATE ... WHERE status = :from` and write the transition row in the same transaction: the pure function decides, SQL applies.

## 10. Upload and storage design

**Presigned POST, not PUT.** A presigned PUT cannot enforce a maximum size; a POST policy can (`content-length-range`) and also pins the key and `Content-Type`. **\[ADR-002\]**

```python
s3.generate_presigned_post(
    Bucket=BUCKET, Key=key,
    Fields={"Content-Type": "text/csv"},
    Conditions=[{"Content-Type": "text/csv"}, ["content-length-range", 1, MAX_FILE_BYTES]],
    ExpiresIn=UPLOAD_URL_TTL_S,
)
```

**Streaming reader.** `get_object()["Body"]` is wrapped in a `HashingReader` (`io.RawIOBase`: updates SHA-256 and `bytes_read` on every `readinto`), then `io.TextIOWrapper(encoding="utf-8-sig", errors="strict", newline="")`, then `csv.reader`. A `UnicodeDecodeError` is turned into `encoding_error` with the offset from `bytes_read`. Memory is bounded by the buffer sizes and one batch, not by the file (NFR-1).

**Two endpoints for MinIO.** The API signs URLs with the public endpoint (`S3_PUBLIC_ENDPOINT`, reachable from the browser) and the worker reads with the internal one (`S3_ENDPOINT`). Compose sets both.

## 11. Validation design

**Domain.** `domain.products.validate(raw: Sequence[str], header: Header, ctx: OrgContext) -> NormalizedRow | list[RowError]` is pure. `ctx` carries `allowed_currencies`. Price parsing uses a regex `^\d{1,8}(\.\d{1,2})?$` before `Decimal(...)`, so `1e3`, `NaN`, `1,5` and negative values are rejected by format, never by float conversion.

**Error codes.** File level: `header_invalid`, `encoding_error`, `empty_file`, `too_many_rows`. Row level: `required`, `invalid_format`, `out_of_range`, `too_long`, `invalid_currency`, `malformed_record`, `duplicate_key_in_file`.

**COPY.** Staging writes go through the psycopg 3 cursor under Django's connection (`cursor.cursor.copy("COPY imports_row (...) FROM STDIN")` with `write_row`), inside the batch's `transaction.atomic()`. **\[ADR-004\]**

**Duplicates.** Detecting them while streaming would need a set of every `sku` in memory (unbounded). Instead, `finalize_validation` runs one statement:

```sql
WITH ranked AS (
  SELECT row_number, sku, min(row_number) OVER (PARTITION BY sku) AS first_row
  FROM imports_row WHERE job_id = :job
)
-- insert duplicate_key_in_file errors for row_number > first_row, delete them from staging
```

Memory stays bounded and the result does not depend on batch boundaries or resumes (VR-11).

**Cancellation.** `cancel_requested` is checked by the batch's conditional `UPDATE`; when set, the batch rolls back, the job moves to `cancelled` and staging is purged.

## 12. Preview and apply design

**Diff.** One query joins staging with `catalog_product` on `(organization_id, sku)`:

```sql
SELECT count(*) FILTER (WHERE p.id IS NULL)                         AS to_insert,
       count(*) FILTER (WHERE p.id IS NOT NULL AND p.row_hash <> r.row_hash) AS to_update,
       count(*) FILTER (WHERE p.row_hash = r.row_hash)              AS unchanged
FROM imports_row r LEFT JOIN catalog_product p
  ON p.organization_id = :org AND p.sku = r.sku
WHERE r.job_id = :job;
```

`to_deactivate` (sync) is an anti-join in the other direction. This is the reconciliation check as a hash join in the database: linear in rows, no Python loops.

**Serialization.** `pg_advisory_xact_lock` keyed by the org (and dataset) is taken first in the apply transaction and released by commit or rollback, so a dead worker never leaves a lock behind. Lock order is fixed (advisory lock, then the job row, then products) to rule out deadlocks between applies (VR-6). **\[ADR-006\]**

**Why one transaction.** All-or-nothing is the product promise (FR-APP-2), and 1M upserts in one statement is a cost PostgreSQL handles; the benchmark (VR-16) checks it. The trade-off — the org's catalog rows being written are locked for the duration — is a documented limitation.

## 13. API design

Base path `/api/v1`. JSON; errors as problem details (`type`, `title`, `status`, `code`, `detail`, `request_id`). Cursor pagination on `(created_at, id)` or `(row_number)`; `limit` 1–200, default 50.

| Method and path | Role | Result |
| --- | --- | --- |
| `POST /auth/token`, `POST /auth/token/refresh` | — | JWT pair; refresh rotates |
| `GET /me` | any | user and memberships |
| `POST /orgs/{org}/uploads` | member | `201 {upload_id, url, fields, expires_at}` |
| `POST /orgs/{org}/imports` | member | `202 job`; `200` replay of an idempotent request |
| `GET /orgs/{org}/imports` | viewer | page of jobs |
| `GET /orgs/{org}/imports/{id}` | viewer | job |
| `GET /orgs/{org}/imports/{id}/errors` | viewer | page of errors |
| `GET /orgs/{org}/imports/{id}/error-report` | viewer | `{url, expires_at}` |
| `GET /orgs/{org}/imports/{id}/preview` | viewer | counts and sample |
| `POST /orgs/{org}/imports/{id}/apply` | member | `202 job` / `409 job_not_validated` |
| `POST /orgs/{org}/imports/{id}/cancel` | member | `202 job` / `409 job_not_cancellable` |
| `POST /orgs/{org}/imports/{id}/ws-ticket` | viewer | `{ticket, expires_at}` |
| `GET /orgs/{org}/products` | viewer | page of products |
| `GET /orgs/{org}/products/{sku}` | viewer | product |
| `GET /health/live`, `GET /health`, `GET /metrics` | — | section 15 |

OpenAPI 3.1 generated with drf-spectacular at `/api/schema/` and served at `/api/docs/`.

**Tenant scoping.** One base class, `OrgScopedViewSet`, resolves the org from the slug and the membership of `request.user` once per request, returns 404 for non-members, and builds every queryset from `organization=request.org`. Views never call `Model.objects` directly; an architecture test fails if a view under `api/` does. VR-7 is the runtime proof. **\[ADR-009\]**

## 14. WebSocket design

`ws/imports/{job_id}/?ticket=...`. Tickets are random 32-byte values stored in Redis (`sift:wst:<ticket>` → `user_id:job_id`, TTL 30 s) and consumed with `GETDEL`, so they work once. Tickets avoid putting a JWT in a URL, where proxies and logs keep it. **\[ADR-013\]**

Messages (server → client):

```
{"type": "snapshot", "seq": 0, "job": {...same as GET detail...}}
{"type": "progress", "seq": 7, "bytes_read": 41943040, "total_bytes": 104857600,
 "rows_read": 400000, "valid_rows": 392110, "invalid_rows": 7890}
{"type": "status",   "seq": 8, "status": "validated", "preview_counts": {...}}
```

`seq` comes from Redis `INCR sift:seq:<job_id>`, so it increases across worker processes and restarts. A client that joins late gets the snapshot from the database and ignores events with `seq` lower than one already seen. The worker publishes with `channel_layer.group_send` (`async_to_sync` in the task) after commit; a publish error is logged and ignored (FR-RT-4). **\[ADR-011\]**

## 15. Observability design

### 15.1 Logging

structlog JSON. Middleware binds `request_id`, `user_id`, `org_id`; the Celery `before_task_publish` signal copies `request_id` into headers and `task_prerun` binds it with `job_id`. File contents and cell values are never logged.

### 15.2 Metrics

| Metric | Type | Labels |
| --- | --- | --- |
| sift\_jobs\_total | counter | dataset, final\_status |
| sift\_rows\_validated\_total | counter | result=valid\|invalid |
| sift\_row\_errors\_total | counter | code |
| sift\_validation\_seconds, sift\_apply\_seconds | histogram | |
| sift\_batch\_seconds | histogram | |
| sift\_jobs\_rescued\_total | counter | from\_status |
| sift\_progress\_publish\_errors\_total | counter | |
| sift\_jobs\_by\_status | gauge | status (one `GROUP BY` at scrape time) |

### 15.3 Health

Shape: `{"status": "ok|degraded|down", "checks": {"db", "redis", "storage"}}`; probes run in parallel with short timeouts.

## 16. Project structure, run and CI

```
sift/
  sift/{accounts,catalog,imports,storage,common}/   # plus settings, asgi, urls, celery
  tools/{generate.py,demo.py,bench.py}
  tests/{unit,property,integration,chaos}/
  docs/srs-sdd.md  docs/adr/  docs/benchmark.md
  docker-compose.yml  Dockerfile  Makefile  pyproject.toml  uv.lock
  .github/workflows/ci.yml
```

**Run.** `docker compose up --build` starts postgres, redis, minio, minio-init, migrate (with `seed_demo`: org `acme`, user `demo@sift.local`), api, worker, beat. `docker compose --profile demo run --rm demo` generates a file, uploads it, follows the WebSocket, applies and verifies against the oracle.

**Generator.** `python -m tools.generate --rows N --error-rate r --dup-rate d --seed s --out f.csv` writes the file and `f.oracle.json` (expected `total_rows`, `valid_rows`, `error_counts`, `to_insert`). It does not import `sift`, so it checks the service as a black box.

**CI (GitHub Actions).**

| Job | Steps |
| --- | --- |
| lint | `ruff check`, `ruff format --check`, domain import rule, `makemigrations --check` |
| types | `mypy` |
| test | service containers postgres, redis, minio; `pytest -m "not chaos"` with coverage gate |
| chaos | compose services; `pytest -m chaos` (VR-4, VR-5) |
| smoke | `docker compose up --build -d`; demo profile with a 50k-row file; `verify` |

The benchmark (VR-16) runs locally with `make bench` and writes `docs/benchmark.md`; CI does not gate on timing.

## 17. Test strategy and expected limitations

### 17.1 How the hard tests work

- **Resume property (VR-2).** The batch committer is a port; a fake raises after batch *k* (drawn by Hypothesis), then validation is called again with the same job. Runs against a real PostgreSQL with a small `BATCH_SIZE` (7) so a few hundred records cross many boundaries.
- **Worker kill (VR-4, VR-5).** A real worker subprocess with a test hook that blocks after the *n*-th batch commit (or inside the apply transaction) and signals through a file; the test sends SIGKILL, starts a fresh worker, back-dates `heartbeat_at` / `lease_until` instead of sleeping, and asserts the oracle counts, `attempts = 2` and, for VR-4, that `checkpoint_row` was never reset.
- **Concurrent applies (VR-6).** Two threads released by a barrier call `apply_job` for two jobs of one org; a third org's apply runs at the same time and must finish first.
- **Isolation (VR-7).** The test walks `get_resolver().url_patterns`, fills path parameters with ids from org A, and calls each route as a user of org B with each role.
- **Query budget (VR-8).** `django_assert_num_queries` with page sizes 5 and 50.
- **Memory (VR-16).** The benchmark samples the worker's RSS with `psutil` every 100 ms during the job.

### 17.2 Limitations (to be copied into the README and updated after measuring)

- CSV only, one dataset (`products`), rules defined in code; per-org configuration is limited to allowed currencies.
- Apply holds row locks on the org's affected products for the length of one transaction; a very large apply delays concurrent writes to those rows.
- Resume re-reads the file from the start to keep the SHA-256 complete.
- Progress events are best effort; the REST detail is the source of truth.
- Single PostgreSQL primary; no failover.
- MinIO stands in for S3; no real AWS deployment, no malware scanning of uploads.
- Throughput and memory numbers come from one laptop and are indicative only.

## 18. Planned ADRs

Each ADR is written in `docs/adr/NNN-title.md` (template: Status, Context, Decision, Consequences, Alternatives considered) during the phase listed, so it can record what the implementation showed. Until then the "Proposed" column applies.

| ADR | Question | Proposed | Alternatives | Phase |
| --- | --- | --- | --- | --- |
| 001 | Framework for this project | Django + DRF + Channels | FastAPI + SQLAlchemy (no bundled admin, migrations or WebSocket layer) | F0 |
| 002 | How files reach the system | Presigned POST direct to object storage with size and key policy | Multipart upload through Django; presigned PUT (no size limit) | F2 |
| 003 | Where valid rows wait before apply | Staging table per job, set-based apply | Apply per batch (no all-or-nothing); temp tables (lost on reconnect) | F3 |
| 004 | How rows are written to staging | `COPY` through psycopg 3; logged vs `UNLOGGED` decided by measurement | `bulk_create`; row-by-row ORM | F3/F7 |
| 005 | How validation survives a crash | Batch + errors + checkpoint in one transaction; resume re-reads the file | Restart from scratch; byte-offset seek (unsafe with quoted newlines, breaks the hash) | F3 |
| 006 | How apply stays atomic and ordered | One transaction with a per-org advisory transaction lock, then job row `FOR UPDATE` | Per-batch commits; `SELECT ... FOR UPDATE` on the org row; Redis lock | F4 |
| 007 | Broker | Redis (also channel layer and tickets) **\[DECISION D1\]** | RabbitMQ (one more service; isolates the broker from cache failures) | F0 |
| 008 | Recovering crashed jobs | Heartbeat/lease + `run_token` + Beat rescuer; `acks_late` kept as a second net | Broker redelivery only (Redis `visibility_timeout` is coarse) | F6 |
| 009 | Tenant isolation | Scoped querysets from one base viewset + route-walking test | PostgreSQL RLS; `django-tenants` schemas | F1 |
| 010 | Code structure in Django | Apps with services/selectors and a pure `domain` package | Fat models; logic in serializers | F0 |
| 011 | Progress delivery | Throttled best-effort `group_send` after commit; snapshot on connect; Redis `seq` | Server-sent events; client polling only | F5 |
| 012 | Import idempotency | `Idempotency-Key` on create + hash-based upsert; file hash only warns | Block identical files by hash (prevents intentional re-imports) | F2/F4 |
| 013 | Auth for API and WebSocket | simplejwt for REST; single-use Redis ticket for WebSocket **\[DECISION D4\]** | JWT in query string; session cookies | F1/F5 |
| 014 | Invalid rows policy | Reject above an error-rate threshold, else apply valid rows **\[DECISION D2\]** | Strict all-or-nothing; always apply valid rows | F3 |

## 19. Open decisions

| # | Decision | Proposed | Why |
| --- | --- | --- | --- |
| D1 | Broker: Redis or RabbitMQ | Redis | Channels already needs Redis; one less service; the rescuer covers Redis's coarse redelivery. |
| D2 | Policy for invalid rows | Reject if invalid > 5%; otherwise apply valid rows and report the rest | Mirrors real back-office imports; the threshold is a parameter. |
| D3 | Default flow | Preview then explicit apply; `auto_apply` opt-in | The preview is what makes the diff visible; automation stays possible. |
| D4 | Authentication | simplejwt (access 15 min, refresh 7 d rotated) + WebSocket tickets | Widely used with DRF; no tokens in URLs. |
| D5 | Formats in the MVP | CSV only; XLSX in backlog (openpyxl read-only) | XLSX cannot be streamed from S3 without random access (zip); it needs its own design. |
| D6 | Limits | 200 MiB per file, 2,000,000 records | Enough to prove NFR-1 with margin; easy to raise. |
| D7 | `sync` mode in the MVP | Should (built on day 8 if on schedule) | Adds the anti-join and VR-18; not needed for the core claims. |
| D8 | Django version | 6.1, if DRF, Channels, drf-spectacular and simplejwt declare support at bootstrap; otherwise 5.2 LTS | Checked in F0, recorded in ADR-001. |
| D9 | Code structure | Services/selectors + pure domain | Testable rules and transactions in one place. |
| D10 | ASGI server | uvicorn (one process for HTTP and WebSocket) | Serves HTTP and WebSocket in one process; Daphne only if Channels needs it. |
| D11 | Batch size | 5,000 records (tuned in F7) | Balances commit overhead and lost work on crash. |
| D12 | Name and repo | `sift` (`kaulinmindiola/sift`) | Short; describes filtering good rows from bad. |

## 20. Plan (two weeks)

| Phase | Day | Content | Exit gate |
| --- | --- | --- | --- |
| F0 | 1 | Repo, uv, Django project, apps, settings from env, compose (postgres, redis, minio, migrate), CI lint/types/test, ADR-001/007/010 | `docker compose up` green; CI green |
| F1 | 2 | Custom user, orgs, memberships, JWT, `OrgScopedViewSet`, problem+json, request id, `seed_demo`; ADR-009/013 | VR-7 green on the routes that exist; VR-21 for auth |
| F2 | 3 | Uploads with presigned POST, job creation with idempotency, state machine in `domain`; ADR-002/012 | VR-12, VR-17, VR-20 |
| F3 | 4–5 | Streaming reader, record validation, `COPY` batches, checkpoint, duplicates, error rate, error report; ADR-003/004/005/014 | VR-1, VR-2, VR-9, VR-10, VR-11, VR-15; VR-21 for jobs and errors |
| F4 | 6 | Preview, apply with advisory lock, re-import idempotency | VR-3, VR-6, VR-19 |
| F5 | 7 | Channels consumer, tickets, progress events, demo page (Should); ADR-011 | VR-14 |
| F6 | 8 | Rescuer, cancel, housekeeping, chaos tests; `sync` mode if on schedule; ADR-008 | VR-4, VR-5, VR-13, VR-22, (VR-18) |
| F7 | 9 | Generator + oracle, demo profile, smoke job, query budget, metrics, benchmark | VR-8, VR-16, VR-23; NFR-1/2 measured |
| F8 | 10 | README (evidence table, measurements, limitations), ADR review, SDD v0.2 with implementation notes, tag v1.0.0 | Every Must requirement traced to a passing test |

Within each phase the failure and property tests are written first. Backlog after v1.0.0: XLSX (D5), `MAX_ACTIVE_JOBS_PER_ORG` (FR-JOB-6), per-org rule configuration, a second dataset.
