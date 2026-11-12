"""NFR-10: the domain package stays pure Python.

``sift/imports/domain`` holds the business rules that Hypothesis tests run in
milliseconds. It may import the standard library and its own modules only;
anything that needs Django, a broker, storage or a database belongs in services.
The check reads the source with ``ast`` instead of importing it, so a forbidden
import is caught even if it would only run at type-checking time.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_DIR = REPO_ROOT / "sift" / "imports" / "domain"
DOMAIN_PACKAGE = "sift.imports.domain"

FORBIDDEN_ROOTS = frozenset(
    {
        "boto3",
        "botocore",
        "celery",
        "channels",
        "channels_redis",
        "django",
        "drf_spectacular",
        "kombu",
        "psycopg",
        "psycopg2",
        "redis",
        "rest_framework",
        "rest_framework_simplejwt",
    }
)


def _is_forbidden(module: str) -> bool:
    root = module.split(".", 1)[0]
    if root in FORBIDDEN_ROOTS:
        return True
    if root == "sift":
        return not (module == DOMAIN_PACKAGE or module.startswith(f"{DOMAIN_PACKAGE}."))
    return False


def forbidden_imports(source: str, filename: str = "<string>") -> list[str]:
    """Return one ``file:line imports module`` entry per forbidden import."""
    violations: list[str] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        else:
            # Relative imports (``from . import x``) stay inside the package.
            continue
        violations.extend(
            f"{filename}:{node.lineno} imports {module}"
            for module in modules
            if _is_forbidden(module)
        )
    return violations


def test_domain_package_exists() -> None:
    assert (DOMAIN_DIR / "__init__.py").is_file(), f"Domain package not found at {DOMAIN_DIR}"


def test_domain_modules_import_only_stdlib_and_domain() -> None:
    violations: list[str] = []
    for path in sorted(DOMAIN_DIR.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        violations.extend(forbidden_imports(path.read_text(encoding="utf-8"), relative))

    assert violations == [], "Domain must stay pure (NFR-10):\n" + "\n".join(violations)


@pytest.mark.parametrize(
    "source",
    [
        "import django",
        "from django.db import models",
        "import boto3.session",
        "from celery import shared_task",
        "import redis",
        "from psycopg import sql",
        "from rest_framework import serializers",
        "from sift.common.config import ImportSettings",
        "import sift.storage",
    ],
)
def test_checker_flags_forbidden_imports(source: str) -> None:
    assert forbidden_imports(source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from decimal import Decimal",
        "import csv, hashlib",
        "from sift.imports.domain.types import Header",
        "import sift.imports.domain",
        "from . import types",
        "from .errors import RowErrorCode",
    ],
)
def test_checker_allows_stdlib_and_domain_imports(source: str) -> None:
    assert forbidden_imports(source) == []
