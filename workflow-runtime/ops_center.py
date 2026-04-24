"""Center of workflow: task queue, session key, call agent via `workflow` channel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from mia.agent.loop import AgentLoop


WORKFLOW_CHANNEL = "workflow"


@dataclass(slots=True)
class WorkflowJob:
    id: str
    title: str
    instruction: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowResult:
    job_id: str
    text: str
    session_key: str
    # Queue mode: id file task in working_queue, session working:<project> on target agent
    queue_task_id: str | None = None


class OpsCenter:
    """Associate a project (project) with AgentLoop: each job has a stable session according to `job.id`."""

    def __init__(self, project_id: str, agent_loop: "AgentLoop") -> None:
        self._project_id = project_id
        self._loop = agent_loop

    @staticmethod
    def make_session_key(project_id: str, job_id: str) -> str:
        return f"workflow:{project_id}:{job_id}"

    def session_key(self, job_id: str) -> str:
        return self.make_session_key(self._project_id, job_id)

    async def run_job(self, job: WorkflowJob) -> WorkflowResult:
        """Gửi instruction vào model + tool (qua process_direct) với kênh workflow."""
        out = await self._loop.process_direct(
            job.instruction,
            session_key=self.session_key(job.id),
            channel=WORKFLOW_CHANNEL,
            chat_id=job.id,
        )
        text = (out.content if out else None) or ""
        return WorkflowResult(
            job_id=job.id,
            text=str(text),
            session_key=self.session_key(job.id),
        )

    async def run_queue(self, jobs: list[WorkflowJob]) -> list[WorkflowResult]:
        """Execute sequentially; job after sees history of each `session_key` if same hasn't shared session (each job id different)."""
        results: list[WorkflowResult] = []
        for j in jobs:
            results.append(await self.run_job(j))
        return results
