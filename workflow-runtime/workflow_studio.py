"""
Session + agent catalog for Agile Studio / external clients (discovery, bootstrap, optional registration).

Used by``working_queue_webhook.py`` (or a unified HTTP entrypoint). Not a standalone server.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

# --- Sessions (in-memory; optional file persistence) ---

_store: dict[str, float] = {}
_sessions_file: Path | None = None
SESSION_KEY_PREFIX = "wrs_"


def init_session_store(
    data_dir: Path,
    *,
    clear: bool = False,
) -> None:
    global _store, _sessions_file
    data_dir.mkdir(parents=True, exist_ok=True)
    _sessions_file = data_dir / "studio_sessions.json"
    if clear or not _sessions_file.is_file():
        _store = {}
    if _sessions_file.is_file() and not clear:
        try:
            raw = json.loads(_sessions_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "sessions" in raw and isinstance(raw["sessions"], dict):
                for k, v in raw["sessions"].items():
                    if isinstance(v, (int, float)) and k.startswith(SESSION_KEY_PREFIX):
                        _store[k] = float(v)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            if not _store:
                _store = {}


def get_connect_secret() -> str | None:
    """
    A single long-lived secret, known only to the client app (Agile Studio) and this server.
    The client sends it **once** in ``POST /v1/sessions``; the response is a ``session_key`` for all other APIs.

    Primary: ``WORKFLOW_RUNTIME_CONNECT_SECRET``. Deprecated aliases: ``WORKFLOW_STUDIO_BOOTSTRAP_SECRET``,
    ``WORKING_QUEUE_WEBHOOK_BEARER_TOKEN`` (old name — still read for one-release migration).
    """
    s = (os.environ.get("WORKFLOW_RUNTIME_CONNECT_SECRET") or "").strip()
    if s:
        return s
    s = (os.environ.get("WORKFLOW_STUDIO_BOOTSTRAP_SECRET") or "").strip()
    if s:
        return s
    return (os.environ.get("WORKING_QUEUE_WEBHOOK_BEARER_TOKEN") or "").strip() or None


# Backwards compatibility for internal callers
def _bootstrap_secret() -> str | None:
    return get_connect_secret()


def _session_ttl_s() -> float | None:
    # 0 = no expiry
    v = (os.environ.get("WORKFLOW_STUDIO_SESSION_TTL_DAYS") or "30").strip()
    try:
        d = float(v)
    except ValueError:
        d = 30.0
    if d <= 0:
        return None
    return d * 24 * 3600


def create_session(bootstrap: str) -> str | None:
    """Validates bootstrap secret; returns a new session key, or None."""
    b = _bootstrap_secret()
    if not b or len(b) < 12:
        return None
    if len(bootstrap) != len(b) or not secrets.compare_digest(bootstrap, b):
        return None
    key = f"{SESSION_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    _store[key] = time.time()
    _persist_sessions()
    return key


def _persist_sessions() -> None:
    if _sessions_file is None:
        return
    try:
        p = _sessions_file.parent
        p.mkdir(parents=True, exist_ok=True)
        tmp = _sessions_file.parent / f".{_sessions_file.name}.{os.getpid()}.tmp"
        tmp.write_text(
            json.dumps({"version": 1, "sessions": {k: v for k, v in _store.items()}}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(_sessions_file)
    except OSError:
        pass


def session_is_valid(key: str) -> bool:
    if not key or not key.startswith(SESSION_KEY_PREFIX) or key not in _store:
        return False
    ttl = _session_ttl_s()
    if ttl is None:
        return True
    if time.time() - _store[key] > ttl:
        _store.pop(key, None)
        _persist_sessions()
        return False
    return True


# --- Catalog merge (workspace map + display metadata) ---


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_agent_catalog(
    repo: Path,
    agents_map: dict[str, dict[str, Any]],
    catalog_path: Path | None,
) -> list[dict[str, Any]]:
    """
    ``agents_map``: keys = agent_id, value must have ``workspace``.
    ``catalog_path``: optional JSON: ``{ "agents": { "pm": { "displayName", "role", "description" } } }`` or
    a dict keyed by id at root.
    """
    overlay: dict[str, Any] = {}
    if catalog_path and catalog_path.is_file():
        try:
            raw = _load_json(catalog_path)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            raw = {}
        if isinstance(raw, dict):
            o = raw.get("agents", raw) if "agents" in raw else raw
            if isinstance(o, dict):
                overlay = o

    out: list[dict[str, Any]] = []
    for agent_id in sorted(agents_map.keys(), key=str.lower):
        row = dict(agents_map[agent_id])
        row["id"] = agent_id
        w = str(row.get("workspace", "")).strip()
        extra: dict[str, Any] = {}
        if agent_id in overlay and isinstance(overlay[agent_id], dict):
            extra = overlay[agent_id]
        display = (
            extra.get("displayName")
            or extra.get("display_name")
            or extra.get("name")
            or f"Mia {agent_id}"
        )
        role = extra.get("role") or extra.get("label") or "AI assistant"
        desc = extra.get("description") or extra.get("summary") or ""
        sik = extra.get("supportedItemKinds")
        if not isinstance(sik, list) or not sik:
            sik = ["task", "notification"]
        out.append(
            {
                "id": agent_id,
                "name": str(display).strip() or agent_id,
                "role": str(role).strip(),
                "description": str(desc).strip(),
                "workspace": w,
                "supported_item_kinds": sik,
            }
        )
    return out


def public_base_url(request: Any) -> str:
    """``request`` = aiohttp ``web.Request``."""
    env = (os.environ.get("WORKFLOW_RUNTIME_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    # host can include :port
    return f"{scheme}://{request.host}"


def append_interest(
    data_dir: Path,
    body: dict[str, Any],
    agent_id: str,
) -> None:
    """Optional audit line for "studio registered interest" in an agent."""
    f = data_dir / "agent_interest.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {"t": time.time(), "agent_id": agent_id}
    for k in ("client_id", "project_key", "note", "user_ref"):
        v = body.get(k)
        if v is not None and str(v) != "":
            row[k] = v
    line = json.dumps(row, ensure_ascii=False) + "\n"
    with f.open("a", encoding="utf-8") as fo:
        fo.write(line)
