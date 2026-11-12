# ADR-001: Django 5.2 LTS with DRF and Channels

- **Status:** Accepted
- **Date:** 2026-11-12
- **Phase:** F0
- **Related:** D8, D10, NFR-9

## Context

Sift needs a REST API with authentication and OpenAPI, a relational schema with
migrations, an admin for organizations and users (FR-ACC-6), WebSocket progress
(FR-RT) and background jobs. All of it has to run from one code base: the API,
the Celery worker and beat share models and services.

D8 left the Django version open: use 6.1 if Django REST framework, Channels,
drf-spectacular and djangorestframework-simplejwt all declare support for it at
bootstrap; otherwise use 5.2 LTS.

## Decision

Django + Django REST framework + Channels, served by uvicorn as one ASGI
process for HTTP and WebSocket (D10). The project has no `wsgi.py`.

Django is pinned to the 5.2 LTS series (`Django>=5.2,<5.3`). The D8 check on
2026-11-11 found:

| Package | Latest | Declared Django support |
| --- | --- | --- |
| djangorestframework | 3.18 | adds 6.1 |
| drf-spectacular | 0.30.0 | up to 6.0 |
| djangorestframework-simplejwt | 5.5.1 | up to 6.0 |
| channels | 4.3.2 | 5.2 and later |

Two of the four packages do not declare 6.1, so the rule selects 5.2 LTS.
The resolved versions live in `uv.lock` (Django 5.2.19, DRF 3.18.3,
drf-spectacular 0.30.0, simplejwt 5.5.1, Channels 4.3.2).

## Consequences

- Every dependency runs on a Django version it officially supports, and 5.2
  is a long-term support release.
- Features new in 6.0/6.1 (for example model field fetch modes) are not
  available. Nothing in the SDD depends on them.
- Moving to 6.1 later is one line in `pyproject.toml` plus `uv lock`, once the
  four packages declare support.

## Alternatives considered

- **Django 6.1 regardless of declared support.** Rejected: an undeclared
  combination is untested by the libraries' own CI, and the SDD rule exists to
  avoid debugging other people's compatibility.
- **FastAPI + SQLAlchemy.** Rejected: no bundled admin, migrations or WebSocket
  channel layer; each would be assembled by hand for no gain in this scope.

## What the implementation showed

To be completed when F0 closes.
