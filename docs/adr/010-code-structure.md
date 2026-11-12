# ADR-010: Apps with services and selectors around a pure domain package

- **Status:** Accepted
- **Date:** 2026-11-12
- **Phase:** F0
- **Related:** D9, NFR-10, NFR-7

## Context

The import rules (header resolution, record validation, row hashing, the job
state machine) are the core of Sift and need property-based tests that run in
milliseconds (VR-1, VR-2, VR-17). Transactions, SQL and side effects (storage,
broker, WebSocket) must stay in one place per use case so their guarantees can
be reasoned about.

## Decision

- **Django apps by bounded area:** `accounts`, `catalog`, `imports`, `storage`
  and `common`, each with an explicit `AppConfig.label` and explicit
  `Meta.db_table` names (SDD section 8).
- **`imports/domain`** is pure Python: standard library and its own modules
  only. An `ast`-based architecture test (`tests/architecture/test_domain_purity.py`)
  fails CI if it imports Django, DRF, Celery, Channels, boto3, psycopg, redis or
  any other `sift` package.
- **Services** own use cases and transactions; **selectors** own read queries;
  views and Celery tasks are thin and call services. Hand-written SQL lives
  only in `imports/staging.py`.
- **One settings module** read from the environment through typed helpers
  (`sift/common/env.py`); secrets have no default and the process refuses to
  start without them. Import parameters are an immutable `ImportSettings`
  injected into services, so tests override them without touching globals.
- mypy runs strict on `imports.domain` and `imports.services`.

## Consequences

- Business rules are tested without a database, broker or Django setup.
- More modules than a fat-model design, and a convention to keep: queries in
  selectors, writes in services. The architecture tests enforce the parts that
  can be checked mechanically (domain purity now; view scoping in F1).
- No `settings/base|dev|prod` split: there is no production environment in
  scope, and tests adjust settings through fixtures and `ImportSettings`.

## Alternatives considered

- **Fat models.** Rejected: rules tied to the ORM need a database to test and
  spread transactions across model methods.
- **Logic in serializers.** Rejected: couples validation of CSV records to the
  HTTP layer, while most of it runs inside Celery tasks.
- **import-linter for the purity rule.** Rejected: one more dependency for a
  check that 60 lines of `ast` cover, including a test of the checker itself.

## What the implementation showed

F0: the purity test proved itself by failing on a deliberately added
`from django.db import models` in the domain package. Reviewed again in F8.
