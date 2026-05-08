"""
Fan-out Agile Studio events to API Center.

- Prioritize fan-out only to agents **that are AI members of the project** (``agent_id`` matches catalog).
- If the project has no AI members with ``agent_id``: keep legacy behavior — send all agents in catalog
  (avoid losing notifications when AI is not assigned to the project).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from . import api_center_client, crud, models

log = logging.getLogger(__name__)


def wiki_comment_webhook_data_dict(
    db: Session,
    project_id: int,
    doc: models.WikiDocument,
    row: models.WikiComment,
    author_member_id: int,
) -> dict[str, Any]:
    """Payload ``data`` for ``wiki_comment_*`` webhook / API Center (matches router fanout shape)."""
    return {
        "wiki_document_id": doc.id,
        "wiki_comment_id": row.id,
        "wiki_thread_root_id": row.parent_id or row.id,
        "doc_slug": doc.slug,
        "doc_title": doc.title,
        "author_member_id": author_member_id,
        "content_preview": (row.content or "")[:600],
        "quote_preview": (row.quote or "")[:400],
        "parent_comment_id": row.parent_id,
        "quoted_comment_id": getattr(row, "quoted_comment_id", None),
        "quoted_excerpt_preview": ((getattr(row, "quoted_excerpt", None) or "")[:400]),
        "recipient_hints": crud.recipient_hints_for_wiki_comment(
            db,
            project_id,
            doc,
            comment_body=row.content,
            author_member_id=author_member_id,
        ),
    }


def project_allows_api_center_event_fanout(p: models.Project) -> bool:
    raw = getattr(p, "settings_json", None)
    if not raw or not isinstance(raw, dict):
        return True
    v = raw.get("agile_event_notifications_enabled")
    if v is None:
        return True
    return bool(v)


def _dedupe_agent_ids(rows: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for a in rows:
        aid = str((a or {}).get("id") or "").strip()
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append(aid)
    return out


def forward_webhook_to_api_center(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Gọi API Center (có reconnect khi 401). Dùng từ route HTTP; ném ValueError
    nếu chưa kết nối hoặc lỗi chuyển tiếp.
    """
    row = crud.api_center_connection_get(db)
    if row is None or not (row.session_key or "").strip():
        raise ValueError("API Center is not connected")
    return _webhook_with_reconnect(db, row, payload)


def _webhook_with_reconnect(
    db: Session,
    row: models.ApiCenterConnection,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        return api_center_client.webhook_agile_notifications(
            row.endpoint, row.session_key or "", payload
        )
    except ValueError as e:
        msg = str(e)
        if "HTTP 401" in msg and (row.connect_secret or "").strip():
            try:
                reconnect_info = api_center_client.reconnect_session_info(
                    row.endpoint, row.connect_secret
                )
                new_sk = str(reconnect_info.get("session_key") or "")
                crud.api_center_connection_upsert(
                    db,
                    endpoint=row.endpoint,
                    connect_secret=row.connect_secret,
                    session_key=new_sk,
                    api_endpoints=reconnect_info.get("endpoints")
                    if isinstance(reconnect_info.get("endpoints"), dict)
                    else {},
                )
                return api_center_client.webhook_agile_notifications(
                    row.endpoint, new_sk, payload
                )
            except ValueError as e2:
                raise ValueError(str(e2)) from e2
        raise


def _fanout_payload(
    *,
    project_id: int,
    project_name: str | None,
    event_type: str,
    summary: str,
    changed_fields: list[str],
    data: dict[str, Any],
    agent_ids: list[str],
) -> dict[str, Any]:
    trace_id = f"as_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    return {
        "trace_id": trace_id,
        "event_type": event_type,
        "project_id": str(project_id),
        "project_name": project_name,
        "summary": summary,
        "changed_fields": changed_fields,
        "agent_ids": agent_ids,
        "item_kind": "notification",
        "source_role": "agile_studio_auto",
        "service": "agile-studio",
        "data": data,
    }


def run_fanout_for_agile_studio_event(
    project_id: int,
    project_name: str | None,
    event_type: str,
    summary: str,
    changed_fields: list[str],
    data: dict[str, Any],
) -> None:
    """
    Chạy sau response (BackgroundTasks): mở session mới, gom agent_id từ API Center, gửi một payload.
    """
    from .db import session_scope

    with session_scope() as db:
        try:
            p = crud.project_get(db, project_id)
            if p is None:
                log.debug("api_center fanout: project %s missing", project_id)
                return
            if not project_allows_api_center_event_fanout(p):
                return
            row = crud.api_center_connection_get(db)
            if row is None or not (row.session_key or "").strip():
                log.debug("api_center fanout: not connected, skip %s", event_type)
                return
            try:
                agents = api_center_client.list_agents(row.endpoint, row.session_key or "")
            except ValueError as e:
                log.warning("api_center fanout: list_agents failed: %s", e)
                return
            catalog_ids = _dedupe_agent_ids(agents)
            if not catalog_ids:
                log.info("api_center fanout: no agents in catalog, skip %s", event_type)
                return
            project_agents = crud.project_ai_agent_catalog_ids(db, project_id)
            if project_agents:
                want = {a.strip().lower() for a in project_agents}
                agent_ids = [a for a in catalog_ids if str(a).strip().lower() in want]
                if not agent_ids:
                    log.info(
                        "api_center fanout: no catalog agents match project AI members, skip %s",
                        event_type,
                    )
                    return
            else:
                agent_ids = catalog_ids
            et = (event_type or "").strip()
            if et in {"wiki_comment_created", "wiki_comment_updated"}:
                hints = data.get("recipient_hints") if isinstance(data.get("recipient_hints"), dict) else {}
                menc_raw = hints.get("mentioned_agent_ids")
                menc_l = (
                    {str(x).strip().lower() for x in menc_raw if str(x).strip()}
                    if isinstance(menc_raw, list)
                    else set()
                )
                if not menc_l:
                    log.debug(
                        "api_center fanout: %s — no AI @mentions in wiki comment, skip agent dispatch",
                        et,
                    )
                    return
                agent_ids = [a for a in agent_ids if str(a).strip().lower() in menc_l]
                if not agent_ids:
                    log.info(
                        "api_center fanout: %s — mentioned agents not in project/catalog, skip",
                        et,
                    )
                    return
            payload = _fanout_payload(
                project_id=project_id,
                project_name=project_name or p.name,
                event_type=event_type,
                summary=summary,
                changed_fields=changed_fields,
                data=data,
                agent_ids=agent_ids,
            )
            out = _webhook_with_reconnect(db, row, payload)
            log.debug(
                "api_center fanout: %s project_id=%s routed_count=%s",
                event_type,
                project_id,
                (out or {}).get("routed_count"),
            )
        except Exception:
            log.exception(
                "api_center fanout failed: event=%s project_id=%s", event_type, project_id
            )


def schedule_api_center_event_fanout(
    background_tasks: BackgroundTasks,
    *,
    project_id: int,
    project_name: str | None,
    event_type: str,
    summary: str,
    changed_fields: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    background_tasks.add_task(
        run_fanout_for_agile_studio_event,
        project_id,
        project_name,
        event_type,
        summary,
        changed_fields or [],
        data or {},
    )
