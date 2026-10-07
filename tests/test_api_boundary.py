"""Boundary failure behavior without a running database."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from refundguard.api import Settings, create_app

ROOT = Path(__file__).resolve().parents[1]


def test_api_requires_explicit_database_configuration(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Settings.from_env()


def test_database_errors_do_not_expose_connection_credentials():
    secret = "NEVER_EXPOSE_TEST_PASSWORD"
    app = create_app(
        Settings(
            f"postgresql://example:{secret}@127.0.0.1:1/example",
            ROOT / "data",
            ROOT / "config/demo_ruleset.json",
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "database_unavailable"}}
        assert secret not in response.text and "postgresql" not in response.text
