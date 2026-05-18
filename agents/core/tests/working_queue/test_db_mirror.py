"""DB mirror: ensure agent row before task; events only after task exists."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mia.working_queue.db_mirror import WorkingQueueDbMirror
from mia.working_queue.models import WorkingQueueTaskPayload


def test_append_event_skips_when_task_missing(monkeypatch) -> None:
    monkeypatch.setenv("MIA_AGENT_DATABASE_URL", "mysql+pymysql://u:p@127.0.0.1:3307/agent")
    mirror = WorkingQueueDbMirror(agent_id="mia-ba", enabled=True)
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    ctx = MagicMock()
    ctx.__enter__.return_value = conn
    ctx.__exit__.return_value = None
    with patch.object(mirror, "_connect", return_value=ctx):
        mirror.append_event("missing-task", "submitted", {"file": "pending/x.json"})
    cur.execute.assert_called_once()
    assert "SELECT 1" in cur.execute.call_args[0][0]


def test_record_event_does_not_append_when_upsert_fails(monkeypatch) -> None:
    monkeypatch.setenv("MIA_AGENT_DATABASE_URL", "mysql+pymysql://u:p@127.0.0.1:3307/agent")
    mirror = WorkingQueueDbMirror(agent_id="mia-ba", enabled=True)
    task = WorkingQueueTaskPayload(id="t1", project_id="1", message="hi")
    with patch.object(mirror, "upsert_task", return_value=False) as up:
        with patch.object(mirror, "append_event") as ev:
            mirror.record_event(task, location="pending", file_rel="pending/t1.json", event="submitted")
    up.assert_called_once()
    ev.assert_not_called()
