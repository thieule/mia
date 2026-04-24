"""Background poller: consume JSON tasks from the working queue (like heartbeat, file-based)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

from loguru import logger

if TYPE_CHECKING:
    from mia.agent.loop import AgentLoop

from mia.utils.evaluator import evaluate_response
from mia.working_queue.prompt import build_process_prompt, session_key_for_project
from mia.working_queue.store import WorkingQueueStore


class WorkingQueueService:
    """
    Periodically claim pending ``*.json`` tasks and run them through :meth:`AgentLoop.process_direct`
    with session key ``working:<project>`` so history stays separate from personal channels.
    """

    def __init__(
        self,
        *,
        workspace: Path,
        store: WorkingQueueStore,
        agent: Any,  # AgentLoop
        provider: Any,
        model: str,
        interval_s: int = 20,
        enabled: bool = True,
        max_tasks_per_tick: int = 1,
        notify_on_complete: bool = True,
        keep_recent_session_messages: int = 24,
        on_notify: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        pick_bus_target: Callable[[], tuple[str, str]] | None = None,
        notify_on_complete_kinds: list[str] | None = None,
    ) -> None:
        self.workspace = workspace
        self.store = store
        self.agent: AgentLoop = agent
        self.provider = provider
        self.model = model
        self.interval_s = interval_s
        self.enabled = enabled
        self.max_tasks_per_tick = max(1, max_tasks_per_tick)
        self.notify_on_complete = notify_on_complete
        self.keep_recent_session_messages = max(0, keep_recent_session_messages)
        self.on_notify = on_notify
        self._pick_bus_target = pick_bus_target
        self._notify_kinds: set[str] = set(
            notify_on_complete_kinds if notify_on_complete_kinds is not None else ["task"]
        )
        self._running = False
        self._task: asyncio.Task | None = None
        self._run_lock = asyncio.Lock()

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Working queue poller: disabled")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Working queue poller: started (every {}s)", self.interval_s)

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval_s)
                if self._running:
                    await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Working queue poller error: {}", e)

    async def _tick(self) -> None:
        async with self._run_lock:
            for _ in range(self.max_tasks_per_tick):
                claimed = self.store.claim_oldest_pending()
                if not claimed:
                    return
                proc_path, wtask = claimed
                await self._process_one(proc_path, wtask)

    async def _process_one(self, processing_path: Path, wtask: Any) -> None:
        from mia.working_queue.models import WorkingQueueTaskPayload

        if not isinstance(wtask, WorkingQueueTaskPayload):
            return
        key = session_key_for_project(wtask.project_id)
        user_text = build_process_prompt(wtask)
        kind = wtask.item_kind
        logger.info(
            "Working queue: item {} kind={} project={} session={}",
            wtask.id,
            kind,
            wtask.project_id,
            key,
        )

        async def _silent(*_a: Any, **_k: Any) -> None:
            return

        try:
            await self.agent._connect_mcp()
            resp = await self.agent.process_direct(
                user_text,
                session_key=key,
                channel="working_queue",
                chat_id=wtask.id,
                on_progress=_silent,
            )
            text = (resp.content if resp else None) or ""
            self.store.mark_done(processing_path, wtask, result_excerpt=text[:8000])
            # Bound session size for the project stream
            session = self.agent.sessions.get_or_create(key)
            session.retain_recent_legal_suffix(self.keep_recent_session_messages)
            self.agent.sessions.save(session)

            if self.notify_on_complete and self.on_notify and self._pick_bus_target:
                kind2 = wtask.item_kind
                if kind2 not in self._notify_kinds:
                    return
                channel, chat_id = self._pick_bus_target()
                if channel == "cli":
                    return
                if text.strip():
                    should = await evaluate_response(
                        text, user_text, self.provider, self.model,
                    )
                    if should:
                        label = "Notification" if kind2 == "notification" else "Task"
                        await self.on_notify(
                            f"[Working queue {label} {wtask.id} | project: {wtask.project_id}]\n\n{text}"
                        )
        except Exception as e:
            logger.exception("Working queue: task failed {}", wtask.id)
            self.store.mark_failed(
                processing_path,
                wtask,
                str(e) or type(e).__name__,
            )
