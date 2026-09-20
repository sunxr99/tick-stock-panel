from __future__ import annotations

from app import secrets_store


def test_get_tushare_token_uses_configured_env_value(monkeypatch):
    class _Settings:
        tushare_token = "from-dotenv"

    monkeypatch.setattr(secrets_store, "load", lambda: {})
    monkeypatch.setattr("app.config.settings", _Settings())

    assert secrets_store.get_tushare_token() == "from-dotenv"


def test_get_tushare_token_prefers_local_secret(monkeypatch):
    monkeypatch.setattr(secrets_store, "load", lambda: {"tushare_token": "from-secret"})

    assert secrets_store.get_tushare_token() == "from-secret"
