"""Gọi chat-service khi dữ liệu project/member thay đổi (server-to-server)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


def notify_chat_project_created(project_id: int) -> None:
    """
    Sau khi tạo project: đảm bảo có channel `general`.
    Bỏ qua nếu không cấu hình AGILE_CHAT_SERVICE_URL.
    """
    base = (os.environ.get("AGILE_CHAT_SERVICE_URL") or "").strip().rstrip("/")
    if not base:
        return
    url = f"{base}/api/chat/internal/channels/ensure-after-project-created"
    payload = json.dumps({"projectId": project_id}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                logger.warning("chat_sync project_created: HTTP %s %s", resp.status, url)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        logger.warning("chat_sync project_created failed HTTP %s: %s", e.code, body)
    except urllib.error.URLError as e:
        logger.warning("chat_sync project_created unreachable %s: %s", url, e.reason)
    except Exception:
        logger.exception("chat_sync project_created unexpected error url=%s", url)


def notify_chat_member_added(project_id: int, member_id: int) -> None:
    """
    Sau POST /projects/{id}/members: tạo kênh general (nếu thiếu) + kênh DM với mọi member khác.
    Bỏ qua nếu không cấu hình AGILE_CHAT_SERVICE_URL.
    """
    base = (os.environ.get("AGILE_CHAT_SERVICE_URL") or "").strip().rstrip("/")
    if not base:
        return
    url = f"{base}/api/chat/internal/channels/ensure-after-member-added"
    payload = json.dumps({"projectId": project_id, "memberId": member_id}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                logger.warning("chat_sync member_added: HTTP %s %s", resp.status, url)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        logger.warning("chat_sync member_added failed HTTP %s: %s", e.code, body)
    except urllib.error.URLError as e:
        logger.warning("chat_sync member_added unreachable %s: %s", url, e.reason)
    except Exception:
        logger.exception("chat_sync member_added unexpected error url=%s", url)


def notify_story_chat_event(project_id: int, story_id: int, event_type: str, payload: dict) -> None:
    """
    Broadcast story activity (comments, …) qua chat-service WebSocket (`chat:event`).
    Clients join room `{projectId}_story_{storyId}` (same mechanism as `chat:join`).
    """
    base = (os.environ.get("AGILE_CHAT_SERVICE_URL") or "").strip().rstrip("/")
    if not base:
        return
    url = f"{base}/api/chat/internal/story-events/broadcast"
    body_obj = {"projectId": project_id, "storyId": story_id, "eventType": event_type, "payload": payload}
    payload_b = json.dumps(body_obj).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload_b,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                logger.warning("chat_sync story_event: HTTP %s %s", resp.status, url)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        logger.warning("chat_sync story_event failed HTTP %s: %s", e.code, body)
    except urllib.error.URLError as e:
        logger.warning("chat_sync story_event unreachable %s: %s", url, e.reason)
    except Exception:
        logger.exception("chat_sync story_event unexpected error url=%s", url)


def notify_wiki_doc_chat_event(project_id: int, doc_id: str, event_type: str, payload: dict) -> None:
    """Broadcast wiki feedback (`chat:event`) tới room `{projectId}_wiki_doc_{docId}`."""
    base = (os.environ.get("AGILE_CHAT_SERVICE_URL") or "").strip().rstrip("/")
    did = str(doc_id or "").strip()
    if not base or not did:
        return
    url = f"{base}/api/chat/internal/wiki-doc-events/broadcast"
    body_obj = {"projectId": project_id, "docId": did, "eventType": event_type, "payload": payload}
    payload_b = json.dumps(body_obj).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload_b,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                logger.warning("chat_sync wiki_doc_event: HTTP %s %s", resp.status, url)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        logger.warning("chat_sync wiki_doc_event failed HTTP %s: %s", e.code, body)
    except urllib.error.URLError as e:
        logger.warning("chat_sync wiki_doc_event unreachable %s: %s", url, e.reason)
    except Exception:
        logger.exception("chat_sync wiki_doc_event unexpected error url=%s", url)
