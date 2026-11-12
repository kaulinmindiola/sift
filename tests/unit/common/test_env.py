from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from sift.common.env import env_bool, env_decimal, env_int, env_list, env_str, load_env_file


def test_env_str_returns_the_stripped_value() -> None:
    assert env_str("NAME", environ={"NAME": "  sift  "}) == "sift"


def test_env_str_uses_the_default_when_missing_or_blank() -> None:
    assert env_str("NAME", "fallback", environ={}) == "fallback"
    assert env_str("NAME", "fallback", environ={"NAME": "   "}) == "fallback"


def test_required_variable_fails_fast_and_names_it() -> None:
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        env_str("DJANGO_SECRET_KEY", environ={})


def test_error_messages_never_echo_the_value() -> None:
    with pytest.raises(ImproperlyConfigured) as error:
        env_int("DB_PORT", environ={"DB_PORT": "not-a-secret-but-hidden"})
    assert "not-a-secret-but-hidden" not in str(error.value)


def test_env_int_parses_integers() -> None:
    assert env_int("N", environ={"N": "42"}) == 42
    assert env_int("N", 7, environ={}) == 7


def test_env_int_rejects_garbage() -> None:
    with pytest.raises(ImproperlyConfigured, match="N must be an integer"):
        env_int("N", environ={"N": "4x"})


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        ("0", False),
        ("False", False),
        ("no", False),
        ("off", False),
    ],
)
def test_env_bool_accepts_common_spellings(raw: str, expected: bool) -> None:
    assert env_bool("FLAG", environ={"FLAG": raw}) is expected


def test_env_bool_rejects_unknown_values() -> None:
    with pytest.raises(ImproperlyConfigured, match="FLAG"):
        env_bool("FLAG", environ={"FLAG": "maybe"})


def test_env_list_splits_on_commas_and_drops_blanks() -> None:
    assert env_list("HOSTS", environ={"HOSTS": "a, b,,c "}) == ["a", "b", "c"]
    assert env_list("HOSTS", ["x"], environ={}) == ["x"]


def test_env_decimal_parses_exact_values() -> None:
    assert env_decimal("RATE", environ={"RATE": "0.05"}) == Decimal("0.05")


@pytest.mark.parametrize("raw", ["abc", "NaN", "Infinity"])
def test_env_decimal_rejects_invalid_or_non_finite(raw: str) -> None:
    with pytest.raises(ImproperlyConfigured, match="RATE"):
        env_decimal("RATE", environ={"RATE": raw})


def test_load_env_file_sets_only_missing_keys(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"# comment\n\nA=1\nexport B=\"two words\"\nC='x'\r\nEXISTING=from-file\n")
    environ = {"EXISTING": "from-process"}

    load_env_file(env_file, environ)

    assert environ == {"EXISTING": "from-process", "A": "1", "B": "two words", "C": "x"}


def test_load_env_file_ignores_a_missing_file(tmp_path: Path) -> None:
    environ: dict[str, str] = {}
    load_env_file(tmp_path / "absent.env", environ)
    assert environ == {}


def test_load_env_file_rejects_malformed_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_bytes(b"NOT A PAIR\n")
    with pytest.raises(ImproperlyConfigured, match=r"\.env:1"):
        load_env_file(env_file, {})
