"""FR-OBS-2: liveness endpoint.

These tests are deliberately not marked ``django_db``: pytest-django blocks
database access in them, so they also prove that liveness never queries it.
"""

from django.test import Client
from django.urls import reverse


def test_liveness_returns_ok_without_touching_the_database(client: Client) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json() == {"status": "ok"}


def test_liveness_answers_head_requests(client: Client) -> None:
    assert client.head("/health/live").status_code == 200


def test_liveness_rejects_unsafe_methods(client: Client) -> None:
    assert client.post("/health/live").status_code == 405


def test_liveness_route_is_named() -> None:
    assert reverse("health-live") == "/health/live"
