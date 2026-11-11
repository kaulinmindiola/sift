"""Import parameters grouped in one immutable object.

Services receive an ``ImportSettings`` instead of reading Django settings, so a
test can pass ``ImportSettings(batch_size=7)`` without touching global state.
Each field maps to the environment variable with the same name in upper case.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from decimal import Decimal
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from sift.common.env import env_decimal, env_int


@dataclass(frozen=True, slots=True)
class ImportSettings:
    # Limits (D6)
    max_file_bytes: int = 200 * 1024 * 1024
    max_rows: int = 2_000_000
    # Validation (D2, D11)
    batch_size: int = 5_000
    error_rate_threshold: Decimal = Decimal("0.05")
    max_stored_errors: int = 10_000
    # Uploads, previews and reports
    upload_url_ttl_s: int = 600
    upload_expiry_h: int = 24
    preview_ttl_h: int = 24
    report_retention_d: int = 7
    # Recovery; apply_lease_s is fixed with benchmark data in F7
    rescue_interval_s: int = 30
    heartbeat_stale_s: int = 120
    apply_lease_s: int = 600
    max_attempts: int = 3
    # Live progress
    progress_min_interval_ms: int = 500
    ws_ticket_ttl_s: int = 30

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, int) and value <= 0:
                raise ImproperlyConfigured(f"{field.name} must be a positive integer.")
        if not Decimal(0) <= self.error_rate_threshold <= Decimal(1):
            raise ImproperlyConfigured("error_rate_threshold must be between 0 and 1.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ImportSettings:
        defaults = cls()
        values: dict[str, Any] = {}
        for field in fields(cls):
            default = getattr(defaults, field.name)
            variable = field.name.upper()
            if isinstance(default, Decimal):
                values[field.name] = env_decimal(variable, default, environ=environ)
            else:
                values[field.name] = env_int(variable, default, environ=environ)
        return cls(**values)


def get_import_settings() -> ImportSettings:
    """Return the process-wide settings built in ``sift.settings``."""
    from django.conf import settings

    value = settings.IMPORT_SETTINGS
    if not isinstance(value, ImportSettings):
        raise ImproperlyConfigured("settings.IMPORT_SETTINGS must be an ImportSettings.")
    return value
