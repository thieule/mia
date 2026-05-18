"""Pending claim order: priority 0 before 1."""

from __future__ import annotations

from mia.working_queue.models import WorkingQueueTaskPayload, task_to_json
from mia.working_queue.store import WorkingQueueStore, submit_task


def test_claim_prefers_low_priority_number(tmp_path) -> None:
    import os
    import time

    store = WorkingQueueStore(tmp_path / "wq", priority_enabled=True)
    submit_task(store, project_id="p", message="notification", item_kind="notification", priority=1)
    submit_task(store, project_id="p", message="chat task", item_kind="task", priority=0)
    # Make the high-priority (0) file newer; claim should still pick priority 0 first.
    paths = store.list_pending_paths()
    by_msg = {}
    for p in paths:
        by_msg[store.load(p).message] = p
    os.utime(by_msg["notification"], (time.time() - 100, time.time() - 100))
    os.utime(by_msg["chat task"], (time.time(), time.time()))

    claimed = store.claim_oldest_pending()
    assert claimed is not None
    _path, task = claimed
    assert task.priority == 0
    assert task.message == "chat task"
