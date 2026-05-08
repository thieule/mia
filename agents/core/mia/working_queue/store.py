"""Filesystem store for working-queue JSON files."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from mia.utils.helpers import ensure_dir, safe_filename

from mia.working_queue.models import (
    QueueItemKind,
    WorkingQueueTaskPayload,
    parse_task_file,
    task_to_json,
    utcnow_iso,
)


def _write_json_atomic(path: Path, data: Any) -> None:
    if isinstance(data, (dict, list)):
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        text = str(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class WorkingQueueStore:
    """
    Layout under *base* (usually ``<workspace>/working_queue``)::

        pending/   — new tasks (JSON)
        processing/ — claimed by consumer
        done/      — completed
        failed/    — bad JSON or execution error
        projects/<safe_project_id>/ — optional per-project notes (e.g. last_done)
        state/     — index + snapshots (same tree as the queue)::

            summary.json   — counts per phase + updated_at
            items/<id>.json — per-item status + result/error preview
            ledger.jsonl   — append-only JSON lines (submitted → processing → done/failed)
    """

    def __init__(self, base: Path) -> None:
        self.base = base
        self.pending = ensure_dir(base / "pending")
        self.processing = ensure_dir(base / "processing")
        self.done = ensure_dir(base / "done")
        self.failed = ensure_dir(base / "failed")
        self.projects = ensure_dir(base / "projects")
        self.state = ensure_dir(base / "state")
        self.state_items = ensure_dir(self.state / "items")
        self.ledger = self.state / "ledger.jsonl"

    def project_dir(self, project_id: str) -> Path:
        return ensure_dir(self.projects / safe_filename(project_id))

    def _rel_to_base(self, file_path: Path) -> str:
        try:
            return file_path.resolve().relative_to(self.base.resolve()).as_posix()
        except ValueError:
            return file_path.name

    def _refresh_summary(self) -> None:
        def _count_json(d: Path) -> int:
            if not d.is_dir():
                return 0
            return sum(1 for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".json")

        s = {
            "updated_at": utcnow_iso(),
            "base": str(self.base.resolve()),
            "counts": {
                "pending": _count_json(self.pending),
                "processing": _count_json(self.processing),
                "done": _count_json(self.done),
                "failed": _count_json(self.failed),
            },
        }
        _write_json_atomic(self.state / "summary.json", s)

    def write_item_status(
        self,
        task: WorkingQueueTaskPayload,
        *,
        location: str,
        file_path: Path,
    ) -> None:
        """``location`` is pending | processing | done | failed. Writes ``state/items/<id>.json``."""
        msg = task.message
        if len(msg) > 2000:
            msg = msg[:2000] + "…"
        rec: dict[str, Any] = {
            "id": task.id,
            "project_id": task.project_id,
            "item_kind": getattr(task, "item_kind", "task"),
            "status": task.status,
            "location": location,
            "file": self._rel_to_base(file_path),
            "created_at": task.created_at,
            "updated_at": utcnow_iso(),
            "enqueued_by": task.enqueued_by,
            "source_role": task.source_role,
            "message_preview": msg,
        }
        if task.service is not None:
            rec["service"] = task.service
        if task.completed_at is not None:
            rec["completed_at"] = task.completed_at
        if task.error:
            rec["error"] = task.error[:16_000]
        if task.result_excerpt:
            rec["result_excerpt"] = task.result_excerpt[:12_000]
        _write_json_atomic(self.state_items / f"{task.id}.json", rec)
        self._refresh_summary()

    def read_summary(self) -> dict[str, Any] | None:
        """Return parsed ``state/summary.json`` if it exists, else None."""
        p = self.state / "summary.json"
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def _append_ledger(
        self,
        event: str,
        task: WorkingQueueTaskPayload,
        extra: dict[str, Any] | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "t": utcnow_iso(),
            "event": event,
            "id": task.id,
            "project_id": task.project_id,
            "item_kind": getattr(task, "item_kind", "task"),
            "status": task.status,
        }
        if extra:
            row.update(extra)
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex

    def list_pending_paths(self) -> list[Path]:
        files = [p for p in self.pending.iterdir() if p.is_file() and p.suffix.lower() == ".json"]
        files.sort(key=lambda p: p.stat().st_mtime)
        return files

    def write_pending_atomic(self, task: WorkingQueueTaskPayload) -> Path:
        dest = self.pending / f"{task.id}.json"
        tmp = self.pending / f".{task.id}.json.{os.getpid()}.tmp"
        tmp.write_text(task_to_json(task), encoding="utf-8")
        tmp.replace(dest)
        self.write_item_status(task, location="pending", file_path=dest)
        self._append_ledger("submitted", task, {"file": self._rel_to_base(dest)})
        return dest

    def load(self, path: Path) -> WorkingQueueTaskPayload:
        return parse_task_file(path.read_text(encoding="utf-8"))

    def move_to(self, src: Path, dest_dir: Path, same_name: bool = True) -> Path:
        dest_dir = ensure_dir(dest_dir)
        dest = dest_dir / src.name if same_name else dest_dir
        try:
            src.replace(dest)
        except OSError:
            # Windows / cross-device: copy + unlink
            dest.write_bytes(src.read_bytes())
            src.unlink(missing_ok=True)
        return dest

    def claim_oldest_pending(self) -> tuple[Path, WorkingQueueTaskPayload] | None:
        for path in self.list_pending_paths():
            try:
                proc = self.processing / path.name
                try:
                    path.replace(proc)
                except OSError:
                    proc.write_bytes(path.read_bytes())
                    path.unlink(missing_ok=True)
                task = self.load(proc)
                task.status = "processing"
                proc.write_text(task_to_json(task), encoding="utf-8")
                self.write_item_status(task, location="processing", file_path=proc)
                self._append_ledger("processing", task, {"file": self._rel_to_base(proc)})
                return proc, task
            except FileNotFoundError:
                continue
            except (json.JSONDecodeError, OSError, ValueError) as e:
                try:
                    if path.is_file():
                        self.move_to(path, self.failed)
                except Exception:
                    pass
                logger.exception("Working queue: invalid task file {}: {}", path, e)
        return None

    def mark_done(
        self,
        processing_path: Path,
        task: WorkingQueueTaskPayload,
        *,
        result_excerpt: str | None = None,
    ) -> None:
        task.status = "done"
        task.completed_at = utcnow_iso()
        task.result_excerpt = (result_excerpt or "")[:32_000]
        out = self.done / processing_path.name
        out.write_text(task_to_json(task), encoding="utf-8")
        processing_path.unlink(missing_ok=True)
        # Optional: tiny index for the project
        pdir = self.project_dir(task.project_id)
        (pdir / "last_done.json").write_text(task_to_json(task), encoding="utf-8")
        self.write_item_status(task, location="done", file_path=out)
        self._append_ledger("done", task, {"file": self._rel_to_base(out)})

    def mark_failed(
        self,
        processing_path: Path,
        task: WorkingQueueTaskPayload,
        error: str,
    ) -> None:
        task.status = "failed"
        task.completed_at = utcnow_iso()
        task.error = error[:16_000]
        out = self.failed / processing_path.name
        out.write_text(task_to_json(task), encoding="utf-8")
        processing_path.unlink(missing_ok=True)
        self.write_item_status(task, location="failed", file_path=out)
        self._append_ledger("failed", task, {"file": self._rel_to_base(out)})


def submit_task(
    store: WorkingQueueStore,
    *,
    project_id: str,
    message: str,
    source_role: str = "user",
    service: str | None = None,
    context: dict[str, Any] | None = None,
    enqueued_by: str | None = None,
    item_kind: str | QueueItemKind = "task",
) -> str:
    """Create a new pending task; returns task id. ``item_kind`` is ``task`` or ``notification``."""
    k = (str(item_kind or "task")).strip()
    if k not in ("task", "notification"):
        k = "task"
    ik: QueueItemKind = k
    task_id = WorkingQueueStore.new_id()
    task = WorkingQueueTaskPayload(
        id=task_id,
        project_id=project_id,
        message=message,
        source_role=source_role,
        service=service,
        context=context or {},
        enqueued_by=enqueued_by,
        item_kind=ik,
    )
    store.write_pending_atomic(task)
    return task_id
