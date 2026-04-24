"""Build the user message body for a working-queue run."""

from __future__ import annotations

import json

from mia.utils.helpers import safe_filename, truncate_text

from mia.working_queue.models import WorkingQueueTaskPayload


def _shared_meta_lines(task: WorkingQueueTaskPayload) -> list[str]:
    out = [
        f"Queue file id: {task.id}",
        f"Project id: {task.project_id}",
    ]
    if task.service:
        out.append(f"Service / module: {task.service}")
    if task.source_role:
        out.append(f"Handoff from role: {task.source_role}")
    if task.enqueued_by:
        out.append(f"Enqueued by: {task.enqueued_by}")
    if task.context:
        out.append("Context (JSON):")
        out.append(json.dumps(task.context, ensure_ascii=False, indent=2))
    return out


def build_process_prompt(task: WorkingQueueTaskPayload) -> str:
    kind = task.item_kind if task.item_kind in ("task", "notification") else "task"

    if kind == "notification":
        lines: list[str] = [
            "[Working queue — NOTIFICATION] This item is a **notification / signal**, not a full work-task handoff.",
            "Treat it as information to read, possibly acknowledge, and only take substantive action if the text explicitly requires it. Prefer a **short** reply: what you noted, and any one follow-up you recommend.",
        ]
        lines += _shared_meta_lines(task)
        lines.append("")
        lines.append("Notification text:")
        lines.append(truncate_text(task.message, 120_000))
        lines.append("")
        lines.append(
            "If there is no explicit ask, do not launch large implementation or repo-wide refactors. End with a one-line ‘Noted’ or ‘Ack’ summary as appropriate per workspace policy."
        )
        return "\n".join(lines)

    lines2: list[str] = [
        "[Working queue — TASK] This item is **actionable work** to perform (as opposed to a short notification). Session is isolated from personal chat channels.",
    ]
    lines2 += _shared_meta_lines(task)
    lines2.append("")
    lines2.append("Task / message:")
    lines2.append(truncate_text(task.message, 120_000))
    lines2.append("")
    lines2.append(
        "Execute this task per workspace policy. Summarize what you did and any follow-ups at the end."
    )
    return "\n".join(lines2)


def session_key_for_project(project_id: str) -> str:
    """Conversation key so project work does not mix with e.g. discord:… sessions."""
    return f"working:{safe_filename(project_id)}"

