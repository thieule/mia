"""MySQL URL resolution for Mia agent tables (database ``agent`` — not ``agile_studio``)."""

from __future__ import annotations

import os
import re
from typing import Any

# Canonical local default (docker mysql-init creates database ``agent`` on port 3307).
DEFAULT_AGENT_DATABASE_URL = "mysql+pymysql://app:app@127.0.0.1:3307/agent"

# Checked in order. ``AGILE_DATABASE_URL`` is intentionally excluded.
_AGENT_DB_ENV_KEYS = (
    "MIA_AGENT_DATABASE_URL",
    "API_CENTER_AGENT_DB_URL",
    "MIA_AGENT_SYNC_DATABASE_URL",
    "MIA_WORKING_QUEUE_DB_URL",
)


def resolve_agent_database_url() -> str:
    """Return SQLAlchemy-style MySQL URL for ``mia_*`` tables, or empty string."""
    for name in _AGENT_DB_ENV_KEYS:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return raw
    return ""


def ensure_agent_db_env_defaults() -> None:
    """Set ``MIA_AGENT_DATABASE_URL`` when no agent DB URL is configured."""
    if resolve_agent_database_url():
        return
    os.environ.setdefault("MIA_AGENT_DATABASE_URL", DEFAULT_AGENT_DATABASE_URL)
    # Keep legacy alias in sync for tools that only read API_CENTER_AGENT_DB_URL.
    os.environ.setdefault("API_CENTER_AGENT_DB_URL", os.environ["MIA_AGENT_DATABASE_URL"])


def parse_mysql_url(url: str) -> dict[str, Any]:
    u = (url or "").strip()
    if not u:
        raise ValueError("empty database url")
    if "://" in u:
        _, rest = u.split("://", 1)
    else:
        rest = u
    auth_host, _, db = rest.rpartition("/")
    db = db.split("?")[0]
    if "@" in auth_host:
        auth, hostport = auth_host.rsplit("@", 1)
    else:
        auth, hostport = "", auth_host
    if ":" in auth:
        user, password = auth.split(":", 1)
    else:
        user, password = auth, ""
    host = hostport
    port = 3306
    if hostport.startswith("["):
        m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", hostport)
        if m:
            host = m.group(1)
            if m.group(2):
                port = int(m.group(2))
    elif ":" in hostport:
        hp, p = hostport.rsplit(":", 1)
        if p.isdigit():
            host, port = hp, int(p)
        else:
            host = hostport
    return {"host": host, "port": port, "user": user, "password": password, "database": db}


def db_connect_kwargs() -> dict[str, Any]:
    raw = resolve_agent_database_url()
    if not raw:
        raise RuntimeError(
            "Missing Mia agent database URL. Set MIA_AGENT_DATABASE_URL "
            f"(recommended: {DEFAULT_AGENT_DATABASE_URL}). "
            "Do not point mia_* tables at AGILE_DATABASE_URL / agile_studio."
        )
    kw = parse_mysql_url(raw)
    if (kw.get("database") or "").strip().lower() == "agile_studio":
        raise RuntimeError(
            "Mia agent DB must use database `agent`, not `agile_studio`. "
            "Fix MIA_AGENT_DATABASE_URL / API_CENTER_AGENT_DB_URL."
        )
    return kw
