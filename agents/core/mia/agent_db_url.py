"""Resolve MySQL URL for Mia agent tables (shared env contract with api-center)."""

from __future__ import annotations

import os

_AGENT_DB_ENV_KEYS = (
    "MIA_AGENT_DATABASE_URL",
    "MIA_WORKING_QUEUE_DB_URL",
    "API_CENTER_AGENT_DB_URL",
    "MIA_AGENT_SYNC_DATABASE_URL",
)


def resolve_agent_database_url() -> str:
    for name in _AGENT_DB_ENV_KEYS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    return ""
