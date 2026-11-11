"""Typed access to environment variables.

Settings read configuration only through these helpers, so a missing or
malformed value stops the process at start-up with a clear message. Error
messages name the variable but never echo its value (FR-SEC-1).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _raw(name: str, environ: Mapping[str, str] | None) -> str | None:
    source = os.environ if environ is None else environ
    value = source.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _missing(name: str) -> ImproperlyConfigured:
    return ImproperlyConfigured(f"Environment variable {name} is required but not set.")


def env_str(
    name: str, default: str | None = None, *, environ: Mapping[str, str] | None = None
) -> str:
    """Return the variable as text; without a default the variable is required."""
    value = _raw(name, environ)
    if value is not None:
        return value
    if default is None:
        raise _missing(name)
    return default


def env_int(
    name: str, default: int | None = None, *, environ: Mapping[str, str] | None = None
) -> int:
    value = _raw(name, environ)
    if value is None:
        if default is None:
            raise _missing(name)
        return default
    try:
        return int(value)
    except ValueError:
        raise ImproperlyConfigured(f"Environment variable {name} must be an integer.") from None


def env_bool(
    name: str, default: bool | None = None, *, environ: Mapping[str, str] | None = None
) -> bool:
    value = _raw(name, environ)
    if value is None:
        if default is None:
            raise _missing(name)
        return default
    lowered = value.lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ImproperlyConfigured(
        f"Environment variable {name} must be one of: {', '.join(sorted(_TRUE | _FALSE))}."
    )


def env_list(
    name: str, default: list[str] | None = None, *, environ: Mapping[str, str] | None = None
) -> list[str]:
    """Return a comma-separated variable as a list, without blanks."""
    value = _raw(name, environ)
    if value is None:
        if default is None:
            raise _missing(name)
        return list(default)
    return [item.strip() for item in value.split(",") if item.strip()]


def env_decimal(
    name: str, default: Decimal | None = None, *, environ: Mapping[str, str] | None = None
) -> Decimal:
    value = _raw(name, environ)
    if value is None:
        if default is None:
            raise _missing(name)
        return default
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        raise ImproperlyConfigured(f"Environment variable {name} must be a decimal.") from None
    if not parsed.is_finite():
        raise ImproperlyConfigured(f"Environment variable {name} must be a finite decimal.")
    return parsed


def load_env_file(path: Path, environ: MutableMapping[str, str] | None = None) -> None:
    """Load ``KEY=VALUE`` lines from ``path`` into the environment.

    Variables that are already set win over the file, so the process
    environment (compose, CI) always takes precedence. A missing file is not
    an error. Supports comments, blank lines, an optional ``export`` prefix and
    values wrapped in single or double quotes.
    """
    target: MutableMapping[str, str] = os.environ if environ is None else environ
    if not path.is_file():
        return
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped.removeprefix("export ").lstrip()
        key, separator, value = stripped.partition("=")
        key = key.strip()
        if not separator or not key.isidentifier():
            raise ImproperlyConfigured(f"{path.name}:{lineno}: expected KEY=VALUE.")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        target.setdefault(key, value)
