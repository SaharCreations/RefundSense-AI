"""Real DSN construction checks: special characters and TLS options remain intact."""

import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

spec = importlib.util.spec_from_file_location(
    "entry", Path(__file__).resolve().parents[1] / "scripts/container_entrypoint.py"
)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


def test_secrets_with_reserved_characters_and_tls(tmp_path):
    secret = tmp_path / "password"
    secret.write_text("pass@/?#:'with spaces\n")
    result = urlsplit(
        entry.database_url(
            {
                "PGHOST": "db.example",
                "PGUSER": "user@example",
                "PGDATABASE": "demo/name",
                "PGPASSWORD_FILE": str(secret),
                "PGSSLMODE": "verify-full",
                "PGSSLROOTCERT": "/certs/ca.pem",
            }
        )
    )
    assert unquote(result.password) == "pass@/?#:'with spaces"
    assert unquote(result.username) == "user@example"
    assert unquote(result.path) == "/demo/name"
    assert parse_qs(result.query) == {"sslmode": ["verify-full"], "sslrootcert": ["/certs/ca.pem"]}


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"PGHOST": "evil@host", "PGPASSWORD": "secret"},
        {"PGHOST": "db", "PGPORT": "5432/path", "PGPASSWORD": "secret"},
    ],
)
def test_missing_or_invalid_credentials_are_not_guessed(env):
    with pytest.raises(ValueError):
        entry.database_url(env)


def test_explicit_dsn_retained_for_existing_local_setup():
    assert (
        entry.database_url({"DATABASE_URL": "postgresql://existing/database"})
        == "postgresql://existing/database"
    )
