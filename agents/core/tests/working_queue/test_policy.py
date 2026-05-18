"""Working queue policy: allowlist, dedupe, priority."""

from __future__ import annotations

from mia.working_queue.policy import (
    agile_notification_should_enqueue,
    build_dedupe_key,
    priority_for_item,
    should_fast_skip_notification,
)
from mia.working_queue.models import WorkingQueueTaskPayload


def test_drop_wiki_comment_deleted() -> None:
    payload = {
        "event_type": "wiki_comment_deleted",
        "project_id": "2",
        "data": {"recipient_hints": {"mentioned_agent_ids": ["mia-ba"]}},
    }
    allow, reason = agile_notification_should_enqueue(payload, "mia-ba")
    assert allow is False
    assert reason == "dropped_event_type"


def test_allow_mention_on_comment() -> None:
    payload = {
        "event_type": "agile_studio.comment.created",
        "data": {"recipient_hints": {"mentioned_agent_ids": ["mia-tech"]}},
    }
    allow, _ = agile_notification_should_enqueue(payload, "mia-tech")
    assert allow is True


def test_priority_chat_before_notification() -> None:
    assert priority_for_item(item_kind="task", source_role="agile_studio_chat", enqueued_by="api-center:chat.dispatch") == 0
    assert priority_for_item(item_kind="notification", source_role="agile_studio_auto", enqueued_by="api-center:webhooks.agile-notifications") == 1


def test_dedupe_key_stable() -> None:
    k = build_dedupe_key(
        project_id="2",
        event_type="wiki_comment_updated",
        agent_id="mia-ba",
        data={"wiki_comment_id": "abc-123"},
    )
    assert k == "2:wiki_comment_updated:abc-123:mia-ba"


def test_fast_skip_reclaimed_noise() -> None:
    task = WorkingQueueTaskPayload(
        id="x",
        project_id="2",
        message="noise",
        item_kind="notification",
        source_role="agile_studio_auto",
        context={
            "webhook_payload": {"event_type": "wiki_comment_deleted", "data": {}},
            "routing": {"target_agent_id": "mia-ba"},
        },
    )
    assert should_fast_skip_notification(task) is True
