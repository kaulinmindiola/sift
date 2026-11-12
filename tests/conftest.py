"""Fixtures shared by the whole suite."""

from collections.abc import Iterator

import pytest
from django.test import override_settings


@pytest.fixture(autouse=True)
def _fast_password_hashing() -> Iterator[None]:
    """PBKDF2 with production iterations makes every created user take ~1 s."""
    with override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"]):
        yield
