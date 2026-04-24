"""Pydantic models for working-queue JSON tasks (file-based, per agent workspace)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


QueueItemKind = Literal["task", "notification"]
"""``task`` = actionable work. ``notification`` = signal to read/ack; not a default full delivery brief."""


class WorkingQueueTaskPayload(BaseModel):
    """Queued item (task or notification) in ``pending/<id>.json`` (and preserved in done/failed)."""

    model_config = ConfigDict(extra="allow")

    id: str
    project_id: str = Field(
        ...,
        min_length=1,
        description="Project or stream id — used to isolate session history (working:<id>).",
    )
    message: str = Field(..., min_length=1, description="What the next AI must do (e.g. BA handoff).")
    source_role: str = Field(
        default="user",
        description="Who enqueued the task (e.g. ba, tech, user).",
    )
    service: str | None = Field(default=None, description="Optional service / module name.")
    context: dict[str, Any] = Field(default_factory=dict, description="Structured project context (JSON).")
    status: Literal["pending", "processing", "done", "failed"] = "pending"
    created_at: str = Field(default_factory=utcnow_iso)
    enqueued_by: str | None = Field(default=None, description="Channel:chat or tool:working_queue_submit")
    item_kind: QueueItemKind = Field(
        default="task",
        description="task = do the work. notification = internal/event ping — acknowledge briefly, do not treat as a full execution mandate unless the text explicitly requires action.",
    )
    # Filled when finished
    completed_at: str | None = None
    error: str | None = None
    result_excerpt: str | None = None

    @field_validator("project_id", "message", mode="before")
    @classmethod
    def strip_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


def parse_task_file(raw: str) -> WorkingQueueTaskPayload:
    data = json.loads(raw)
    return WorkingQueueTaskPayload.model_validate(data)


def task_to_json(task: WorkingQueueTaskPayload) -> str:
    return task.model_dump_json(indent=2, ensure_ascii=False)
