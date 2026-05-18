"""Background poller: consume JSON tasks from the working queue (like heartbeat, file-based)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Coroutine

import os

from loguru import logger

if TYPE_CHECKING:
    from mia.agent.loop import AgentLoop

from mia.utils.evaluator import evaluate_response
from mia.working_queue.models import WorkingQueueTaskPayload
from mia.working_queue.policy import should_fast_skip_notification
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
        noop_notification_skip: bool = True,
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
        self.noop_notification_skip = noop_notification_skip
        self._running = False
        self._task: asyncio.Task | None = None
        self._run_lock = asyncio.Lock()
        # Limits concurrent process_direct runs; created in start() when the loop exists.
        self._job_sem: asyncio.Semaphore | None = None

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Working queue poller: disabled")
            return
        if self._running:
            return
        self.store.maintain_queue()
        reclaimed = self.store.reclaim_processing_on_restart()
        if reclaimed:
            logger.info(
                "Working queue poller: will retry {} reclaimed task(s) after start",
                len(reclaimed),
            )
        self._job_sem = asyncio.Semaphore(self.max_tasks_per_tick)
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
                if self._running:
                    await self._tick()
                if self._running:
                    await asyncio.sleep(self.interval_s)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Working queue poller error: {}", e)

    async def _tick(self) -> None:
        # Claim quickly, then schedule work without awaiting it here — otherwise _loop is
        # blocked for the whole LLM run and no further pending items are ever claimed.
        batch: list[tuple[Path, WorkingQueueTaskPayload]] = []
        async with self._run_lock:
            for _ in range(self.max_tasks_per_tick):
                claimed = self.store.claim_oldest_pending()
                if not claimed:
                    break
                batch.append(claimed)
        if not batch:
            return
        logger.info("Working queue: claimed {} pending task(s)", len(batch))
        sem = self._job_sem
        if sem is None:
            return

        def _spawn(proc_path: Path, wtask: WorkingQueueTaskPayload) -> None:
            async def _runner() -> None:
                async with sem:
                    try:
                        await self._process_one(proc_path, wtask)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("Working queue: background task failed for {}", wtask.id)

            t = asyncio.create_task(_runner())

            def _done(task: asyncio.Task) -> None:
                try:
                    task.result()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    # Already logged in _runner; avoid "Task exception was never retrieved"
                    pass

            t.add_done_callback(_done)

        for proc_path, wtask in batch:
            _spawn(proc_path, wtask)

    async def _process_one(self, processing_path: Path, wtask: Any) -> None:
        if not isinstance(wtask, WorkingQueueTaskPayload):
            logger.error("Working queue: unexpected payload type for {}", processing_path.name)
            return
        if self.noop_notification_skip and should_fast_skip_notification(wtask):
            logger.info(
                "Working queue: fast-skip notification {} (policy/no-op)",
                wtask.id,
            )
            self.store.mark_done(
                processing_path,
                wtask,
                result_excerpt="[skipped] Notification did not require agent action (queue policy).",
            )
            return

        key = session_key_for_project(wtask.project_id)
        user_text = build_process_prompt(wtask, workspace=self.workspace)
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

        async def _deliver_chat_completion_webhook(content: str, delivery_kind: str) -> None:
            """Push Hub/UI reply via API Center when chat metadata is present (Agile bridge)."""
            url = os.environ.get("WORKING_QUEUE_REPLY_INGEST_URL", "").strip()
            secret = os.environ.get("WORKING_QUEUE_REPLY_INGEST_SECRET", "").strip()
            if not url or not secret:
                return
            ctx = wtask.context if isinstance(wtask.context, dict) else {}
            chat = ctx.get("chat")
            if not isinstance(chat, dict):
                return
            channel_id = str(chat.get("channel_id") or "").strip()
            channel_type = str(chat.get("channel_type") or "").strip().lower()
            if not channel_id:
                return
            meta = ctx.get("_reply_meta") if isinstance(ctx.get("_reply_meta"), dict) else {}
            target_agent_id = str(meta.get("target_agent_id") or "").strip() or None
            trace_id = str(meta.get("trace_id") or wtask.id).strip()
            callback_api_url = meta.get("callback_api_url")
            chat_sender = chat.get("sender")
            body: dict[str, Any] = {
                "task_id": wtask.id,
                "project_id": wtask.project_id,
                "channel_id": channel_id,
                "channel_type": channel_type or "direct",
                "target_agent_id": target_agent_id,
                "trace_id": trace_id,
                "content": (content or "")[:12000],
                "delivery_kind": delivery_kind,
            }
            if isinstance(chat_sender, dict):
                body["sender"] = chat_sender
            if callback_api_url:
                body["callback_api_url"] = callback_api_url
            try:
                import httpx

                async with httpx.AsyncClient(timeout=45.0) as client:
                    res = await client.post(
                        url,
                        json=body,
                        headers={
                            "Authorization": f"Bearer {secret}",
                            "Content-Type": "application/json",
                        },
                    )
                if res.status_code >= 400:
                    logger.warning(
                        "Working queue chat webhook HTTP {} — {}",
                        res.status_code,
                        (res.text or "")[:800],
                    )
            except Exception as exc:
                logger.warning("Working queue chat webhook failed: {}", exc)

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

            await _deliver_chat_completion_webhook(text, "done")

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
            err_msg = str(e) or type(e).__name__
            self.store.mark_failed(
                processing_path,
                wtask,
                err_msg,
            )
            await _deliver_chat_completion_webhook(
                f"[Working queue task failed {wtask.id}]\n\n{err_msg}",
                "failed",
            )
