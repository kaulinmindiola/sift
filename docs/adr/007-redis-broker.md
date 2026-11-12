# ADR-007: Redis as Celery broker, channel layer and ticket store

- **Status:** Accepted
- **Date:** 2026-11-12
- **Phase:** F0 (recovery details in F6, ADR-008)
- **Related:** D1, NFR-3, FR-REC-1..3

## Context

Celery needs a broker. Channels needs a channel layer for `group_send` from the
worker to WebSocket consumers (F5), and the WebSocket tickets need a store with
TTL and atomic consume (F5). Each extra service makes `docker compose up` slower
and is one more thing to fail.

Redis as a broker redelivers unacknowledged messages only after its
`visibility_timeout`, which is coarse; a worker that dies mid-task is not
noticed quickly by the broker alone.

## Decision

One Redis 7 instance serves as Celery broker, Channels layer and ticket store.
Celery is configured so that delivery is at-least-once and safe to repeat:

- `task_acks_late = True` and `task_reject_on_worker_lost = True`: a message is
  acknowledged only after the task finishes, and a task whose worker dies is
  returned to the queue.
- `worker_prefetch_multiplier = 1`: a worker never holds messages it is not
  running.
- JSON serialization only; results are ignored (job state lives in PostgreSQL).

Correctness does not depend on the broker: every task claims its job with a
compare-and-set on `(status, run_token)` (FR-REC-3), and the beat rescuer
re-enqueues stalled jobs (FR-REC-2, ADR-008).

## Consequences

- One service fewer than with RabbitMQ; compose and CI start faster.
- A Redis outage stops the broker, the channel layer and ticket issuing at
  once. The API reports it as `degraded` in `/health` (F2) and job state stays
  safe in PostgreSQL.
- Duplicate deliveries are possible and are handled by the claim, not prevented.

## Alternatives considered

- **RabbitMQ as broker, Redis for the rest.** Better redelivery semantics and
  isolation of the broker from cache load, at the cost of one more service. The
  run_token claim and the rescuer make the weaker Redis semantics sufficient.
- **Broker redelivery as the only recovery mechanism.** Rejected: the
  visibility timeout is too coarse and cannot detect a slow-but-alive worker.

## What the implementation showed

To be completed when F6 closes (rescuer and chaos tests).
