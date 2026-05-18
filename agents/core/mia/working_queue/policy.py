"""Working-queue policy: priority, Agile allowlist, dedupe keys, fast-skip heuristics."""

from __future__ import annotations

import os
from typing import Any

# Noise — never enqueue as agent notifications
_DEFAULT_DROP_EVENT_TYPES = frozenset(
    {
        "wiki_comment_deleted",
    }
)

# Low-signal project churn (no @mention / assignee required to drop)
_DEFAULT_LOW_SIGNAL_EVENT_TYPES = frozenset(
    {
        "story_updated",
        "story_status_changed",
        "wiki_document_updated",
    }
)

_HIGH_SIGNAL_EVENT_TYPES = frozenset(
    {
        "agile_studio.comment.created",
        "agile_studio.comment.updated",
        "agile_studio.task_comment.created",
        "agile_studio.task_comment.updated",
        "wiki_comment_created",
        "wiki_comment_updated",
    }
)


def _parse_csv_env(name: str, default: frozenset[str]) -> frozenset[str]:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def drop_event_types() -> frozenset[str]:
    return _parse_csv_env("MIA_WQ_DROP_EVENT_TYPES", _DEFAULT_DROP_EVENT_TYPES)


def low_signal_event_types() -> frozenset[str]:
    return _parse_csv_env("MIA_WQ_LOW_SIGNAL_EVENT_TYPES", _DEFAULT_LOW_SIGNAL_EVENT_TYPES)


def priority_for_item(*, item_kind: str, source_role: str, enqueued_by: str | None) -> int:
    """Lower number = claimed earlier. 0 = user chat / actionable task."""
    if (item_kind or "task").strip().lower() != "task":
        return 1
    sr = (source_role or "").strip()
    eb = (enqueued_by or "").strip()
    if sr == "agile_studio_chat" or eb.startswith("api-center:chat"):
        return 0
    if eb.startswith("tool:working_queue_submit"):
        return 0
    return 0


def build_dedupe_key(
    *,
    project_id: str,
    event_type: str,
    agent_id: str,
    data: dict[str, Any] | None,
) -> str | None:
    """Stable key for coalescing duplicate Agile notifications."""
    et = (event_type or "").strip()
    if not et or not (project_id or "").strip() or not (agent_id or "").strip():
        return None
    d = data if isinstance(data, dict) else {}
    entity = (
        d.get("wiki_comment_id")
        or d.get("task_id")
        or d.get("story_id")
        or d.get("wiki_document_id")
        or d.get("doc_id")
    )
    if entity is None:
        return None
    return f"{project_id.strip()}:{et}:{entity}:{agent_id.strip().lower()}"


def _agent_in_hints(agent_id: str, hints: dict[str, Any]) -> bool:
    aid = agent_id.strip().lower()
    if not aid:
        return False
    mentioned = hints.get("mentioned_agent_ids")
    if isinstance(mentioned, list):
        if aid in {str(x).strip().lower() for x in mentioned if str(x).strip()}:
            return True
    assignees = hints.get("story_assignee_agent_ids")
    if isinstance(assignees, list):
        if aid in {str(x).strip().lower() for x in assignees if str(x).strip()}:
            return True
    return False


def agile_notification_should_enqueue(payload: dict[str, Any], agent_id: str) -> tuple[bool, str]:
    """
  Return (allow_enqueue, reason_code).
  Used at API Center before writing pending JSON.
  """
    et = str(payload.get("event_type") or payload.get("eventType") or "").strip()
    if not et:
        return False, "missing_event_type"
    if et in drop_event_types():
        return False, "dropped_event_type"
    if et.endswith(".deleted") or et.endswith("_deleted"):
        return False, "deleted_event"

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    hints = data.get("recipient_hints") if isinstance(data.get("recipient_hints"), dict) else {}
    aid = str(agent_id or "").strip()
    if not aid:
        return False, "missing_agent_id"

    if et in _HIGH_SIGNAL_EVENT_TYPES:
        if _agent_in_hints(aid, hints):
            return True, "high_signal_recipient"
        return False, "high_signal_no_recipient"

    if et in low_signal_event_types():
        if _agent_in_hints(aid, hints):
            return True, "low_signal_recipient"
        return False, "low_signal_no_recipient"

    if _agent_in_hints(aid, hints):
        return True, "recipient_hint"

    return False, "default_skip"


def should_fast_skip_notification(task: Any) -> bool:
    """
    Skip full LLM run for notifications that policy would not have enqueued
    (e.g. stuck reclaim of old noise). Only for agile_studio_auto notifications.
  """
    if getattr(task, "item_kind", "task") != "notification":
        return False
    sr = (getattr(task, "source_role", "") or "").strip()
    if sr not in ("agile_studio_auto", "agile_studio_webhook"):
        return False
    ctx = getattr(task, "context", None)
    if not isinstance(ctx, dict):
        return False
    wp = ctx.get("webhook_payload")
    if not isinstance(wp, dict):
        return False
    routing = ctx.get("routing") if isinstance(ctx.get("routing"), dict) else {}
    aid = str(routing.get("target_agent_id") or "").strip()
    if not aid:
        return False
    allow, _ = agile_notification_should_enqueue(wp, aid)
    return not allow
