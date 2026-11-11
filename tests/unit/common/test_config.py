from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from sift.common.config import ImportSettings, get_import_settings


def test_defaults_match_the_srs() -> None:
    settings = ImportSettings()

    assert settings.max_file_bytes == 200 * 1024 * 1024
    assert settings.max_rows == 2_000_000
    assert settings.batch_size == 5_000
    assert settings.error_rate_threshold == Decimal("0.05")
    assert settings.max_stored_errors == 10_000
    assert settings.upload_url_ttl_s == 600
    assert settings.upload_expiry_h == 24
    assert settings.preview_ttl_h == 24
    assert settings.report_retention_d == 7
    assert settings.rescue_interval_s == 30
    assert settings.heartbeat_stale_s == 120
    assert settings.max_attempts == 3
    assert settings.progress_min_interval_ms == 500
    assert settings.ws_ticket_ttl_s == 30


def test_from_env_reads_overrides_and_keeps_other_defaults() -> None:
    settings = ImportSettings.from_env({"BATCH_SIZE": "7", "ERROR_RATE_THRESHOLD": "0.1"})

    assert settings.batch_size == 7
    assert settings.error_rate_threshold == Decimal("0.1")
    assert settings.max_rows == 2_000_000


def test_from_env_with_empty_environment_equals_defaults() -> None:
    assert ImportSettings.from_env({}) == ImportSettings()


@pytest.mark.parametrize(
    "overrides",
    [
        {"batch_size": 0},
        {"max_rows": -1},
        {"error_rate_threshold": Decimal("1.5")},
        {"error_rate_threshold": Decimal("-0.01")},
    ],
)
def test_invalid_values_are_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises(ImproperlyConfigured):
        ImportSettings(**overrides)


def test_settings_are_immutable() -> None:
    settings = ImportSettings()
    with pytest.raises(FrozenInstanceError):
        settings.batch_size = 1  # type: ignore[misc]


def test_django_settings_expose_import_settings() -> None:
    assert isinstance(get_import_settings(), ImportSettings)


def test_get_import_settings_rejects_a_wrong_type(settings: Any) -> None:
    settings.IMPORT_SETTINGS = {"batch_size": 5000}
    with pytest.raises(ImproperlyConfigured):
        get_import_settings()
