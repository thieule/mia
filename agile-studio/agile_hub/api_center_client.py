from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def _read_json_response(resp) -> dict[str, Any]:
    raw = resp.read().decode("utf-8", errors="replace")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except Exception as e:
        raise ValueError(f"Invalid JSON response: {raw[:300]}") from e
    if not isinstance(data, dict):
        raise ValueError("API Center response must be a JSON object")
    return data


def _http_json(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    bearer: str | None = None,
    timeout_s: float = 12.0,
) -> dict[str, Any]:
    data = None
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return _read_json_response(resp)
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(f"API Center HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"API Center unreachable: {e.reason}") from e


def create_session_info(endpoint: str, secret: str) -> dict[str, Any]:
    data = _http_json("POST", f"{endpoint.rstrip('/')}/v1/sessions", body={"secret": secret})
    sk = str(data.get("session_key") or "").strip()
    if not sk:
        raise ValueError("API Center did not return session_key")
    return {
        "session_key": sk,
        "endpoints": data.get("endpoints") if isinstance(data.get("endpoints"), dict) else {},
    }


def create_session(endpoint: str, secret: str) -> str:
    return create_session_info(endpoint, secret)["session_key"]


def reconnect_session_info(endpoint: str, secret: str) -> dict[str, Any]:
    data = _http_json("POST", f"{endpoint.rstrip('/')}/v1/sessions/reconnect", body={"secret": secret})
    sk = str(data.get("session_key") or "").strip()
    if not sk:
        raise ValueError("API Center did not return session_key")
    return {
        "session_key": sk,
        "endpoints": data.get("endpoints") if isinstance(data.get("endpoints"), dict) else {},
    }


def reconnect_session(endpoint: str, secret: str) -> str:
    return reconnect_session_info(endpoint, secret)["session_key"]


def list_agents(endpoint: str, session_key: str) -> list[dict[str, Any]]:
    data = _http_json("GET", f"{endpoint.rstrip('/')}/v1/agents", bearer=session_key)
    rows = data.get("agents")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        if isinstance(item, dict):
            out.append(item)
    return out


def save_mcp_credentials(
    endpoint: str,
    session_key: str,
    *,
    mcp_server_id: str,
    mcp_url: str,
    api_key: str,
    metadata: dict[str, Any] | None = None,
    hub_reply_base_url: str | None = None,
    mcp_tools_url: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "mcp_server_id": mcp_server_id,
        "mcp_url": mcp_url,
        "api_key": api_key,
        "metadata": metadata or {},
    }
    if hub_reply_base_url:
        body["hub_reply_base_url"] = hub_reply_base_url.strip()
    if mcp_tools_url:
        body["mcp_tools_url"] = mcp_tools_url.strip()
    return _http_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/mcp/credentials",
        bearer=session_key,
        body=body,
    )


def chat_dispatch(
    endpoint: str,
    session_key: str,
    payload: dict[str, Any],
    *,
    timeout_s: float = 95.0,
) -> dict[str, Any]:
    """Forward chat dispatch to API Center (may block until agent reply or wait timeout)."""
    return _http_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/chat/dispatch",
        bearer=session_key,
        body=payload,
        timeout_s=timeout_s,
    )


def webhook_agile_notifications(endpoint: str, session_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _http_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/webhooks/agile-notifications",
        bearer=session_key,
        body=payload,
    )
