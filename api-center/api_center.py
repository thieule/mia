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
from typing import Any
from urllib.parse import urlparse

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent
DATA_DIR_DEFAULT = ROOT / "data"
SESSION_PREFIX = "acs_"

_sessions: dict[str, float] = {}
_session_file: Path | None = None
_mcp_file: Path | None = None
_chat_log_file: Path | None = None


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
    global _session_file, _mcp_file, _chat_log_file, _sessions
    data_dir.mkdir(parents=True, exist_ok=True)
    _session_file = data_dir / "sessions.json"
    _mcp_file = data_dir / "mcp_credentials.json"
    _chat_log_file = data_dir / "chat_dispatch_logs.jsonl"
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


def _merge_agents(agents: dict[str, dict[str, Any]], catalog: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for aid in sorted(agents.keys(), key=str.lower):
        a = agents[aid]
        c = catalog.get(aid, {})
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
        return True, "direct_enqueued", str(task_id)
    except Exception as e:
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
        return "unknown", "agent_workspace_not_found"
    item_path = ws / "working_queue" / "state" / "items" / f"{task_id}.json"
    end_at = time.time() + max(0.0, timeout_s)
    while time.time() <= end_at:
        if item_path.is_file():
            try:
                row = json.loads(item_path.read_text(encoding="utf-8"))
            except Exception:
                row = {}
            if isinstance(row, dict):
                loc = str(row.get("location") or row.get("status") or "").strip().lower()
                if loc == "done":
                    txt = str(row.get("result_excerpt") or "").strip()
                    return "done", txt
                if loc == "failed":
                    err = str(row.get("error") or "Task failed").strip()
                    return "failed", err
        await asyncio.sleep(1.5)
    return "timeout", "Agent is processing, not completed in timeout."


def _is_valid_http_url(raw: str) -> bool:
    try:
        p = urlparse(raw)
    except Exception:
        return False
    return p.scheme in {"http", "https"} and bool(p.netloc)


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
        for a in merged_agents:
            if str(a.get("id")) == target_agent_id:
                return a
        return None
    mention_set = {m.strip().lower() for m in mentions if isinstance(m, str) and m.strip()}
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
    lines.append("Hãy đọc context và cập nhật hành động phù hợp với vai trò của bạn.")
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
    mcp_url = str(mcp_row.get("mcp_url") or "").strip()
    if not api_key or not mcp_url:
        return False, "missing mcp_url/api_key"
    path = (os.environ.get("API_CENTER_MCP_REPLY_PATH") or "/agent-chat/reply").strip()
    if not path.startswith("/"):
        path = "/" + path
    url = mcp_url.rstrip("/") + path
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
                elif done_state == "failed":
                    reply_text = f"[{who}] processing error: {done_text}"
                else:
                    reply_text = (
                        f"[{who}] received request and is processing. "
                        f"Mã task: {task_id}"
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
    return result


def require_session(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
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
    targets = _pick_agents_to_start(merged_agents, str(args.agent_ids or ""))
    if not targets:
        print("[api-center] --start-agents enabled but no matching agents selected.", flush=True)
        return []
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


def create_app(merged_agents: list[dict[str, Any]]) -> FastAPI:
    app = FastAPI(title="API Center", version="1")

    def _base_urls(request: Request) -> tuple[str, str]:
        http_base = os.environ.get("API_CENTER_PUBLIC_BASE_URL") or f"{request.url.scheme}://{request.url.netloc}"
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
        mcp_url = str(payload.get("mcp_url") or payload.get("url") or "").strip()
        api_key = str(payload.get("api_key") or "").strip()
        if not server_id:
            raise HTTPException(status_code=400, detail="mcp_server_id is required")
        if not mcp_url or not _is_valid_http_url(mcp_url):
            raise HTTPException(status_code=400, detail="mcp_url must be a valid http/https URL")
        if not api_key:
            raise HTTPException(status_code=400, detail="api_key is required")

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
        records[server_id] = {
            "mcp_server_id": server_id,
            "mcp_url": mcp_url,
            "api_key": api_key,
            "created_at": created_at,
            "updated_at": now,
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        }
        _persist_mcp_credentials(rec)
        return {"ok": True, "mcp_server_id": server_id, "mcp_url": mcp_url, "stored": True, "updated_at": now}

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

    @app.post("/v1/webhooks/agile-notifications")
    async def agile_notifications_webhook(payload: dict[str, Any], _: str = Depends(require_session)) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Root must be JSON object")
        return await _process_notification_webhook(payload=payload, merged_agents=merged_agents)

    @app.websocket("/ws/agent-chat")
    async def ws_agent_chat(websocket: WebSocket) -> None:
        token = websocket.query_params.get("session_key", "").strip()
        if not token:
            auth = websocket.headers.get("authorization") or ""
            if auth.startswith("Bearer "):
                token = auth[7:].strip()
        if not token or not _session_valid(token):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        await websocket.send_json({"event": "chat.connected", "ok": True})
        try:
            while True:
                data = await websocket.receive_json()
                if not isinstance(data, dict):
                    await websocket.send_json({"event": "chat.agent.error", "error": "invalid payload"})
                    continue
                ev = str(data.get("event") or "").strip()
                if ev != "chat.message.created":
                    await websocket.send_json({"event": "chat.agent.error", "error": "unsupported event"})
                    continue
                payload = data.get("payload")
                if not isinstance(payload, dict):
                    await websocket.send_json({"event": "chat.agent.error", "error": "payload must be object"})
                    continue
                _console_inbound_chat(payload, "ws")
                try:
                    result = await _process_chat_dispatch(payload=payload, merged_agents=merged_agents)
                except HTTPException as he:
                    await websocket.send_json({"event": "chat.agent.error", "error": str(he.detail), "status": he.status_code})
                    continue
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
        except WebSocketDisconnect:
            return
        except Exception as e:
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
    app = create_app(merged_agents)
    agent_procs = _start_agent_processes(merged_agents, args)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        _stop_agent_processes(agent_procs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

