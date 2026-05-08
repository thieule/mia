"""Mirror browser chat behaviour after MCP posts a message: notify API Center so @mentions enqueue agents."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

from sqlalchemy.orm import Session

from agile_hub import api_center_client, crud

log = logging.getLogger(__name__)

_AGENT_REPLY_PATH = "/api/v1/integrations/api-center/agent-reply"


def hub_agent_reply_callback_url() -> str | None:
    """Base URL Hub nhận POST từ API Center khi agent trả lời xong (working-queue async).

    Ưu tiên ``AGILE_API_CENTER_CALLBACK_BASE_URL`` (public/internal URL mà api_center + gateway gọi được).
    Nếu không set: suy ra từ ``listen_host`` / ``listen_port`` — host ``0.0.0.0`` được đổi thành ``127.0.0.1``.
    """
    explicit = (os.environ.get("AGILE_API_CENTER_CALLBACK_BASE_URL") or "").strip().rstrip("/")
    if explicit:
        base = explicit
    else:
        try:
            from agile_hub.config import get_settings

            s = get_settings()
            host = str(s.listen_host or "127.0.0.1").strip()
            if host in {"0.0.0.0", "::", "[::]"}:
                host = "127.0.0.1"
            base = f"http://{host}:{int(s.listen_port)}".rstrip("/")
        except Exception:
            base = "http://127.0.0.1:9120"
    return f"{base}{_AGENT_REPLY_PATH}"


def merge_dispatch_payload_callback_url(payload: dict[str, Any]) -> dict[str, Any]:
    """Gắn ``callback_api_url`` mặc định để reply sau working-queue không bị mất khi chờ lâu."""
    if not isinstance(payload, dict):
        return payload
    if str(payload.get("callback_api_url") or "").strip():
        return payload
    cb = hub_agent_reply_callback_url()
    if cb:
        payload["callback_api_url"] = cb
    return payload


def _mention_tokens(text: str) -> list[str]:
    out: list[str] = []
    for m in re.finditer(r"@([^\s@]+)", text or ""):
        tok = (m.group(1) or "").strip().lower()
        tok = re.sub(r"[.,;:!?)\]]+$", "", tok)
        if tok:
            out.append(tok)
    return list(dict.fromkeys(out))


def _channel_id_for_dispatch(
    *,
    project_id: int,
    target_kind: str,
    channel_name: str | None,
    sender_user_id: int,
    user_id: int,
) -> str:
    tk = (target_kind or "").strip().lower()
    if tk == "project_channel":
        name = (channel_name or "general").strip() or "general"
        return f"{project_id}_{name}"
    peer = int(user_id or 0)
    viewer = int(sender_user_id or 0)
    if peer > 0 and viewer > 0:
        lo = min(peer, viewer)
        hi = max(peer, viewer)
        return f"{project_id}_dm_{lo}_{hi}"
    return f"{project_id}_{viewer}"


def _normalize_catalog_agent_id(raw: str) -> str:
    s = (raw or "").strip().lower()
    if s.startswith("ai-"):
        return "mia-" + s[3:]
    return s


def _dm_peer_user_id_for_agent_send(
    target_kind: str,
    room_user_id: int,
    agent_member_id: int,
    original_sender_id: int,
) -> int | None:
    """Match web ``dmPeerUserIdForAgentSend`` for ``SendMessageDto.userId`` in DM."""
    if (target_kind or "").strip().lower() != "private_user":
        return None
    s = int(agent_member_id or 0)
    other = int(room_user_id or 0)
    me = int(original_sender_id or 0)
    if not s or not other or not me:
        return other if other else None
    if s == other:
        return me
    if s == me:
        return other
    return other


def _post_agent_reply_to_chat_service(
    *,
    project_id: int,
    target_kind: str,
    channel_name: str | None,
    user_id: int,
    original_sender_id: int,
    agent_member_id: int,
    sender_name: str,
    content: str,
) -> bool:
    """POST tin agent vào chat-service. Trả False khi không gửi được (caller phải báo lỗi, không giả 200 OK)."""
    base = (os.environ.get("AGILE_CHAT_SERVICE_URL") or "").strip().rstrip("/")
    if not base:
        log.warning("chat_api_center_bridge: AGILE_CHAT_SERVICE_URL unset, cannot post agent reply to chat")
        return False
    tk = (target_kind or "").strip().lower()
    body: dict[str, Any] = {
        "projectId": int(project_id),
        "targetKind": tk,
        "senderUserId": int(agent_member_id),
        "senderName": (sender_name or "").strip() or None,
        "content": content[:4000],
    }
    if tk == "project_channel":
        body["channelName"] = (channel_name or "general").strip() or "general"
    else:
        peer = _dm_peer_user_id_for_agent_send(tk, user_id, agent_member_id, original_sender_id)
        if peer and int(peer) > 0:
            body["userId"] = int(peer)
    url = f"{base}/api/chat/messages"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            sc = int(getattr(resp, "status", None) or resp.getcode() or 0)
            if not (200 <= sc < 300):
                raw = resp.read().decode("utf-8", errors="replace")[:400]
                log.warning("chat_api_center_bridge: chat-service POST %s %s", sc, raw)
                return False
            return True
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:500]
        log.warning("chat_api_center_bridge: chat-service HTTP %s: %s", e.code, msg)
        return False
    except urllib.error.URLError as e:
        log.warning("chat_api_center_bridge: chat-service unreachable: %s", e.reason)
        return False


def _dispatch_sync(
    db: Session,
    *,
    project_id: int,
    target_kind: str,
    channel_name: str | None,
    user_id: int,
    sender_user_id: int,
    sender_name: str | None,
    content: str,
) -> dict[str, Any]:
    toks = _mention_tokens(content)
    if not toks:
        return {"ok": False, "skipped": "no_mentions"}

    row = crud.api_center_connection_get(db)
    if row is None or not (row.session_key or "").strip():
        return {"ok": False, "skipped": "api_center_not_connected"}

    p = crud.project_get(db, project_id)
    if p is None:
        return {"ok": False, "skipped": "project_not_found"}

    ch_id = _channel_id_for_dispatch(
        project_id=project_id,
        target_kind=target_kind,
        channel_name=channel_name,
        sender_user_id=sender_user_id,
        user_id=user_id,
    )
    ct = "direct" if (target_kind or "").strip().lower() == "private_user" else "group"
    trace_id = f"mcp_chat_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {
        "trace_id": trace_id,
        "project_id": str(project_id),
        "project_context": {
            "name": getattr(p, "name", None) or f"Project {project_id}",
            "id": project_id,
            "slug": getattr(p, "slug", None),
            "workspace_ref": getattr(p, "workspace_ref", None),
        },
        "channel_id": ch_id,
        "channel_type": ct,
        "sender": {"id": str(sender_user_id), "name": (sender_name or "").strip()},
        "message": content,
        "mentions": toks,
        "conversation_history": [],
    }
    cb = hub_agent_reply_callback_url()
    if cb:
        payload["callback_api_url"] = cb
    try:
        out = api_center_client.chat_dispatch(row.endpoint, row.session_key or "", payload)
        log.debug(
            "chat_api_center_bridge dispatch trace_id=%s should_respond=%s",
            trace_id,
            (out or {}).get("should_respond"),
        )
        ads = str((out or {}).get("agent_dispatch_status") or "")
        reply = str((out or {}).get("reply_text") or "").strip()
        sel_agent = _normalize_catalog_agent_id(str((out or {}).get("selected_agent_id") or ""))
        if (
            (out or {}).get("should_respond")
            and ":done" in ads
            and reply
            and sel_agent
        ):
            mmap = crud.project_ai_agent_member_ids_map(db, project_id)
            agent_mid = None
            for k, v in mmap.items():
                if str(k).strip().lower() == sel_agent:
                    agent_mid = int(v)
                    break
            if agent_mid and agent_mid > 0:
                mem = crud.member_get(db, agent_mid)
                dn = (getattr(mem, "display_name", None) or "").strip() if mem else ""
                post_name = dn or sel_agent
                posted = _post_agent_reply_to_chat_service(
                    project_id=project_id,
                    target_kind=target_kind,
                    channel_name=channel_name,
                    user_id=int(user_id or 0),
                    original_sender_id=int(sender_user_id),
                    agent_member_id=agent_mid,
                    sender_name=post_name,
                    content=reply,
                )
                if not posted:
                    log.warning(
                        "chat_api_center_bridge: chat-service post failed after sync dispatch trace_id=%s",
                        trace_id,
                    )
            else:
                log.warning(
                    "chat_api_center_bridge: no project member for selected_agent_id=%s",
                    sel_agent,
                )
        return {"ok": True, "trace_id": trace_id, "dispatch": out}
    except ValueError as e:
        log.warning("chat_api_center_bridge dispatch failed: %s", e)
        return {"ok": False, "error": str(e)}


def schedule_dispatch_after_mcp_chat_message(
    *,
    project_id: int,
    target_kind: str,
    channel_name: str | None,
    user_id: int,
    sender_user_id: int,
    sender_name: str | None,
    content: str,
) -> None:
    """Run API Center chat dispatch in a daemon thread (MCP tool must not block on agent wait)."""
    if not _mention_tokens(content):
        return

    def _run() -> None:
        from agile_hub.db import session_scope

        try:
            with session_scope() as db:
                _dispatch_sync(
                    db,
                    project_id=project_id,
                    target_kind=target_kind,
                    channel_name=channel_name,
                    user_id=user_id,
                    sender_user_id=sender_user_id,
                    sender_name=sender_name,
                    content=content,
                )
        except Exception as e:
            log.warning("chat_api_center_bridge background task: %s", e)

    threading.Thread(target=_run, daemon=True).start()


def _dm_room_user_id_from_pair(
    project_id: int,
    channel_id: str,
    human_sender_id: int,
) -> int:
    """Cạnh DM: peer (room.userId) khi biết người gửi tin gốc (human)."""
    m = re.match(rf"^{int(project_id)}_dm_(\d+)_(\d+)$", (channel_id or "").strip())
    if not m:
        return 0
    a, b = int(m.group(1)), int(m.group(2))
    hs = int(human_sender_id or 0)
    if hs == a:
        return b
    if hs == b:
        return a
    return max(a, b)


def ingest_api_center_agent_reply(db: Session, body: dict[str, Any]) -> dict[str, Any]:
    """
    Nhận POST từ API Center (callback HTTP) khi MCP không giao được reply — ghi tin agent vào chat-service.
    Body cùng shape ``reply_payload`` (event, trace_id, project_id, channel_id, content, target_agent_id, metadata.sender).
    """
    project_id = int(str(body.get("project_id") or "0").strip() or "0")
    channel_id = str(body.get("channel_id") or "").strip()
    content = str(body.get("content") or "").strip()
    target_agent_id = _normalize_catalog_agent_id(str(body.get("target_agent_id") or "").strip())
    meta = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    sender = meta.get("sender") if isinstance(meta.get("sender"), dict) else {}
    try:
        human_sender_id = int(sender.get("id") or 0)
    except (TypeError, ValueError):
        human_sender_id = 0

    if project_id <= 0 or not channel_id or not content or not target_agent_id:
        raise ValueError("project_id, channel_id, content, target_agent_id required")

    mmap = crud.project_ai_agent_member_ids_map(db, project_id)
    agent_mid: int | None = None
    for k, v in mmap.items():
        if _normalize_catalog_agent_id(str(k)) == target_agent_id:
            agent_mid = int(v)
            break
    if agent_mid is None or agent_mid <= 0:
        raise ValueError(f"no project AI member for target_agent_id={target_agent_id!r}")

    mem = crud.member_get(db, agent_mid)
    sender_name = ((getattr(mem, "display_name", None) or "").strip() if mem else "") or target_agent_id

    m_dm = re.match(rf"^{project_id}_dm_(\d+)_(\d+)$", channel_id)
    if m_dm:
        room_uid = _dm_room_user_id_from_pair(project_id, channel_id, human_sender_id)
        if room_uid <= 0:
            raise ValueError("invalid DM channel_id")
        posted = _post_agent_reply_to_chat_service(
            project_id=project_id,
            target_kind="private_user",
            channel_name=None,
            user_id=room_uid,
            original_sender_id=human_sender_id,
            agent_member_id=agent_mid,
            sender_name=sender_name,
            content=content,
        )
        if not posted:
            raise ValueError("chat-service refused or unreachable when posting DM reply")
        return {"ok": True, "routed": "private_user", "trace_id": body.get("trace_id")}

    m_pc = re.match(rf"^{project_id}_(.+)$", channel_id)
    if m_pc:
        rest = str(m_pc.group(1) or "").strip()
        if not rest or rest.startswith("dm_"):
            raise ValueError("invalid channel_id for project channel")
        posted = _post_agent_reply_to_chat_service(
            project_id=project_id,
            target_kind="project_channel",
            channel_name=rest,
            user_id=0,
            original_sender_id=human_sender_id or 0,
            agent_member_id=agent_mid,
            sender_name=sender_name,
            content=content,
        )
        if not posted:
            raise ValueError("chat-service refused or unreachable when posting channel reply")
        return {"ok": True, "routed": "project_channel", "trace_id": body.get("trace_id")}

    raise ValueError("channel_id format not recognized (expected {pid}_dm_a_b or {pid}_channelName)")
