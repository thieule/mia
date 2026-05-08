"""Build the user message body for a working-queue run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mia.utils.helpers import safe_filename, truncate_text
from mia.working_queue.models import WorkingQueueTaskPayload

_PROJECT_PROMPT_SUBDIR = "project"
_AGILE_STUDIO_DATA_NOTIFICATION_FILE = "AGILE_STUDIO_DATA_NOTIFICATION.md"


def _load_workspace_project_file(workspace: Path | None, filename: str) -> str | None:
    if workspace is None:
        return None
    path = workspace / _PROJECT_PROMPT_SUBDIR / filename
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8").strip()


_CHAT_HIST_MAX_TURNS = 44
_CHAT_HIST_LINE_MAX = 480
_CHAT_HIST_SUMMARY_MAX = 3600
_CHAT_HIST_BLOCK_MAX = 9800

_FALLBACK_AGILE_STUDIO_DATA_NOTIFICATION = """[Agile Studio — DATA NOTIFICATION]
Workspace file missing: add `{subdir}/{filename}` under your agent workspace (same folder as SOUL.md).

Rules: read Notification text and Context JSON (`event_type`, `data`, `recipient_hints`). Do **not** edit Agile stories, comments, or project settings unless the user **explicitly** asks or workspace approval rules apply. Do **not** call MCP `agile_chat_send` to **project group channels** (e.g. `general`) for automated status/data notifications — only story comments, **wiki doc feedback** (`agile_wiki_comment_create`), or your queue summary. For `agile_studio.comment.*`, reply **on the story** via MCP `agile_comment_create` when the comment asks something of you. For `wiki_comment_created` / `wiki_comment_updated` when you are @mentioned, reply **in the wiki doc feedback thread** via `agile_wiki_comment_create` with `parent_id=wiki_thread_root_id` from the payload — not `agile_comment_create`. No large refactors from notifications alone.
""".format(subdir=_PROJECT_PROMPT_SUBDIR, filename=_AGILE_STUDIO_DATA_NOTIFICATION_FILE)


def _is_agile_studio_chat(task: WorkingQueueTaskPayload) -> bool:
    """Agile Studio @agent chat — api-center sets source_role / enqueued_by."""
    if (task.source_role or "").strip() == "agile_studio_chat":
        return True
    eb = (task.enqueued_by or "").strip()
    return eb.startswith("api-center:chat")


def _format_agile_chat_history_block(chat: dict[str, Any]) -> str:
    """Turn conversation_history (+ optional conversation_summary) into prompt text with size caps."""
    summary_raw = str(chat.get("conversation_summary") or "").strip()
    hist = chat.get("conversation_history")
    chunks: list[str] = []
    if summary_raw:
        chunks.append(
            "Older thread summary (optional; may be produced by the client or a future job):\n"
            + truncate_text(summary_raw, _CHAT_HIST_SUMMARY_MAX)
        )
    if not isinstance(hist, list) or not hist:
        return "\n\n".join(chunks).strip()
    tail = hist[-_CHAT_HIST_MAX_TURNS:]
    omitted = len(hist) - len(tail)
    if omitted > 0:
        chunks.append(f"(Skipped {omitted} older messages; recent turns only below.)")
    parts: list[str] = []
    for h in tail:
        if not isinstance(h, dict):
            continue
        c = str(h.get("content") or "").strip()
        if not c:
            continue
        who = str(h.get("sender_type") or "user")
        parts.append(f"- ({who}) {truncate_text(c, _CHAT_HIST_LINE_MAX)}")
    if parts:
        body = "Recent conversation:\n" + "\n".join(parts)
        if len(body) > _CHAT_HIST_BLOCK_MAX:
            body = truncate_text(body, _CHAT_HIST_BLOCK_MAX).rstrip() + "\n… [history truncated]"
        chunks.append(body)
    return "\n\n".join(chunks).strip()


def _build_agile_studio_chat_prompt(task: WorkingQueueTaskPayload) -> str:
    """Build the Agile Studio @agent chat user message."""
    ctx = task.context if isinstance(task.context, dict) else {}
    chat = ctx.get("chat") if isinstance(ctx.get("chat"), dict) else {}
    user_msg = str(chat.get("message") or "").strip()
    if not user_msg:
        user_msg = truncate_text(task.message, 12_000)

    proj = ctx.get("project_context") if isinstance(ctx.get("project_context"), dict) else {}
    pname = str(proj.get("name") or "").strip()

    sender = chat.get("sender") if isinstance(chat.get("sender"), dict) else {}
    sender_name = str(sender.get("name") or "").strip()
    sender_id = str(sender.get("id") or "").strip()

    hist_lines = _format_agile_chat_history_block(chat)
    if hist_lines:
        hist_lines = hist_lines + "\n\n"

    meta = ctx.get("_reply_meta") if isinstance(ctx.get("_reply_meta"), dict) else {}
    parent_trace = str(meta.get("trace_id") or "").strip() or None

    lines: list[str] = [
        "[Agile Studio — chat project]",
        "You run in the **same tool-enabled loop** as the working queue: use MCP (Agile Studio), `working_queue_submit`, filesystem, etc. in this turn **before** the user sees your answer.",
        "",
        "Plan → act → (optional) enqueue:",
        "- **Truth**: Do not invent wiki/story/doc facts. For audits, gap analysis, «what exists», or doc coverage — **read** via MCP / repo tools first; if tools are unavailable or fail, say so instead of listing made-up story numbers.",
        "- **Scope**: If the ask needs multiple substantial steps (research several docs, edit wiki, implement code), outline a short ordered plan, **do** what fits this turn, then enqueue the rest with `working_queue_submit` using the same `project_id`, "
        "`source_role` e.g. `agile_studio_chat_followup`, and `context_json` including "
        '{"origin":"agile_studio_chat","parent_queue_task_id":"' + str(task.id) + '"'
        + (',"parent_trace_id":"' + parent_trace + '"' if parent_trace else "")
        + ',"step_index":1,"step_total":<number_of_steps>} (set step_index/step_total to match your plan). Each queued message must be **one concrete next action**.',
        "- **Honesty**: Do not claim work is «done» or «updated» unless a tool actually performed it in this turn or a queued task id was created for tracked follow-up.",
        "",
        "Chat bubble (user-visible) rules:",
        "- Same language as the user.",
        "- Final channel text = plain assistant dialogue only (no JSON dump, no «system» preamble). You may still use tools in the same turn; the user only sees your **last** assistant message as the bubble.",
        "- Avoid empty meta-phrases («I responded in channel…»). It is OK to briefly say you queued follow-up tasks or verified via tools.",
        "",
    ]
    if pname:
        lines.append(f"Project: {pname}")
        lines.append("")
    if sender_name or sender_id:
        if sender_name:
            who_line = f"The human user writing to you goes by «{sender_name}»"
            if sender_id:
                who_line += f" (member id {sender_id})"
            lines.append(who_line + ".")
        elif sender_id:
            lines.append(
                f"The human user writing to you has member id {sender_id} "
                "(no display name was provided in the chat app)."
            )
        lines.append(
            "If they ask whether you know their name, use the display name above when present; "
            "otherwise explain you only see their member id."
        )
        lines.append("")
    lines.append("User message:")
    lines.append(truncate_text(user_msg, 8000))
    lines.append("")
    if hist_lines:
        lines.append(truncate_text(hist_lines, 10_000))
    mentions = chat.get("mentions")
    if isinstance(mentions, list) and mentions:
        lines.append(f"Mention: {', '.join(str(x) for x in mentions[:24])}")
        lines.append("")
    lines.append(
        "Now: use tools as needed, then output **only** the user-visible chat reply (bubble text):"
    )
    return "\n".join(lines)


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


def _is_agile_studio_auto_notification(task: WorkingQueueTaskPayload) -> bool:
    sr = (task.source_role or "").strip()
    if sr == "agile_studio_auto":
        return True
    wp = task.context.get("webhook_payload") if isinstance(task.context, dict) else None
    return isinstance(wp, dict) and str(wp.get("service") or "").strip() == "agile-studio"


def _build_agile_studio_data_notification_prompt(
    task: WorkingQueueTaskPayload, workspace: Path | None
) -> str:
    """Agile Hub notification — static copy from ``workspace/project/AGILE_STUDIO_DATA_NOTIFICATION.md``."""
    wp = task.context.get("webhook_payload") if isinstance(task.context, dict) else {}
    wp = wp if isinstance(wp, dict) else {}
    data = wp.get("data") if isinstance(wp.get("data"), dict) else {}
    hints = data.get("recipient_hints") if isinstance(data.get("recipient_hints"), dict) else {}
    event_type = str(wp.get("event_type") or "").strip()

    static_block = _load_workspace_project_file(workspace, _AGILE_STUDIO_DATA_NOTIFICATION_FILE)
    if not static_block:
        static_block = _FALLBACK_AGILE_STUDIO_DATA_NOTIFICATION.strip()

    lines: list[str] = [static_block, "", "---", "", "## Attached runtime payload", ""]
    if event_type:
        lines.append(f"event_type: {event_type}")
        lines.append("")
    if event_type in ("wiki_comment_created", "wiki_comment_updated"):
        wd = data.get("wiki_document_id")
        wr = data.get("wiki_thread_root_id")
        if wd and wr:
            lines.append(
                f"Wiki feedback: doc_id={wd!r}, thread root for replies parent_id={wr!r}. "
                "Use MCP `agile_wiki_comment_create(project_id, doc_id, author_member_id, content, parent_id=thread_root)`. "
                "Optional: `quoted_comment_id` / `quoted_text`. List thread with `agile_wiki_comments_list`. "
                "**Do not** use `agile_comment_create` (stories only)."
            )
            lines.append("")
    if event_type in ("agile_studio.comment.created", "agile_studio.comment.updated"):
        sid = data.get("story_id")
        if sid is not None:
            lines.append(
                f"story_id={sid} — reply on-thread via MCP `agile_comment_create` "
                "(story_id, author_member_id, plus comment text as `body`, `body_text`, or `text`; see Notification text for author_member_id)."
            )
            lines.append("")
    if hints:
        lines.append("recipient_hints (summary):")
        lines.append(json.dumps(hints, ensure_ascii=False, indent=2)[:8000])
        lines.append("")
    lines += _shared_meta_lines(task)
    lines.append("")
    lines.append("Notification text:")
    lines.append(truncate_text(task.message, 120_000))
    lines.append("")
    lines.append(
        "Close with a few lines: handled or not and why. Do not mention posting to project group chat "
        "unless the human explicitly asked for that in this event's thread."
    )
    return "\n".join(lines)


def build_process_prompt(task: WorkingQueueTaskPayload, workspace: Path | None = None) -> str:
    kind = task.item_kind if task.item_kind in ("task", "notification") else "task"

    if kind == "task" and _is_agile_studio_chat(task):
        return _build_agile_studio_chat_prompt(task)

    if kind == "notification":
        if _is_agile_studio_auto_notification(task):
            return _build_agile_studio_data_notification_prompt(task, workspace)
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
        "",
        "Process:",
        "1. **Plan** — If the task is broad, split it into ordered substeps (mental or short note).",
        "2. **Decompose** — For steps you cannot finish in this run, enqueue them with `working_queue_submit` "
        f'(same `project_id`, `source_role` describing handoff, `context_json` with '
        f'{{"follows_queue_task_id":"{task.id}","step":n,"plan_note":"..."}}). One queue item = one clear action.',
        "3. **Execute** — Complete what you can now using tools (MCP, repo, etc.).",
        "4. **Report** — Summarize outcomes, list any new queue task ids, and do not claim work done without tool evidence.",
        "",
    ]
    lines2 += _shared_meta_lines(task)
    lines2.append("")
    lines2.append("Task / message:")
    lines2.append(truncate_text(task.message, 120_000))
    lines2.append("")
    lines2.append("Execute per workspace policy and the process above.")
    return "\n".join(lines2)


def session_key_for_project(project_id: str) -> str:
    """Conversation key so project work does not mix with e.g. discord:… sessions."""
    return f"working:{safe_filename(project_id)}"

