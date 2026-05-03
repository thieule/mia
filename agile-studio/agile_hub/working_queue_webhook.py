"""
Gửi payload tới dịch vụ working queue webhook (POST /v1/working-queue/tasks),
tương thích tài liệu workflow-runtime / mia WorkingQueueTaskPayload.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


def resolve_working_queue_post_url(raw: str) -> str:
    """Nếu user chỉ nhập base (vd. http://host:18880), nối thêm path chuẩn."""
    t = raw.strip().rstrip("/")
    if not t:
        return t
    if "working-queue" in t:
        return t
    return f"{t}/v1/working-queue/tasks"


def parse_webhook_config(settings_json: dict | None) -> tuple[str, str, str] | None:
    """
    Trả về (post_url, bearer_secret, agent_id) nếu đủ cả ba;
    post_url đã qua ``resolve_working_queue_post_url``.
    """
    if not settings_json or not isinstance(settings_json, dict):
        return None

    def s(key: str) -> str | None:
        v = settings_json.get(key)
        if v is None:
            return None
        t = str(v).strip()
        return t or None

    url = s("ai_working_queue_url")
    sec = s("ai_working_queue_secret")
    aid = s("ai_working_queue_agent_id")
    if not url or not sec or not aid:
        return None
    return (resolve_working_queue_post_url(url), sec, aid)


def post_working_queue_task(post_url: str, bearer_token: str, payload: dict[str, Any], *, timeout_s: float = 30.0) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        post_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {bearer_token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if resp.status not in (200, 201, 202):
                log.warning(
                    "working_queue_webhook: HTTP %s từ %s",
                    resp.status,
                    post_url,
                )
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:
            detail = ""
        log.warning(
            "working_queue_webhook: HTTP %s %s — %s",
            e.code,
            post_url,
            detail or e.reason,
        )
    except Exception as e:
        log.warning("working_queue_webhook: gọi thất bại %s — %s", post_url, e)


def build_payload_new_story(
    *,
    agent_id: str,
    project_slug: str,
    project_name: str,
    story_key: str,
    title: str,
    description: str | None,
    status: str,
) -> dict[str, Any]:
    desc = (description or "").strip()
    msg = f"New story [{story_key}]: {title}"
    if desc:
        msg = f"{msg}\n\n{desc}"
    return {
        "agent_id": agent_id,
        "project_id": project_slug,
        "project_name": project_name,
        "message": msg,
        "source_role": "agile_studio",
        "service": "agile_hub",
        "item_kind": "task",
        "context": {
            "event": "story_created",
            "story_key": story_key,
            "story_status": status,
        },
        "stories": [
            {
                "id": story_key,
                "title": title,
                "status": status,
            }
        ],
    }


def build_payload_story_comment(
    *,
    agent_id: str,
    project_slug: str,
    project_name: str,
    story_key: str,
    story_title: str,
    story_status: str,
    comment_body: str,
    author_display_name: str,
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "project_id": project_slug,
        "project_name": project_name,
        "message": f"Comment on [{story_key}] {story_title}\n\n{comment_body}",
        "source_role": "agile_studio",
        "service": "agile_hub",
        "item_kind": "notification",
        "context": {
            "event": "story_comment",
            "author": author_display_name,
        },
        "project": {
            "id": project_slug,
            "name": project_name,
        },
        "story": {
            "id": story_key,
            "title": story_title,
            "status": story_status,
        },
    }


def background_new_story(
    post_url: str,
    bearer: str,
    agent_id: str,
    project_slug: str,
    project_name: str,
    story_key: str,
    title: str,
    description: str | None,
    status: str,
) -> None:
    """Dùng với FastAPI BackgroundTasks — không ném ngoại lệ ra API."""
    p = build_payload_new_story(
        agent_id=agent_id,
        project_slug=project_slug,
        project_name=project_name,
        story_key=story_key,
        title=title,
        description=description,
        status=status,
    )
    post_working_queue_task(post_url, bearer, p)


def background_story_comment(
    post_url: str,
    bearer: str,
    agent_id: str,
    project_slug: str,
    project_name: str,
    story_key: str,
    story_title: str,
    story_status: str,
    comment_body: str,
    author_display_name: str,
) -> None:
    p = build_payload_story_comment(
        agent_id=agent_id,
        project_slug=project_slug,
        project_name=project_name,
        story_key=story_key,
        story_title=story_title,
        story_status=story_status,
        comment_body=comment_body,
        author_display_name=author_display_name,
    )
    post_working_queue_task(post_url, bearer, p)
