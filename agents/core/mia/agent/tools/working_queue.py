"""Enqueue a task to the per-agent file-based working queue (JSON in ``pending/``)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from mia.agent.tools.base import Tool, tool_parameters
from mia.agent.tools.schema import StringSchema, tool_parameters_schema
from mia.utils.helpers import ensure_dir
from mia.working_queue.store import WorkingQueueStore, submit_task

if TYPE_CHECKING:
    from mia.config.schema import WorkingQueueConfig


def _is_under_root(path: Path, root: Path) -> bool:
    a, b = path.resolve(), root.resolve()
    if a == b:
        return True
    try:
        a.relative_to(b)
    except ValueError:
        return False
    return True


@tool_parameters(
    tool_parameters_schema(
        project_id=StringSchema(
            "Project or workstream id. Used to isolate session history: working:<id>, separate from personal chat."
        ),
        message=StringSchema("Task for the next AI to perform (e.g. handoff from BA with requirements)."),
        source_role=StringSchema("Who is enqueueing: e.g. ba, tech, user."),
        service=StringSchema("Optional: service or module name."),
        context_json=StringSchema(
            "Optional JSON object string for structured project context (e.g. {\"client\":\"X\"}). Empty to skip."
        ),
        target_agent_workspace=StringSchema(
            "Optional: absolute path to *another* agent's workspace root (must be listed in handoffAllowWorkspaceRoots). "
            "If set, the task is written to that agent's working_queue/pending (handoff to Tech, etc.)."
        ),
        item_kind=StringSchema(
            "Queue item type: 'task' (actionable work) or 'notification' (short signal; AI treats it as non-mandatory unless text requires action). Default: task."
        ),
        required=["project_id", "message", "source_role"],
    )
)
class WorkingQueueSubmitTool(Tool):
    """Submits a JSON task so the background poller (or same agent) can run it in session ``working:<project_id>``."""

    def __init__(self, local_workspace: Path, config: "WorkingQueueConfig") -> None:
        self._workspace = local_workspace
        self._config = config

    @property
    def name(self) -> str:
        return "working_queue_submit"

    @property
    def description(self) -> str:
        return (
            "Add an item to the working queue (pending JSON): either item_kind=task (work to perform) or item_kind=notification "
            "(information the AI should read/ack briefly, not a full execution brief unless the text says so). "
            "Use a stable project_id so the conversation stays in session key working:<project_id>. "
            "To hand off to another agent, set target_agent_workspace when allowed in config."
        )

    def _store_for_target(self, target_agent_workspace: str | None) -> tuple[WorkingQueueStore, str | None]:
        sub = self._config.subdir
        if not (target_agent_workspace and str(target_agent_workspace).strip()):
            return WorkingQueueStore(ensure_dir(self._workspace / sub)), None
        t = Path(target_agent_workspace).expanduser().resolve()
        roots = [
            Path(r).expanduser().resolve()
            for r in self._config.handoff_allow_workspace_roots
            if str(r).strip()
        ]
        if not roots:
            raise ValueError(
                "target_agent_workspace is set but config.workingQueue.handoffAllowWorkspaceRoots is empty. "
                "Add allowed target workspace absolute paths, or leave target empty for the local queue only."
            )
        if not any(_is_under_root(t, r) for r in roots):
            raise ValueError(
                f"target_agent_workspace {t} is not under any configured handoffAllowWorkspaceRoots."
            )
        return WorkingQueueStore(ensure_dir(t / sub)), str(t)

    async def execute(
        self,
        project_id: str,
        message: str,
        source_role: str,
        service: str | None = None,
        context_json: str | None = None,
        target_agent_workspace: str | None = None,
        item_kind: str = "task",
        **kwargs: Any,
    ) -> str:
        import json

        context: dict[str, Any] = {}
        if context_json is not None and str(context_json).strip():
            try:
                raw = json.loads(context_json)
                if not isinstance(raw, dict):
                    return "Error: context_json must be a JSON object (dictionary)."
                context = raw
            except json.JSONDecodeError as e:
                return f"Error: context_json is not valid JSON: {e}"

        try:
            store, _ = self._store_for_target(
                str(target_agent_workspace).strip() if target_agent_workspace and str(target_agent_workspace).strip() else None
            )
        except ValueError as e:
            return f"Error: {e}"

        task_id = submit_task(
            store,
            project_id=project_id,
            message=message,
            source_role=source_role,
            service=service,
            context=context,
            enqueued_by="tool:working_queue_submit",
            item_kind=item_kind or "task",
        )
        loc = store.base
        return (
            f"Enqueued working-queue task {task_id} (project_id={project_id!r}). "
            f"Files: {loc / 'pending'}. Session when run: working:<project>."
        )
