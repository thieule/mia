"""Working queue: reclaim orphaned processing tasks on restart."""

from __future__ import annotations

import json
from pathlib import Path

from mia.working_queue.models import WorkingQueueTaskPayload, task_to_json
from mia.working_queue.store import WorkingQueueStore, submit_task


def _write_processing(store: WorkingQueueStore, task: WorkingQueueTaskPayload) -> Path:
    task.status = "processing"
    path = store.processing / f"{task.id}.json"
    path.write_text(task_to_json(task), encoding="utf-8")
    return path


def test_reclaim_moves_processing_to_pending(tmp_path: Path) -> None:
    store = WorkingQueueStore(tmp_path / "working_queue")
    task_id = submit_task(
        store,
        project_id="p1",
        message="do something",
        enqueued_by="test",
    )
    pending_path = store.pending / f"{task_id}.json"
    task = store.load(pending_path)
    store.move_to(pending_path, store.processing)
    proc_path = store.processing / f"{task_id}.json"
    proc_path.write_text(task_to_json(task.model_copy(update={"status": "processing"})), encoding="utf-8")

    reclaimed = store.reclaim_processing_on_restart()

    assert reclaimed == [task_id]
    assert not proc_path.exists()
    assert (store.pending / f"{task_id}.json").is_file()
    back = store.load(store.pending / f"{task_id}.json")
    assert back.status == "pending"
    assert back.completed_at is None
    assert back.error is None


def test_reclaim_skips_when_pending_already_exists(tmp_path: Path) -> None:
    store = WorkingQueueStore(tmp_path / "working_queue")
    task_id = submit_task(store, project_id="p1", message="pending copy")
    _write_processing(
        store,
        WorkingQueueTaskPayload(
            id=task_id,
            project_id="p1",
            message="stale processing copy",
            status="processing",
        ),
    )

    reclaimed = store.reclaim_processing_on_restart()

    assert reclaimed == []
    assert (store.pending / f"{task_id}.json").is_file()
    assert (store.processing / f"{task_id}.json").is_file()


def test_reclaim_appends_ledger_event(tmp_path: Path) -> None:
    store = WorkingQueueStore(tmp_path / "working_queue")
    task_id = submit_task(store, project_id="p1", message="ledger test")
    proc = store.processing / f"{task_id}.json"
    store.move_to(store.pending / f"{task_id}.json", store.processing)
    task = store.load(proc)
    proc.write_text(task_to_json(task.model_copy(update={"status": "processing"})), encoding="utf-8")

    store.reclaim_processing_on_restart()

    lines = store.ledger.read_text(encoding="utf-8").strip().splitlines()
    last = json.loads(lines[-1])
    assert last["event"] == "reclaimed"
    assert last["id"] == task_id
    assert last["status"] == "pending"
