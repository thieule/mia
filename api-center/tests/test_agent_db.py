"""Agent DB URL resolution (database ``agent`` only)."""

from __future__ import annotations

import os

import pytest

from agent_db import db_connect_kwargs, ensure_agent_db_env_defaults, resolve_agent_database_url


def test_resolve_prefers_mia_agent_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MIA_AGENT_DATABASE_URL", raising=False)
    monkeypatch.delenv("API_CENTER_AGENT_DB_URL", raising=False)
    monkeypatch.delenv("AGILE_DATABASE_URL", raising=False)
    monkeypatch.setenv("MIA_AGENT_DATABASE_URL", "mysql+pymysql://u:p@localhost:3307/agent")
    assert resolve_agent_database_url().endswith("/agent")


def test_agile_studio_url_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIA_AGENT_DATABASE_URL", "mysql+pymysql://app:app@127.0.0.1:3307/agile_studio")
    with pytest.raises(RuntimeError, match="database `agent`"):
        db_connect_kwargs()


def test_ensure_defaults_sets_agent_db(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("MIA_AGENT_DATABASE_URL", "API_CENTER_AGENT_DB_URL", "MIA_AGENT_SYNC_DATABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    ensure_agent_db_env_defaults()
    assert "/agent" in resolve_agent_database_url()
