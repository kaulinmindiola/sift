# ADR-015: Chainguard MinIO pinned by digest, bucket created by ensure_bucket

- **Status:** Accepted
- **Date:** 2026-11-12
- **Phase:** F0
- **Related:** NFR-8, FR-UPL-3, implementation plan H13/H14

## Context

The SDD uses MinIO as local S3-compatible storage, with a `minio-init` service
that creates the bucket with `mc mb`. When F0 started:

- the `minio/minio` and `minio/mc` images were no longer published, and the
  images on quay.io required an account, so `docker compose up --build`
  (NFR-8) could not work as designed;
- Chainguard publishes a free MinIO image, `cgr.dev/chainguard/minio`, but only
  under a moving `latest` tag. It is distroless: it runs as a non-root user and
  has no shell, `curl` or `wget`, so neither `mc mb` nor an HTTP healthcheck
  can run inside it.

## Decision

- Compose uses `cgr.dev/chainguard/minio@sha256:786cb11d340b1a657de8dc899560e36e1d1fb371d3d6f3eb6c903a0bb0cec714`,
  pinned by digest for reproducible starts.
- The bucket is created by the Django command `manage.py ensure_bucket`, run by
  the one-shot `migrate` service after `migrate`. It is idempotent, removes any
  bucket policy (the bucket must never allow anonymous reads) and, with
  `--wait 60`, retries while MinIO is starting. This replaces both `minio-init`
  and a MinIO healthcheck.
- CI starts PostgreSQL, Redis and MinIO with the same `docker-compose.yml`, so
  local development and CI share one source of image versions and the digest.
- Application code talks to storage only through boto3 with path-style
  addressing, so any S3-compatible server can replace MinIO.

## Consequences

- `docker compose up --build` works from a fresh clone without an account on
  any registry.
- The digest is renewed by hand (a `build(docker)` commit) when needed; there
  are no version tags to follow.
- MinIO has no compose healthcheck; services that need storage depend on
  `migrate` completing, which only happens once storage answers.
- The bucket logic is covered by integration tests against a real MinIO,
  including an anonymous GET that must return 403.

## Alternatives considered

- **`pgsty/silo` (community fork of MinIO).** Viable drop-in replacement with
  version tags; kept as the fallback if the Chainguard image changes or
  disappears.
- **RustFS or Garage.** S3-compatible, but the POST-policy behaviour that
  presigned uploads rely on (ADR-002, VR-20) would need to be verified first.
- **Building MinIO from source.** Reproducible but adds a build step and
  minutes to every clean start.
- **Keeping `minio-init` with a third-party `mc` image.** Rejected: another
  external image to trust and pin, and the logic would not be testable in the
  project's test suite.

## What the implementation showed

F0: the pinned image, `ensure_bucket --wait 60` and the 403 check worked both
on Docker Desktop for Windows and on the GitHub Actions Linux runner.
