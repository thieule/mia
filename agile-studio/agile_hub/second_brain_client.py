"""Fire-and-forget ingest to Second Brain MCP (optional)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger(__name__)


def post_agile_event_to_second_brain(
    *,
    event_type: str,
    project_id: int,
    project_name: str | None,
    summary: str,
    changed_fields: list[str],
    data: dict[str, Any],
) -> None:
    url = (os.environ.get("AGILE_SECOND_BRAIN_INGEST_URL") or "").strip()
    if not url:
        return
    secret = (os.environ.get("AGILE_SECOND_BRAIN_INGEST_SECRET") or "").strip()
    if not secret:
        log.debug("second_brain ingest: AGILE_SECOND_BRAIN_INGEST_SECRET empty, skip")
        return
    body = json.dumps(
        {
            "event_type": event_type,
            "project_id": project_id,
            "project_name": project_name,
            "summary": summary,
            "changed_fields": changed_fields,
            "data": data,
        },
        default=str,
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    req.add_header("X-Second-Brain-Secret", secret)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status >= 400:
                log.warning("second_brain ingest HTTP %s for %s", resp.status, event_type)
    except urllib.error.HTTPError as e:
        log.warning("second_brain ingest HTTPError %s for %s", e.code, event_type)
    except urllib.error.URLError as e:
        log.debug("second_brain ingest URLError for %s: %s", event_type, e)
    except Exception:
        log.exception("second_brain ingest failed for %s", event_type)
