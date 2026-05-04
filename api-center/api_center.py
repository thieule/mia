#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent
DATA_DIR_DEFAULT = ROOT / "data"
SESSION_PREFIX = "acs_"


def _chat_debug_enabled() -> bool:
    return (os.environ.get("API_CENTER_CHAT_DEBUG") or "").strip().lower() in ("1", "true", "yes", "on")


def _chat_dbg(msg: str, *parts: Any) -> None:
    if not _chat_debug_enabled():
        return
    extra = " ".join(str(p) for p in parts) if parts else ""
    print(f"[api-center][chat-debug] {msg}{(' ' + extra) if extra else ''}", flush=True)

_sessions: dict[str, float] = {}
_session_file: Path | None = None
_mcp_file: Path | None = None
_chat_log_file: Path | None = None
_wq_sync_delivered_file: Path | None = None
_WQ_SYNC_DELIVERED_MAX = 4000


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, val = line.partition("=")
        name = name.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1]
        if name:
            os.environ[name] = val


def _connect_secret() -> str:
    s = (os.environ.get("API_CENTER_CONNECT_SECRET") or "").strip()
    if not s:
        raise ValueError("Missing API_CENTER_CONNECT_SECRET")
    if len(s) < 12:
        raise ValueError("API_CENTER_CONNECT_SECRET must be >= 12 chars")
    return s


def _session_ttl_s() -> float | None:
    raw = (os.environ.get("API_CENTER_SESSION_TTL_DAYS") or "30").strip()
    try:
        d = float(raw)
    except ValueError:
        d = 30.0
    if d <= 0:
        return None
    return d * 24 * 3600


def _init_storage(data_dir: Path) -> None:
    global _session_file, _mcp_file, _chat_log_file, _sessions, _wq_sync_delivered_file
    data_dir.mkdir(parents=True, exist_ok=True)
    _session_file = data_dir / "sessions.json"
    _mcp_file = data_dir / "mcp_credentials.json"
    _chat_log_file = data_dir / "chat_dispatch_logs.jsonl"
    _wq_sync_delivered_file = data_dir / "wq_sync_delivered_task_ids.json"
    _sessions = {}
    if _session_file.is_file():
        try:
            raw = json.loads(_session_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raw = {}
        if isinstance(raw, dict) and isinstance(raw.get("sessions"), dict):
            for k, v in raw["sessions"].items():
                if isinstance(k, str) and k.startswith(SESSION_PREFIX) and isinstance(v, (int, float)):
                    _sessions[k] = float(v)


def _persist_sessions() -> None:
    if _session_file is None:
        return
    tmp = _session_file.parent / f".{_session_file.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"version": 1, "sessions": _sessions}, indent=2), encoding="utf-8")
    tmp.replace(_session_file)


def _wq_load_sync_delivered_ids() -> set[str]:
    path = _wq_sync_delivered_file
    if path is None or not path.is_file():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ids = raw.get("task_ids") if isinstance(raw, dict) else None
        if isinstance(ids, list):
            return {str(x) for x in ids if isinstance(x, str) and x.strip()}
    except (OSError, json.JSONDecodeError):
        pass
    return set()


def _wq_was_sync_delivered(task_id: str) -> bool:
    tid = str(task_id or "").strip()
    return bool(tid) and tid in _wq_load_sync_delivered_ids()


def _wq_mark_sync_delivered(task_id: str) -> None:
    path = _wq_sync_delivered_file
    tid = str(task_id or "").strip()
    if path is None or not tid:
        return
    cur = _wq_load_sync_delivered_ids()
    cur.add(tid)
    lst = sorted(cur)
    if len(lst) > _WQ_SYNC_DELIVERED_MAX:
        lst = lst[-_WQ_SYNC_DELIVERED_MAX:]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"version": 1, "task_ids": lst}, indent=2), encoding="utf-8")
    tmp.replace(path)


def _create_session(secret: str) -> str | None:
    expected = _connect_secret()
    if len(secret) != len(expected) or not secrets.compare_digest(secret, expected):
        return None
    key = f"{SESSION_PREFIX}{secrets.token_urlsafe(32)}"
    _sessions[key] = time.time()
    _persist_sessions()
    return key


def _session_valid(key: str) -> bool:
    if key not in _sessions:
        return False
    ttl = _session_ttl_s()
    if ttl is None:
        return True
    if time.time() - _sessions[key] > ttl:
        _sessions.pop(key, None)
        _persist_sessions()
        return False
    return True


def _load_agents(path: Path) -> dict[str, dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("agents file must be object")
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip() and isinstance(v, dict):
            out[k.strip()] = dict(v)
    if not out:
        raise ValueError("agents file is empty")
    return out


def _load_catalog(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("agents"), dict):
        raw = raw["agents"]
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, dict):
            out[k] = v
    return out


def _catalog_meta_for_runtime_id(
    catalog: dict[str, dict[str, Any]], runtime_id: str
) -> dict[str, Any]:
    """
    agents.json dùng key runtime (vd. ``mia-ba``). agents.catalog.json thường có key ngắn (``ba``)
    và ``alias``: ``mia-ba`` — cần ghép để có displayName đúng (mention @miaba hoạt động).
    """
    if runtime_id in catalog and isinstance(catalog.get(runtime_id), dict):
        return catalog[runtime_id]
    rid = (runtime_id or "").strip()
    for row in catalog.values():
        if not isinstance(row, dict):
            continue
        if str(row.get("alias") or "").strip() == rid:
            return row
    return {}


def _merge_agents(agents: dict[str, dict[str, Any]], catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for aid in sorted(agents.keys(), key=str.lower):
        a = agents[aid]
        c = _catalog_meta_for_runtime_id(catalog, aid)
        rows.append(
            {
                "id": aid,
                "name": str(c.get("displayName") or c.get("name") or f"Mia {aid}"),
                "role": str(c.get("role") or "AI assistant"),
                "description": str(c.get("description") or ""),
                "workspace": str(a.get("workspace") or ""),
                "supported_item_kinds": c.get("supportedItemKinds")
                if isinstance(c.get("supportedItemKinds"), list)
                else ["task", "notification"],
            }
        )
    return rows


def _load_mcp_credentials() -> dict[str, Any]:
    if _mcp_file is None or not _mcp_file.is_file():
        return {"version": 1, "records": {}}
    try:
        raw = json.loads(_mcp_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "records": {}}
    if not isinstance(raw, dict):
        return {"version": 1, "records": {}}
    if not isinstance(raw.get("records"), dict):
        raw["records"] = {}
    return raw


def _persist_mcp_credentials(data: dict[str, Any]) -> None:
    if _mcp_file is None:
        return
    tmp = _mcp_file.parent / f".{_mcp_file.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_mcp_file)


def _append_chat_log(event: dict[str, Any]) -> None:
    if _chat_log_file is None:
        return
    row = {"t": time.time(), **event}
    with _chat_log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _console_inbound_chat(payload: dict[str, Any], via: str) -> None:
    trace_id = str(payload.get("trace_id") or f"tr_{int(time.time() * 1000)}")
    project_id = str(payload.get("project_id") or "").strip() or "(unknown-project)"
    channel_id = str(payload.get("channel_id") or "").strip() or "(unknown-channel)"
    channel_type = str(payload.get("channel_type") or "").strip() or "(unknown-type)"
    sender = payload.get("sender") if isinstance(payload.get("sender"), dict) else {}
    sender_name = str(sender.get("name") or sender.get("id") or "unknown-sender")
    message = str(payload.get("message") or "").strip()
    preview = (message[:180] + "...") if len(message) > 180 else message
    print(
        "[api-center][chat-inbound]"
        f" via={via}"
        f" trace_id={trace_id}"
        f" project_id={project_id}"
        f" channel_id={channel_id}"
        f" channel_type={channel_type}"
        f" sender={sender_name}"
        f" message={preview!r}",
        flush=True,
    )


def _agent_workspace_path(agent: dict[str, Any]) -> Path | None:
    ws = str(agent.get("workspace") or "").strip()
    if not ws:
        return None
    p = Path(ws)
    if not p.is_absolute():
        p = (ROOT.parent / p).resolve()
    else:
        p = p.resolve()
    if not p.is_dir():
        return None
    return p


def _ensure_core_import_path() -> None:
    core_dir = Path(os.environ.get("API_CENTER_CORE_DIR") or (ROOT.parent / "core")).resolve()
    if str(core_dir) not in sys.path:
        sys.path.insert(0, str(core_dir))


async def _enqueue_agent_queue_item_direct(
    *,
    agent: dict[str, Any],
    project_id: str,
    message: str,
    source_role: str,
    service: str | None,
    context: dict[str, Any],
    item_kind: str,
    enqueued_by: str,
) -> tuple[bool, str, str | None]:
    _ensure_core_import_path()
    try:
        from mia.working_queue import submit_task
        from mia.working_queue.store import WorkingQueueStore
    except Exception as e:
        return False, f"direct_import_error:{type(e).__name__}", None
    agent_ws = _agent_workspace_path(agent)
    if agent_ws is None or not agent_ws.is_dir():
        _chat_dbg("enqueue_skip", "direct_workspace_not_found", f"agent_workspace={agent.get('workspace')!r}")
        return False, "direct_workspace_not_found", None
    wq_subdir = (os.environ.get("API_CENTER_WORKING_QUEUE_SUBDIR") or "working_queue").strip() or "working_queue"
    queue_dir = agent_ws / wq_subdir
    queue_dir.mkdir(parents=True, exist_ok=True)
    ik = (item_kind or "task").strip().lower()
    if ik not in {"task", "notification"}:
        ik = "task"
    try:
        store = WorkingQueueStore(queue_dir)
        task_id = submit_task(
            store,
            project_id=project_id,
            message=message,
            source_role=source_role,
            service=service,
            context=context,
            enqueued_by=enqueued_by,
            item_kind=ik,
        )
        _chat_dbg(
            "enqueue_ok",
            f"queue_dir={queue_dir}",
            f"task_id={task_id}",
            f"item_kind={ik}",
        )
        return True, "direct_enqueued", str(task_id)
    except Exception as e:
        _chat_dbg("enqueue_fail", type(e).__name__, str(e))
        return False, f"direct_enqueue_error:{type(e).__name__}", None


async def _enqueue_agent_chat_task_direct(
    *,
    agent: dict[str, Any],
    agent_id: str,
    project_id: str,
    channel_id: str,
    channel_type: str,
    sender: dict[str, Any],
    message: str,
    payload: dict[str, Any],
    trace_id: str,
) -> tuple[bool, str, str | None]:
    msg = (
        "[Agent chat] User message need to reply.\n"
        f"- project_id: {project_id}\n"
        f"- channel_id: {channel_id}\n"
        f"- channel_type: {channel_type}\n"
        f"- sender: {sender.get('name') or sender.get('id') or 'unknown'}\n"
        f"- message: {message}\n"
        "Please reply briefly, contextually correct, and suggest the next step if needed."
    )
    return await _enqueue_agent_queue_item_direct(
        agent=agent,
        project_id=project_id,
        message=msg,
        source_role="agile_studio_chat",
        service=str(payload.get("project_context", {}).get("name") or "agile-chat"),
        context={
            "chat": {
                "channel_id": channel_id,
                "channel_type": channel_type,
                "sender": sender,
                "message": message,
                "mentions": payload.get("mentions") if isinstance(payload.get("mentions"), list) else [],
                "conversation_history": payload.get("conversation_history")
                if isinstance(payload.get("conversation_history"), list)
                else [],
            },
            "project_context": payload.get("project_context")
            if isinstance(payload.get("project_context"), dict)
            else {},
            "story_context": payload.get("story_context")
            if isinstance(payload.get("story_context"), dict)
            else {},
            "_reply_meta": {
                "trace_id": trace_id,
                "target_agent_id": agent_id,
                "callback_api_url": payload.get("callback_api_url"),
            },
        },
        item_kind="task",
        enqueued_by="api-center:chat.dispatch",
    )


async def _wait_agent_task_result(
    *,
    agent: dict[str, Any],
    task_id: str,
    timeout_s: float,
) -> tuple[str, str]:
    ws = _agent_workspace_path(agent)
    if ws is None:
        _chat_dbg("wait_task", "no_workspace_path")
        return "unknown", "agent_workspace_not_found"
    item_path = ws / "working_queue" / "state" / "items" / f"{task_id}.json"
    _chat_dbg("wait_task_start", f"path={item_path}", f"timeout_s={timeout_s}")
    end_at = time.time() + max(0.0, timeout_s)
    last_pulse = 0.0
    last_loc = ""
    while time.time() <= end_at:
        if item_path.is_file():
            try:
                row = json.loads(item_path.read_text(encoding="utf-8"))
            except Exception:
                row = {}
            if isinstance(row, dict):
                loc = str(row.get("location") or row.get("status") or "").strip().lower()
                if loc != last_loc:
                    last_loc = loc
                    _chat_dbg("wait_task_state", f"location={loc!r}", f"task_id={task_id}")
                if loc == "done":
                    txt = str(row.get("result_excerpt") or "").strip()
                    _chat_dbg("wait_task_done", f"excerpt_len={len(txt)}")
                    return "done", txt
                if loc == "failed":
                    err = str(row.get("error") or "Task failed").strip()
                    _chat_dbg("wait_task_failed", err[:300])
                    return "failed", err
        else:
            now = time.time()
            if _chat_debug_enabled() and now - last_pulse >= 8.0:
                last_pulse = now
                _chat_dbg("wait_task_poll", "state_file_missing_yet", f"task_id={task_id}")
        await asyncio.sleep(1.5)
    _chat_dbg("wait_task_timeout", f"task_id={task_id}", f"path_exists={item_path.is_file()}")
    return "timeout", "Agent is processing, not completed in timeout."


def _is_valid_http_url(raw: str) -> bool:
    try:
        p = urlparse(raw)
    except Exception:
        return False
    return p.scheme in {"http", "https"} and bool(p.netloc)


def _fix_vite_port_to_hub(url: str) -> str:
    """Web UI Vite (5175/5173) hay bị nhập nhầm thay cho Hub API (9120)."""
    u = (url or "").strip()
    if ":5175" in u:
        return u.replace(":5175", ":9120", 1)
    if ":5173" in u:
        return u.replace(":5173", ":9120", 1)
    if ":4173" in u:
        return u.replace(":4173", ":9120", 1)
    return u


def _fix_vite_port_to_mcp(url: str) -> str:
    """Cùng lý do — endpoint MCP streamable-http trong compose là 9121."""
    u = (url or "").strip()
    if ":5175" in u:
        return u.replace(":5175", ":9121", 1)
    if ":5173" in u:
        return u.replace(":5173", ":9121", 1)
    if ":4173" in u:
        return u.replace(":4173", ":9121", 1)
    return u


def _prefer_ipv4_loopback_url(url: str) -> str:
    """Một số máy `localhost` → ::1 trong khi MCP chỉ listen 127.0.0.1 — client kết nối thất bại."""
    s = (url or "").strip()
    if not s:
        return s
    low = s.lower()
    needle = "://localhost"
    idx = low.find(needle)
    if idx < 0:
        return s
    after_host = idx + len(needle)
    if after_host >= len(s) or s[after_host] not in ":/":
        return s
    return s[: idx + 3] + "127.0.0.1" + s[after_host:]


def _derive_hub_base_from_mcp_tools_url(tools_url: str) -> str:
    """Hub reply base từ URL MCP streamable-http (vd. ...:9121/mcp → ...:9120)."""
    u = _fix_vite_port_to_hub((tools_url or "").strip())
    u = u.rstrip("/")
    if ":9121" in u:
        u = u.replace(":9121", ":9120", 1)
    low = u.lower()
    if low.endswith("/mcp"):
        u = u[:-4].rstrip("/")
    return u.strip()


def _derive_tools_url_from_hub_base(hub_url: str) -> str:
    """URL MCP tools mặc định từ base Hub (docker: 9120 → 9121 + /mcp)."""
    u = _fix_vite_port_to_mcp((hub_url or "").strip()).rstrip("/")
    if ":9120" in u:
        u = u.replace(":9120", ":9121", 1)
    if not u.lower().endswith("/mcp"):
        u = u + "/mcp"
    return u.strip()


def _reply_dispatch_base_url(mcp_row: dict[str, Any]) -> str:
    """URL gốc để POST .../agent-chat/reply (không phải endpoint /mcp của FastMCP)."""
    explicit = str(mcp_row.get("hub_reply_base_url") or "").strip()
    if explicit and _is_valid_http_url(explicit):
        return explicit.rstrip("/")
    raw = str(mcp_row.get("mcp_url") or "").strip()
    if raw.rstrip("/").lower().endswith("/mcp"):
        return _derive_hub_base_from_mcp_tools_url(raw).rstrip("/")
    return raw.rstrip("/")


def _normalize_mcp_hub_and_tools_urls(payload: dict[str, Any]) -> tuple[str, str]:
    """
    Trả về (hub_reply_base, mcp_tools_url) — cả hai đều http(s) hợp lệ.
    Cho phép chỉ nhập một trong hai dạng: base Hub (9120) hoặc URL MCP (.../mcp, thường 9121).
    """
    hub_opt = str(payload.get("hub_reply_base_url") or "").strip()
    tools_opt = str(payload.get("mcp_tools_url") or "").strip()
    legacy = str(payload.get("mcp_url") or "").strip()
    env_tools = (os.environ.get("API_CENTER_AGILE_MCP_TOOLS_URL") or "").strip()

    if hub_opt and tools_opt:
        hub_f = _prefer_ipv4_loopback_url(_fix_vite_port_to_hub(hub_opt).rstrip("/"))
        tools_f = _prefer_ipv4_loopback_url(_fix_vite_port_to_mcp(tools_opt).rstrip("/"))
        return hub_f, tools_f

    if legacy.rstrip("/").lower().endswith("/mcp"):
        raw_tools = tools_opt or legacy.strip().rstrip("/")
        tools = _prefer_ipv4_loopback_url(_fix_vite_port_to_mcp(raw_tools).rstrip("/"))
        hub = hub_opt or _derive_hub_base_from_mcp_tools_url(legacy)
        hub = _prefer_ipv4_loopback_url(_fix_vite_port_to_hub(hub).rstrip("/"))
        return hub.rstrip("/"), tools.rstrip("/")

    hub = _prefer_ipv4_loopback_url(_fix_vite_port_to_hub((hub_opt or legacy)).rstrip("/"))
    if not hub:
        raise ValueError("Need mcp_url (hub base or .../mcp) or hub_reply_base_url + mcp_tools_url")
    tools = tools_opt or _derive_tools_url_from_hub_base(hub)
    tools = _prefer_ipv4_loopback_url(_fix_vite_port_to_mcp(tools).rstrip("/"))
    if env_tools:
        tools = _prefer_ipv4_loopback_url(_fix_vite_port_to_mcp(env_tools).rstrip("/"))
    return hub.rstrip("/"), tools.rstrip("/")


def _inject_agile_studio_mcp_into_agent_configs(
    merged_agents: list[dict[str, Any]],
    *,
    tools_url: str,
    api_key: str,
) -> dict[str, Any]:
    """Gộp tools.mcpServers['agile-studio'] vào config/config.json của mỗi agent trong agents.json."""
    summary: dict[str, Any] = {"updated": [], "skipped": [], "errors": []}
    tools_url_n = _prefer_ipv4_loopback_url((tools_url or "").strip())
    entry = {
        "type": "streamableHttp",
        "url": tools_url_n,
        "headers": {"Authorization": f"Bearer {api_key}"},
        "toolTimeout": 30,
        "enabledTools": ["*"],
    }
    for row in merged_agents:
        aid = str(row.get("id") or "").strip()
        ws = str(row.get("workspace") or "").strip()
        root = _agent_root_from_workspace(ws)
        if root is None:
            summary["skipped"].append({"agent": aid, "reason": "bad_workspace", "workspace": ws})
            continue
        cfg_path = root / "config" / "config.json"
        if not cfg_path.is_file():
            summary["skipped"].append({"agent": aid, "reason": "missing_config", "path": str(cfg_path)})
            continue
        try:
            raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            summary["errors"].append({"agent": aid, "error": f"read_json:{e}"})
            continue
        if not isinstance(raw, dict):
            summary["errors"].append({"agent": aid, "error": "config_root_not_object"})
            continue
        tools = raw.setdefault("tools", {})
        if not isinstance(tools, dict):
            raw["tools"] = {}
            tools = raw["tools"]
        mcp = tools.setdefault("mcpServers", {})
        if not isinstance(mcp, dict):
            tools["mcpServers"] = {}
            mcp = tools["mcpServers"]
        mcp["agile-studio"] = entry
        try:
            tmp = cfg_path.parent / f".config.json.{os.getpid()}.tmp"
            tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            tmp.replace(cfg_path)
            summary["updated"].append(aid)
        except Exception as e:
            summary["errors"].append({"agent": aid, "error": str(e)})
    return summary


def _sync_agile_mcp_to_managed_agents(merged_agents: list[dict[str, Any]]) -> None:
    """Khi khởi động hoặc sau khi lưu credential: đồng bộ MCP Agile vào config các agent."""
    rec = _load_mcp_credentials()
    records = rec.get("records") if isinstance(rec.get("records"), dict) else {}
    row = records.get("agile-studio")
    if not isinstance(row, dict):
        return
    api_key = str(row.get("api_key") or "").strip()
    if not api_key:
        return
    tools_url = _fix_vite_port_to_mcp(str(row.get("mcp_tools_url") or "").strip())
    hub = str(row.get("mcp_url") or "").strip()
    if not tools_url:
        if hub and not hub.rstrip("/").lower().endswith("/mcp"):
            tools_url = _derive_tools_url_from_hub_base(hub)
        elif hub:
            tools_url = _fix_vite_port_to_mcp(hub.strip().rstrip("/"))
    env_tools = (os.environ.get("API_CENTER_AGILE_MCP_TOOLS_URL") or "").strip()
    if env_tools:
        tools_url = _fix_vite_port_to_mcp(env_tools.strip())
    tools_url = _prefer_ipv4_loopback_url((tools_url or "").strip())
    if not tools_url or not _is_valid_http_url(tools_url):
        print("[api-center] agile MCP: skip agent config sync (missing or invalid mcp_tools_url)", flush=True)
        return
    summary = _inject_agile_studio_mcp_into_agent_configs(
        merged_agents, tools_url=tools_url, api_key=api_key
    )
    n_ok = len(summary.get("updated") or [])
    n_err = len(summary.get("errors") or [])
    print(
        f"[api-center] agile MCP: synced agent configs updated={n_ok} errors={n_err}",
        flush=True,
    )


async def _notify_gateways_reload_mcp() -> dict[str, Any]:
    """
    Gọi POST tới URL gateway (mia gateway hoặc ``mia serve``) để reload MCP sau khi đã ghi config.

    Env::

        API_CENTER_GATEWAY_MCP_RELOAD_URLS=http://127.0.0.1:18793/internal/reload-mcp,http://127.0.0.1:8900/internal/reload-mcp
        API_CENTER_GATEWAY_MCP_RELOAD_SECRET=<cùng giá trị với MIA_GATEWAY_ADMIN_SECRET trên gateway>
    """
    urls_raw = (os.environ.get("API_CENTER_GATEWAY_MCP_RELOAD_URLS") or "").strip()
    secret = (os.environ.get("API_CENTER_GATEWAY_MCP_RELOAD_SECRET") or "").strip()
    if not urls_raw or not secret:
        return {"skipped": True, "reason": "set API_CENTER_GATEWAY_MCP_RELOAD_URLS and API_CENTER_GATEWAY_MCP_RELOAD_SECRET"}
    urls = [u.strip() for u in urls_raw.split(",") if u.strip()]
    if not urls:
        return {"skipped": True, "reason": "empty URLs"}
    headers = {"Authorization": f"Bearer {secret}", "Content-Type": "application/json"}
    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=25.0) as client:
        for url in urls:
            try:
                r = await client.post(url, json={}, headers=headers)
                body_preview = (r.text or "")[:800]
                results.append({"url": url, "status_code": r.status_code, "body_preview": body_preview})
            except Exception as e:
                results.append({"url": url, "error": f"{type(e).__name__}: {e}"})
    ok_count = sum(1 for x in results if 200 <= int(x.get("status_code") or 0) < 300)
    print(f"[api-center] gateway MCP reload notified ok={ok_count}/{len(results)}", flush=True)
    return {"notified": True, "results": results}


def _extract_bearer(authorization: str | None, x_api_key: str | None) -> str:
    h = authorization or ""
    if h.startswith("Bearer "):
        return h[7:].strip()
    return (x_api_key or "").strip()


def _agent_mention_hit(text: str, agent: dict[str, Any]) -> bool:
    t = (text or "").lower()
    aid = str(agent.get("id") or "").lower()
    name = str(agent.get("name") or "").lower()
    if not t:
        return False
    candidates = [f"@{aid}"]
    if name:
        short = name.replace(" ", "")
        candidates.append(f"@{short}")
    for c in candidates:
        if c in t:
            return True
    return False


def _select_target_agent(
    *,
    merged_agents: list[dict[str, Any]],
    target_agent_id: str | None,
    message: str,
    mentions: list[str],
) -> dict[str, Any] | None:
    if target_agent_id:
        tid = str(target_agent_id).strip().lower()
        if tid.startswith("ai-"):
            tid = "mia-" + tid[3:]
        for a in merged_agents:
            aid = str(a.get("id") or "").strip().lower()
            if aid == tid:
                return a
        return None
    mention_set = {m.strip().lower() for m in mentions if isinstance(m, str) and m.strip()}
    for m in list(mention_set):
        if m.startswith("miamia-"):
            mention_set.add("mia-" + m[7:])
    for m in list(mention_set):
        if m.startswith("ai-"):
            mention_set.add("mia-" + m[3:])
        if m.startswith("mia-"):
            mention_set.add("ai-" + m[4:])
    for a in merged_agents:
        aid = str(a.get("id") or "").lower()
        if aid and (aid in mention_set or f"@{aid}" in mention_set):
            return a
    for a in merged_agents:
        if _agent_mention_hit(message, a):
            return a
    return None


def _should_respond(channel_type: str, target_agent: dict[str, Any] | None) -> bool:
    ct = (channel_type or "").strip().lower()
    if ct in {"direct", "private", "dm", "agent_dm"}:
        return True
    if ct in {"group", "public", "project_channel"}:
        return target_agent is not None
    return target_agent is not None


def _resolve_agents_by_ids(
    *,
    merged_agents: list[dict[str, Any]],
    ids: list[str],
) -> list[dict[str, Any]]:
    wanted = {x.strip().lower() for x in ids if isinstance(x, str) and x.strip()}
    if not wanted:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in merged_agents:
        aid = str(a.get("id") or "").strip()
        if aid and aid.lower() in wanted and aid.lower() not in seen:
            out.append(a)
            seen.add(aid.lower())
    return out


def _build_notification_message(payload: dict[str, Any], agent_id: str) -> str:
    event_type = str(payload.get("event_type") or payload.get("eventType") or "agile.notification").strip()
    summary = str(payload.get("summary") or payload.get("message") or "Data change notification").strip()
    project_id = str(payload.get("project_id") or payload.get("projectId") or "").strip()
    changed = payload.get("changed_fields")
    changed_text = ", ".join([str(x) for x in changed]) if isinstance(changed, list) else ""
    lines = [
        f"[Agile webhook] Notification for agent {agent_id}",
        f"- event_type: {event_type}",
        f"- project_id: {project_id or '(unknown)'}",
        f"- summary: {summary}",
    ]
    if changed_text:
        lines.append(f"- changed_fields: {changed_text}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    hints = data.get("recipient_hints") if isinstance(data.get("recipient_hints"), dict) else {}
    if hints:
        aid_norm = str(agent_id).strip().lower()
        mentioned = hints.get("mentioned_agent_ids") if isinstance(hints.get("mentioned_agent_ids"), list) else []
        assignees = hints.get("story_assignee_agent_ids") if isinstance(hints.get("story_assignee_agent_ids"), list) else []
        mentioned_l = {str(x).strip().lower() for x in mentioned}
        assignees_l = {str(x).strip().lower() for x in assignees}
        direct_mention = aid_norm in mentioned_l
        assignee_hit = aid_norm in assignees_l
        lines.append("")
        lines.append("Relevance hints (comment/story events):")
        lines.append(f"- You are explicitly @mentioned in this comment: {direct_mention}")
        lines.append(f"- You are an AI assignee on this story: {assignee_hit}")
        excerpt = str(hints.get("comment_excerpt") or "").strip()
        if excerpt:
            lines.append("- Comment text:")
            lines.append(excerpt[:4000])
        mmap = hints.get("ai_member_ids_by_agent")
        if isinstance(mmap, dict):
            mid: int | None = None
            for k, v in mmap.items():
                if str(k).strip().lower() == aid_norm:
                    try:
                        mid = int(v)
                    except (TypeError, ValueError):
                        mid = None
                    break
            if mid is not None and mid > 0:
                lines.append("")
                lines.append(
                    f"- Your Agile MCP author_member_id for this project (use with agile_comment_create / chat tools): {mid}"
                )
    lines.append("")
    data_story_id = data.get("story_id")
    comment_events = {
        "agile_studio.comment.created",
        "agile_studio.comment.updated",
    }
    if event_type in comment_events and data_story_id is not None:
        lines.append(
            "Story-comment thread: **reply on the story** using MCP "
            "`agile_comment_create(story_id, author_member_id, body=…)` "
            f"(or `body_text` / `text` / `content` / `message` for the comment text) "
            f"with story_id={data_story_id} and author_member_id from the hints above when present. "
            "Use `agile_story_get` for full context. "
            "If the human asks for a richer description or clarification, **post that text as a new story comment** "
            "(do not stay silent). "
            "Use `agile_story_update` only when they explicitly ask to change stored story fields. "
            "`agile_chat_send` to a **project group channel** (e.g. `general`) is **discouraged** for "
            "comment-thread answers — the default answer belongs on the story."
        )
    else:
        lines.append(
            "Read Context JSON (webhook_payload). "
            "This is an automated **status / project-data** signal — do **not** post to the project's "
            "**group chat** via MCP `agile_chat_send` (`project_channel` / e.g. `general`); humans "
            "should not see broadcast noise there. "
            "If the event is directly relevant (mention / assignee / clear ask in a comment), "
            "reply via Agile Studio MCP — for story threads prefer `agile_comment_create`. "
            "Otherwise note briefly in your queue reply only — don't spam any channel."
        )
    return "\n".join(lines)


async def _process_notification_webhook(
    *,
    payload: dict[str, Any],
    merged_agents: list[dict[str, Any]],
) -> dict[str, Any]:
    project_id = str(payload.get("project_id") or payload.get("projectId") or "").strip()
    if not project_id:
        raise HTTPException(status_code=400, detail="Required: project_id")
    explicit_ids: list[str] = []
    one = str(payload.get("target_agent_id") or payload.get("agent_id") or "").strip()
    if one:
        explicit_ids.append(one)
    many = payload.get("agent_ids")
    if isinstance(many, list):
        explicit_ids.extend([str(x).strip() for x in many if str(x).strip()])
    routing = payload.get("routing")
    if isinstance(routing, dict):
        rid = str(routing.get("agent_id") or routing.get("target_agent_id") or "").strip()
        if rid:
            explicit_ids.append(rid)
    targets = _resolve_agents_by_ids(merged_agents=merged_agents, ids=explicit_ids)
    if not targets:
        raise HTTPException(status_code=400, detail="No routable target agent. Provide target_agent_id or agent_ids.")

    item_kind = str(payload.get("item_kind") or "notification").strip().lower()
    if item_kind not in {"task", "notification"}:
        item_kind = "notification"
    source_role = str(payload.get("source_role") or "agile_studio_webhook").strip() or "agile_studio_webhook"
    service = str(payload.get("service") or payload.get("project_name") or "agile-webhook").strip() or "agile-webhook"
    trace_id = str(payload.get("trace_id") or f"tr_{int(time.time()*1000)}")

    routed: list[dict[str, Any]] = []
    for agent in targets:
        aid = str(agent.get("id") or "")
        msg = _build_notification_message(payload, aid)
        ok, status, task_id = await _enqueue_agent_queue_item_direct(
            agent=agent,
            project_id=project_id,
            message=msg,
            source_role=source_role,
            service=service,
            context={
                "webhook_payload": payload,
                "routing": {"target_agent_id": aid, "trace_id": trace_id},
            },
            item_kind=item_kind,
            enqueued_by="api-center:webhooks.agile-notifications",
        )
        routed.append(
            {
                "agent_id": aid,
                "ok": ok,
                "status": status,
                "task_id": task_id,
            }
        )
    _append_chat_log(
        {
            "type": "webhook.notification.dispatch",
            "trace_id": trace_id,
            "project_id": project_id,
            "routed_count": len(routed),
            "item_kind": item_kind,
        }
    )
    return {
        "ok": True,
        "event": "webhook.notification.ack",
        "trace_id": trace_id,
        "project_id": project_id,
        "item_kind": item_kind,
        "routed": routed,
        "routed_count": len(routed),
    }


async def _send_reply_via_mcp(
    mcp_row: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[bool, str]:
    api_key = str(mcp_row.get("api_key") or "").strip()
    reply_base = _reply_dispatch_base_url(mcp_row)
    if not api_key or not reply_base:
        return False, "missing mcp_url/api_key"
    path = (os.environ.get("API_CENTER_MCP_REPLY_PATH") or "/agent-chat/reply").strip()
    if not path.startswith("/"):
        path = "/" + path
    url = reply_base.rstrip("/") + path
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, json=payload, headers=headers)
        if 200 <= res.status_code < 300:
            return True, f"mcp:{res.status_code}"
        return False, f"mcp_http_{res.status_code}"
    except Exception as e:
        return False, f"mcp_error:{type(e).__name__}"


async def _send_reply_via_api(payload: dict[str, Any]) -> tuple[bool, str]:
    url = (
        str(payload.get("callback_api_url") or "").strip()
        or (os.environ.get("API_CENTER_AGILE_REPLY_URL") or "").strip()
    )
    if not url:
        return False, "missing callback_api_url"
    if not _is_valid_http_url(url):
        return False, "invalid callback_api_url"
    headers = {"Content-Type": "application/json"}
    token = (os.environ.get("API_CENTER_AGILE_REPLY_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(url, json=payload, headers=headers)
        if 200 <= res.status_code < 300:
            return True, f"api:{res.status_code}"
        return False, f"api_http_{res.status_code}"
    except Exception as e:
        return False, f"api_error:{type(e).__name__}"


async def _ingest_working_queue_chat_reply(payload: dict[str, Any]) -> dict[str, Any]:
    """Deliver agent working-queue completion to Hub when sync chat.dispatch wait timed out."""
    task_id = str(payload.get("task_id") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()
    channel_id = str(payload.get("channel_id") or "").strip()
    channel_type = str(payload.get("channel_type") or "direct").strip().lower()
    target_agent_id = str(payload.get("target_agent_id") or "").strip() or None
    trace_id = str(payload.get("trace_id") or task_id).strip()
    content = str(payload.get("content") or "").strip()
    delivery_kind = str(payload.get("delivery_kind") or "done").strip().lower()
    callback_api_url = payload.get("callback_api_url")

    if not task_id or not project_id or not channel_id:
        raise HTTPException(status_code=400, detail="task_id, project_id, channel_id required")
    if delivery_kind not in {"done", "failed"}:
        raise HTTPException(status_code=400, detail="delivery_kind must be done or failed")

    if delivery_kind == "done" and _wq_was_sync_delivered(task_id):
        return {"ok": True, "skipped": "already_delivered_via_sync_poll", "task_id": task_id}

    if not content:
        content = "[Agent completed with no visible reply text.]"

    rec = _load_mcp_credentials()
    records = rec.get("records") if isinstance(rec.get("records"), dict) else {}

    reply_payload = {
        "event": "chat.agent.reply",
        "trace_id": trace_id,
        "project_id": project_id,
        "channel_id": channel_id,
        "target_agent_id": target_agent_id,
        "content": content[:12000],
        "metadata": {
            "source": "api-center",
            "mode": "working_queue_webhook",
            "task_id": task_id,
            "delivery_kind": delivery_kind,
        },
        "callback_api_url": callback_api_url,
    }
    mode, status = await _dispatch_reply(
        mcp_records=records,
        target_agent_id=target_agent_id,
        reply_payload=reply_payload,
    )
    _append_chat_log(
        {
            "type": "chat.reply.working_queue_webhook",
            "task_id": task_id,
            "mode": mode,
            "status": status,
            "delivery_kind": delivery_kind,
        }
    )
    return {"ok": True, "task_id": task_id, "delivery_mode": mode, "delivery_status": status}


def require_wq_ingest_secret(
    authorization: Optional[str] = Header(default=None),
) -> None:
    expected = (os.environ.get("API_CENTER_WORKING_QUEUE_INGEST_SECRET") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Set API_CENTER_WORKING_QUEUE_INGEST_SECRET to accept working-queue completion webhooks",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")
    token = authorization[7:].strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="Invalid ingest token")


async def _dispatch_reply(
    *,
    mcp_records: dict[str, Any],
    target_agent_id: str | None,
    reply_payload: dict[str, Any],
) -> tuple[str, str]:
    """
    Returns (delivery_mode, delivery_status)
    """
    # MCP first
    if target_agent_id and target_agent_id in mcp_records and isinstance(mcp_records[target_agent_id], dict):
        ok, status = await _send_reply_via_mcp(mcp_records[target_agent_id], reply_payload)
        if ok:
            return "mcp", status
    if "agile-studio" in mcp_records and isinstance(mcp_records["agile-studio"], dict):
        ok, status = await _send_reply_via_mcp(mcp_records["agile-studio"], reply_payload)
        if ok:
            return "mcp", status
    # fallback API
    ok, status = await _send_reply_via_api(reply_payload)
    if ok:
        return "api", status
    return "none", status


async def _process_chat_dispatch(
    *,
    payload: dict[str, Any],
    merged_agents: list[dict[str, Any]],
) -> dict[str, Any]:
    # contract
    project_id = str(payload.get("project_id") or "").strip()
    channel_id = str(payload.get("channel_id") or "").strip()
    channel_type = str(payload.get("channel_type") or "").strip().lower()
    sender = payload.get("sender")
    message = str(payload.get("message") or "").strip()
    target_agent_id = str(payload.get("target_agent_id") or "").strip() or None
    mentions = payload.get("mentions") if isinstance(payload.get("mentions"), list) else []
    conv = payload.get("conversation_history") if isinstance(payload.get("conversation_history"), list) else []
    trace_id = str(payload.get("trace_id") or f"tr_{int(time.time()*1000)}")
    if not project_id or not channel_id or not channel_type or not isinstance(sender, dict) or not message:
        raise HTTPException(
            status_code=400,
            detail="Required: project_id, channel_id, channel_type, sender(object), message",
        )
    if channel_type not in {"group", "direct", "private", "dm", "project_channel", "agent_dm", "public"}:
        raise HTTPException(status_code=400, detail="channel_type unsupported")

    agent = _select_target_agent(
        merged_agents=merged_agents,
        target_agent_id=target_agent_id,
        message=message,
        mentions=mentions,
    )
    should = _should_respond(channel_type, agent)
    selected_agent_id = str(agent.get("id")) if isinstance(agent, dict) else None
    _chat_dbg(
        "select_agent",
        f"target_agent_id={target_agent_id!r}",
        f"selected_agent_id={selected_agent_id!r}",
        f"should_respond={should}",
        f"mentions={mentions!r}",
    )

    reply_text = ""
    agent_task_id: str | None = None
    agent_dispatch_status = "skipped"
    if should:
        who = selected_agent_id or "agent"
        if selected_agent_id:
            ok, enq_status, task_id = await _enqueue_agent_chat_task_direct(
                agent=agent,
                agent_id=selected_agent_id,
                project_id=project_id,
                channel_id=channel_id,
                channel_type=channel_type,
                sender=sender,
                message=message,
                payload=payload,
                trace_id=trace_id,
            )
            agent_dispatch_status = enq_status
            agent_task_id = task_id
            if ok and task_id and isinstance(agent, dict):
                wait_s_raw = (os.environ.get("API_CENTER_CHAT_WAIT_TIMEOUT_S") or "45").strip()
                try:
                    wait_s = float(wait_s_raw)
                except ValueError:
                    wait_s = 45.0
                done_state, done_text = await _wait_agent_task_result(
                    agent=agent,
                    task_id=task_id,
                    timeout_s=wait_s,
                )
                agent_dispatch_status = f"{agent_dispatch_status}:{done_state}"
                if done_state == "done" and done_text.strip():
                    reply_text = done_text[:12000]
                    _wq_mark_sync_delivered(task_id)
                elif done_state == "failed":
                    reply_text = f"[{who}] processing error: {done_text}"
                elif done_state == "timeout":
                    reply_text = (
                        f"[{who}] Still processing (wait window expired). "
                        f"When the agent finishes, a follow-up reply can be pushed if "
                        f"`WORKING_QUEUE_REPLY_INGEST_URL` / `WORKING_QUEUE_REPLY_INGEST_SECRET` match "
                        f"`API_CENTER_WORKING_QUEUE_INGEST_SECRET` on API Center (see api-center EXAMPLE_.env). "
                        f"Task `{task_id}`. Increase `API_CENTER_CHAT_WAIT_TIMEOUT_S` (default 45) for slower runs. "
                        "If nothing completes: ensure this agent id is in `--agent-ids`, "
                        "`working_queue.enabled` is true in `config/config.json`, and the gateway process is running."
                    )
                else:
                    reply_text = (
                        f"[{who}] received request and is processing. "
                        f"Task ID: {task_id}"
                    )
            else:
                reply_text = (
                    f"[{who}] received project context {project_id} but couldn't enqueue to agent queue "
                    f"({agent_dispatch_status})."
                )
        else:
            reply_text = (
                f"[{who}] received project context {project_id}. "
                "Please mention the correct agent to process."
            )
    result = {
        "trace_id": trace_id,
        "project_id": project_id,
        "channel_id": channel_id,
        "channel_type": channel_type,
        "selected_agent_id": selected_agent_id,
        "should_respond": should,
        "reply_text": reply_text,
        "agent_task_id": agent_task_id,
        "agent_dispatch_status": agent_dispatch_status,
        "policy": {
            "rule": "mentionAgentInGroup || isDirectAgentChannel",
            "mention_hit": bool(agent) if channel_type in {"group", "public", "project_channel"} else None,
        },
        "context_window": {
            "conversation_history_items": len(conv),
            "project_context_present": bool(payload.get("project_context")),
            "story_context_present": bool(payload.get("story_context")),
        },
    }
    _append_chat_log(
        {
            "type": "chat.dispatch",
            "trace_id": trace_id,
            "project_id": project_id,
            "channel_id": channel_id,
            "channel_type": channel_type,
            "selected_agent_id": selected_agent_id,
            "should_respond": should,
            "message_preview": message[:240],
        }
    )
    # Luôn in (không cần API_CENTER_CHAT_DEBUG) — để terminal có dòng khi có request chat.
    print(
        "[api-center][chat-result]"
        f" trace_id={trace_id}"
        f" should_respond={should}"
        f" selected_agent_id={selected_agent_id!r}"
        f" reply_chars={len(reply_text)}"
        f" dispatch_status={agent_dispatch_status!r}",
        flush=True,
    )
    return result


def require_session(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None, alias="X-Api-Key"),
) -> str:
    token = _extract_bearer(authorization, x_api_key)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer session_key")
    if not _session_valid(token):
        raise HTTPException(status_code=401, detail="Invalid/expired session_key")
    return token


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Standalone API Center (FastAPI)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("API_CENTER_PORT", "18881")))
    p.add_argument("--env", type=Path, default=None, help="dotenv file (default api-center/.env)")
    p.add_argument("--agents", type=Path, default=None, help="agents map file")
    p.add_argument("--catalog", type=Path, default=None, help="agents catalog file")
    p.add_argument("--data-dir", type=Path, default=None, help="state/session directory")
    p.add_argument(
        "--start-agents",
        action="store_true",
        help="Start configured agent launchers (start.py) together with API Center.",
    )
    p.add_argument(
        "--agent-ids",
        default="",
        help="Comma-separated agent ids to start (default: all from agents file).",
    )
    p.add_argument(
        "--agent-start-args",
        default="--skip-install",
        help="Extra args passed to each agent start.py (default: --skip-install).",
    )
    return p.parse_args()


def _agent_root_from_workspace(workspace: str) -> Path | None:
    ws = workspace.strip()
    if not ws:
        return None
    p = Path(ws)
    if not p.is_absolute():
        p = (ROOT.parent / p).resolve()
    else:
        p = p.resolve()
    if not p.is_dir():
        return None
    return p.parent


def _pick_agents_to_start(merged_agents: list[dict[str, Any]], raw_ids: str) -> list[dict[str, Any]]:
    wanted = {x.strip().lower() for x in raw_ids.split(",") if x.strip()}
    if not wanted:
        return list(merged_agents)
    out: list[dict[str, Any]] = []
    for row in merged_agents:
        aid = str(row.get("id") or "").strip().lower()
        if aid and aid in wanted:
            out.append(row)
    return out


def _start_agent_processes(merged_agents: list[dict[str, Any]], args: argparse.Namespace) -> list[subprocess.Popen[Any]]:
    if not args.start_agents:
        return []
    raw_ids = str(args.agent_ids or "").strip()
    targets = _pick_agents_to_start(merged_agents, raw_ids)
    if not targets:
        print("[api-center] --start-agents enabled but no matching agents selected.", flush=True)
        return []
    if raw_ids:
        started = {str(r.get("id") or "").strip().lower() for r in targets if str(r.get("id") or "").strip()}
        catalog_ids = [
            str(r.get("id") or "").strip().lower() for r in merged_agents if str(r.get("id") or "").strip()
        ]
        not_started = sorted({x for x in catalog_ids if x not in started})
        if not_started:
            print(
                "[api-center] --agent-ids is a subset: Agile chat or webhooks targeting agents that are "
                "not started here will time out until you add them to --agent-ids or run `python start.py` "
                f"in that workspace. Started: {sorted(started)}; not started: {not_started}",
                flush=True,
            )
    extra = shlex.split(str(args.agent_start_args or "").strip())
    procs: list[subprocess.Popen[Any]] = []
    for row in targets:
        aid = str(row.get("id") or "").strip()
        ws = str(row.get("workspace") or "").strip()
        root = _agent_root_from_workspace(ws)
        if root is None:
            print(f"[api-center] skip agent {aid}: invalid workspace={ws!r}", flush=True)
            continue
        launcher = root / "start.py"
        if not launcher.is_file():
            print(f"[api-center] skip agent {aid}: missing launcher {launcher}", flush=True)
            continue
        cmd = [sys.executable, str(launcher), *extra]
        try:
            p = subprocess.Popen(cmd, cwd=str(root))
            procs.append(p)
            print(f"[api-center] started agent {aid} pid={p.pid} cmd={' '.join(cmd)}", flush=True)
        except Exception as e:
            print(f"[api-center] failed to start agent {aid}: {type(e).__name__}: {e}", flush=True)
    return procs


def _stop_agent_processes(procs: list[subprocess.Popen[Any]]) -> None:
    for p in procs:
        if p.poll() is not None:
            continue
        try:
            p.terminate()
            p.wait(timeout=8)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass


def _normalize_public_http_base(env_val: str | None, request: Request) -> str:
    """HTTP base URL cho link trong JSON (browser). Nếu env thiếu scheme (vd. localhost:18881), thêm http://."""
    s = (env_val or "").strip()
    if not s:
        return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")
    low = s.lower()
    if low.startswith("https://") or low.startswith("http://"):
        return s.rstrip("/")
    return f"http://{s.lstrip('/')}".rstrip("/")


def create_app(merged_agents: list[dict[str, Any]]) -> FastAPI:
    app = FastAPI(title="API Center", version="1")

    def _base_urls(request: Request) -> tuple[str, str]:
        http_base = _normalize_public_http_base(os.environ.get("API_CENTER_PUBLIC_BASE_URL"), request)
        if http_base.startswith("https://"):
            ws_base = "wss://" + http_base[len("https://") :]
        elif http_base.startswith("http://"):
            ws_base = "ws://" + http_base[len("http://") :]
        else:
            ws_base = http_base
        return http_base, ws_base

    @app.exception_handler(HTTPException)
    async def http_exc_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": "http_error", "message": str(exc.detail), "http_status": exc.status_code}},
        )

    @app.get("/")
    async def root(request: Request) -> dict[str, Any]:
        base, _ = _base_urls(request)
        return {
            "service": "api_center",
            "version": 1,
            "links": {
                "health": f"{base}/v1/health",
                "session_create": f"{base}/v1/sessions",
                "session_reconnect": f"{base}/v1/sessions/reconnect",
                "agents": f"{base}/v1/agents",
                "mcp_upsert": f"{base}/v1/mcp/credentials",
                "chat_dispatch": f"{base}/v1/chat/dispatch",
                "working_queue_reply_ingest": f"{base}/v1/internal/working-queue-reply",
                "chat_ws": f"{base}/ws/agent-chat?session_key=<session_key>",
                "agile_notifications_webhook": f"{base}/v1/webhooks/agile-notifications",
            },
        }

    @app.get("/health")
    async def health_simple(_: str = Depends(require_session)) -> dict[str, str]:
        return {"status": "ok", "service": "api_center"}

    @app.get("/v1/health")
    async def health(_: str = Depends(require_session)) -> dict[str, str]:
        return {"status": "ok", "service": "api_center"}

    @app.post("/v1/sessions", status_code=201)
    async def create_session(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        sec = str(payload.get("secret") or "").strip() if isinstance(payload, dict) else ""
        if not sec:
            raise HTTPException(status_code=400, detail="Field `secret` is required")
        sk = _create_session(sec)
        if not sk:
            raise HTTPException(status_code=401, detail="Secret does not match")
        base, ws_base = _base_urls(request)
        return {
            "session_key": sk,
            "token_type": "bearer",
            "endpoints": {
                "agents": f"{base}/v1/agents",
                "chat_dispatch": f"{base}/v1/chat/dispatch",
                "chat_ws": f"{ws_base}/ws/agent-chat?session_key={sk}",
                "agile_notifications_webhook": f"{base}/v1/webhooks/agile-notifications",
            },
        }

    @app.post("/v1/sessions/reconnect", status_code=201)
    async def reconnect(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        return await create_session(payload, request)

    @app.get("/v1/agents")
    async def agents(_: str = Depends(require_session)) -> dict[str, Any]:
        return {"agents": merged_agents, "count": len(merged_agents)}

    @app.post("/v1/mcp/credentials", status_code=201)
    async def mcp_upsert(payload: dict[str, Any], _: str = Depends(require_session)) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Root must be JSON object")
        server_id = str(payload.get("mcp_server_id") or payload.get("server_id") or "agile-studio").strip()
        api_key = str(payload.get("api_key") or "").strip()
        if not server_id:
            raise HTTPException(status_code=400, detail="mcp_server_id is required")
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required")
        try:
            hub_reply, mcp_tools = _normalize_mcp_hub_and_tools_urls(payload)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not _is_valid_http_url(hub_reply):
            raise HTTPException(status_code=400, detail="hub reply base URL must be valid http/https")
        if not _is_valid_http_url(mcp_tools):
            raise HTTPException(status_code=400, detail="mcp_tools_url must be valid http/https")

        rec = _load_mcp_credentials()
        records = rec.setdefault("records", {})
        if not isinstance(records, dict):
            records = {}
            rec["records"] = records
        now = time.time()
        existing = records.get(server_id)
        created_at = now
        if isinstance(existing, dict) and isinstance(existing.get("created_at"), (int, float)):
            created_at = float(existing["created_at"])
        meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        records[server_id] = {
            "mcp_server_id": server_id,
            "mcp_url": hub_reply,
            "hub_reply_base_url": hub_reply,
            "mcp_tools_url": mcp_tools,
            "api_key": api_key,
            "created_at": created_at,
            "updated_at": now,
            "metadata": meta,
        }
        _persist_mcp_credentials(rec)
        agent_sync: dict[str, Any] | None = None
        if server_id == "agile-studio":
            agent_sync = _inject_agile_studio_mcp_into_agent_configs(
                merged_agents, tools_url=mcp_tools, api_key=api_key
            )
            print(
                "[api-center] agile MCP: injected into agent configs "
                f"updated={len(agent_sync.get('updated') or [])} errors={len(agent_sync.get('errors') or [])}",
                flush=True,
            )
        gateway_reload: dict[str, Any] | None = None
        if server_id == "agile-studio":
            gateway_reload = await _notify_gateways_reload_mcp()
        out: dict[str, Any] = {
            "ok": True,
            "mcp_server_id": server_id,
            "mcp_url": hub_reply,
            "mcp_tools_url": mcp_tools,
            "stored": True,
            "updated_at": now,
        }
        if agent_sync is not None:
            out["agent_config_sync"] = agent_sync
        if gateway_reload is not None:
            out["gateway_reload"] = gateway_reload
        return out

    @app.get("/v1/mcp/credentials/{server_id}")
    async def mcp_get(server_id: str, _: str = Depends(require_session)) -> dict[str, Any]:
        rec = _load_mcp_credentials()
        records = rec.get("records")
        if not isinstance(records, dict):
            raise HTTPException(status_code=404, detail="No MCP credentials stored")
        row = records.get(server_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail=f"No MCP credentials for server_id={server_id!r}")
        api_key = str(row.get("api_key") or "")
        masked = f"{api_key[:3]}***{api_key[-2:]}" if len(api_key) >= 6 else "***"
        return {
            "mcp_server_id": server_id,
            "mcp_url": row.get("mcp_url"),
            "mcp_tools_url": row.get("mcp_tools_url"),
            "has_api_key": bool(api_key),
            "api_key_masked": masked,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        }

    @app.post("/v1/chat/dispatch")
    async def chat_dispatch(payload: dict[str, Any], _: str = Depends(require_session)) -> dict[str, Any]:
        if isinstance(payload, dict):
            _console_inbound_chat(payload, "http")
        result = await _process_chat_dispatch(payload=payload, merged_agents=merged_agents)
        _chat_dbg(
            "http_dispatch_result",
            f"should_respond={result.get('should_respond')}",
            f"reply_len={len(str(result.get('reply_text') or ''))}",
            f"agent_dispatch_status={result.get('agent_dispatch_status')!r}",
        )
        delivery_mode = "none"
        delivery_status = "skipped"
        if result.get("should_respond"):
            rec = _load_mcp_credentials()
            records = rec.get("records")
            if not isinstance(records, dict):
                records = {}
            reply_payload = {
                "event": "chat.agent.reply",
                "trace_id": result["trace_id"],
                "project_id": result["project_id"],
                "channel_id": result["channel_id"],
                "target_agent_id": result["selected_agent_id"],
                "content": result["reply_text"],
                "metadata": {"source": "api-center", "mode": "http_dispatch"},
                "callback_api_url": payload.get("callback_api_url"),
            }
            delivery_mode, delivery_status = await _dispatch_reply(
                mcp_records=records,
                target_agent_id=result.get("selected_agent_id"),
                reply_payload=reply_payload,
            )
            _append_chat_log(
                {
                    "type": "chat.reply.delivery",
                    "trace_id": result["trace_id"],
                    "mode": delivery_mode,
                    "status": delivery_status,
                }
            )
        return {
            "ok": True,
            "event": "chat.agent.ack",
            **result,
            "delivery_mode": delivery_mode,
            "delivery_status": delivery_status,
        }

    @app.post("/v1/internal/working-queue-reply")
    async def working_queue_completion_ingest(
        payload: dict[str, Any],
        _: None = Depends(require_wq_ingest_secret),
    ) -> dict[str, Any]:
        """Agent gateway POSTs here when a chat-originated queue task finishes (async follow-up)."""
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Root must be JSON object")
        return await _ingest_working_queue_chat_reply(payload)

    @app.post("/v1/webhooks/agile-notifications")
    async def agile_notifications_webhook(payload: dict[str, Any], _: str = Depends(require_session)) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Root must be JSON object")
        return await _process_notification_webhook(payload=payload, merged_agents=merged_agents)

    @app.websocket("/ws/agent-chat")
    async def ws_agent_chat(websocket: WebSocket) -> None:
        """Bidirectional chat bridge **browser ⇄ API Center** (not agent ⇄ API Center).

        Client → server: ``{"event":"chat.message.created","payload":{...}}``.
        Server → client: ``chat.connected``, ``chat.agent.ack``, ``chat.agent.reply`` (includes ``reply_text``),
        ``chat.agent.error``. Agent work runs via working-queue + subprocess gateway; replies return on this socket after dispatch completes.
        """
        token = websocket.query_params.get("session_key", "").strip()
        if not token:
            auth = websocket.headers.get("authorization") or ""
            if auth.startswith("Bearer "):
                token = auth[7:].strip()
        if not token or not _session_valid(token):
            _chat_dbg("ws_agent_chat", "reject", "401_missing_or_invalid_session")
            await websocket.close(code=4401)
            return
        await websocket.accept()
        _chat_dbg("ws_agent_chat", "accepted", f"session_prefix={(token[:12] + '…') if len(token) > 12 else token!r}")
        await websocket.send_json({"event": "chat.connected", "ok": True})
        try:
            while True:
                data = await websocket.receive_json()
                if not isinstance(data, dict):
                    _chat_dbg("ws_recv", "invalid_payload_non_object")
                    await websocket.send_json({"event": "chat.agent.error", "error": "invalid payload"})
                    continue
                ev = str(data.get("event") or "").strip()
                if ev != "chat.message.created":
                    _chat_dbg("ws_recv", "unsupported_event", repr(ev))
                    await websocket.send_json({"event": "chat.agent.error", "error": "unsupported event"})
                    continue
                payload = data.get("payload")
                if not isinstance(payload, dict):
                    _chat_dbg("ws_recv", "payload_not_object")
                    await websocket.send_json({"event": "chat.agent.error", "error": "payload must be object"})
                    continue
                _console_inbound_chat(payload, "ws")
                try:
                    result = await _process_chat_dispatch(payload=payload, merged_agents=merged_agents)
                except HTTPException as he:
                    _chat_dbg("ws_dispatch_http_exc", he.status_code, str(he.detail))
                    await websocket.send_json({"event": "chat.agent.error", "error": str(he.detail), "status": he.status_code})
                    continue
                _chat_dbg(
                    "ws_dispatch_result",
                    f"should_respond={result.get('should_respond')}",
                    f"reply_len={len(str(result.get('reply_text') or ''))}",
                    f"dispatch_status={result.get('agent_dispatch_status')!r}",
                )
                await websocket.send_json({"event": "chat.agent.ack", **result})
                if result.get("should_respond"):
                    rec = _load_mcp_credentials()
                    records = rec.get("records")
                    if not isinstance(records, dict):
                        records = {}
                    reply_payload = {
                        "event": "chat.agent.reply",
                        "trace_id": result["trace_id"],
                        "project_id": result["project_id"],
                        "channel_id": result["channel_id"],
                        "target_agent_id": result["selected_agent_id"],
                        "content": result["reply_text"],
                        "metadata": {"source": "api-center", "mode": "ws"},
                        "callback_api_url": payload.get("callback_api_url"),
                    }
                    mode, status = await _dispatch_reply(
                        mcp_records=records,
                        target_agent_id=result.get("selected_agent_id"),
                        reply_payload=reply_payload,
                    )
                    await websocket.send_json(
                        {
                            "event": "chat.agent.reply",
                            **result,
                            "delivery_mode": mode,
                            "delivery_status": status,
                        }
                    )
                    _chat_dbg("ws_reply_sent", f"delivery_mode={mode}", f"delivery_status={status!r}")
        except WebSocketDisconnect:
            _chat_dbg("ws_agent_chat", "disconnect", "client_closed")
            return
        except Exception as e:
            _chat_dbg("ws_agent_chat", "exception", type(e).__name__, str(e))
            await websocket.send_json({"event": "chat.agent.error", "error": f"{type(e).__name__}: {e}"})
            await websocket.close(code=1011)

    return app


def main() -> int:
    args = _parse_args()
    _load_dotenv((args.env or ROOT / ".env").resolve())
    try:
        _ = _connect_secret()
    except ValueError as e:
        print(str(e))
        return 1

    agents_path = (args.agents or Path(os.environ.get("API_CENTER_AGENTS_FILE", str(ROOT / "agents.json")))).expanduser().resolve()
    catalog_raw = os.environ.get("API_CENTER_CATALOG_FILE", "").strip()
    catalog_path = args.catalog or (Path(catalog_raw).expanduser().resolve() if catalog_raw else (ROOT / "agents.catalog.json"))
    try:
        agent_map = _load_agents(agents_path)
        catalog = _load_catalog(catalog_path if isinstance(catalog_path, Path) else None)
        merged_agents = _merge_agents(agent_map, catalog)
    except Exception as e:
        print(f"Failed loading agents metadata: {e}")
        return 1

    _init_storage((args.data_dir or DATA_DIR_DEFAULT).resolve())
    _sync_agile_mcp_to_managed_agents(merged_agents)
    env_file = (args.env or ROOT / ".env").resolve()
    print(
        "[api-center] startup"
        f" env_file={env_file}"
        f" chat_debug={_chat_debug_enabled()}"
        f" port={args.port}",
        flush=True,
    )
    print(
        "[api-center] Khi có chat @agent, terminal sẽ có [api-center][chat-inbound] và [api-center][chat-result].",
        flush=True,
    )
    app = create_app(merged_agents)
    agent_procs = _start_agent_processes(merged_agents, args)
    try:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info",
            # Giữ WS sống khi chờ agent (LLM + queue có thể >45s); tránh proxy/ngắt idle.
            ws_ping_interval=25.0,
            ws_ping_timeout=25.0,
        )
    finally:
        _stop_agent_processes(agent_procs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

