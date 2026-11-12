"""FR-ACC-1: users log in with their email address."""

import pytest
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.db import IntegrityError

from sift.accounts.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_project_uses_the_email_user_model() -> None:
    assert settings.AUTH_USER_MODEL == "accounts.User"
    assert get_user_model() is User
    assert User._meta.db_table == "accounts_user"


def test_create_user_normalizes_email_and_hashes_the_password() -> None:
    user = User.objects.create_user("  Ana@Example.COM ", "s3cret-pass")

    assert user.email == "ana@example.com"
    assert user.password != "s3cret-pass"
    assert user.check_password("s3cret-pass")
    assert user.is_active
    assert not user.is_staff
    assert not user.is_superuser


def test_create_user_requires_an_email() -> None:
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user("   ", "s3cret-pass")


def test_create_superuser_sets_staff_and_superuser_flags() -> None:
    admin = User.objects.create_superuser("root@sift.local", "s3cret-pass")

    assert admin.is_staff
    assert admin.is_superuser


@pytest.mark.parametrize("flag", ["is_staff", "is_superuser"])
def test_create_superuser_rejects_disabled_flags(flag: str) -> None:
    with pytest.raises(ValueError, match=flag):
        User.objects.create_superuser("root@sift.local", "s3cret-pass", **{flag: False})


def test_email_is_unique_regardless_of_case() -> None:
    User.objects.create_user("ana@example.com", "s3cret-pass")

    with pytest.raises(IntegrityError):
        User.objects.create_user("ANA@example.com", "other-pass")


def test_authenticate_by_email_ignores_case() -> None:
    User.objects.create_user("ana@example.com", "s3cret-pass")

    assert authenticate(username="ANA@Example.com", password="s3cret-pass") is not None
    assert authenticate(username="ana@example.com", password="wrong") is None


def test_inactive_users_cannot_authenticate() -> None:
    User.objects.create_user("ana@example.com", "s3cret-pass", is_active=False)

    assert authenticate(username="ana@example.com", password="s3cret-pass") is None


def test_display_names_fall_back_to_the_email() -> None:
    named = User(email="ana@example.com", full_name="Ana Maria Ruiz")
    unnamed = User(email="bob@example.com")

    assert str(named) == "ana@example.com"
    assert named.get_full_name() == "Ana Maria Ruiz"
    assert named.get_short_name() == "Ana"
    assert unnamed.get_full_name() == "bob@example.com"
    assert unnamed.get_short_name() == "bob@example.com"
