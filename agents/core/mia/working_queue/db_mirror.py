"""Optional MySQL mirror for working-queue tasks (dual-write with file store)."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from loguru import logger

from mia.agent_db_url import resolve_agent_database_url
from mia.working_queue.models import WorkingQueueTaskPayload, utcnow_iso


def _parse_mysql_url(url: str) -> dict[str, Any]:
    u = (url or "").strip()
    if not u:
        raise ValueError("empty database url")
    if "://" in u:
        _, rest = u.split("://", 1)
    else:
        rest = u
    auth_host, _, db = rest.rpartition("/")
    db = db.split("?")[0]
    if "@" in auth_host:
        auth, hostport = auth_host.rsplit("@", 1)
    else:
        auth, hostport = "", auth_host
    if ":" in auth:
        user, password = auth.split(":", 1)
    else:
        user, password = auth, ""
    host = hostport
    port = 3306
    if ":" in hostport and not hostport.startswith("["):
        hp, p = hostport.rsplit(":", 1)
        if p.isdigit():
            host, port = hp, int(p)
    return {"host": host, "port": port, "user": user, "password": password, "database": db}


def _db_url() -> str:
    return resolve_agent_database_url()


def _iso_to_mysql(ts: str | None) -> str | None:
    if not ts:
        return None
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        return None


class WorkingQueueDbMirror:
    """Best-effort mirror to ``mia_working_queue_tasks`` / ``mia_working_queue_events``."""

    def __init__(self, *, agent_id: str, enabled: bool | None = None) -> None:
        self.agent_id = (agent_id or "").strip()
        if enabled is None:
            enabled = (os.environ.get("MIA_WORKING_QUEUE_DB_MIRROR", "1").strip().lower() not in ("0", "false", "no"))
        self.enabled = bool(enabled) and bool(self.agent_id) and bool(_db_url())

    def _connect(self):
        import pymysql

        return pymysql.connect(charset="utf8mb4", autocommit=True, **_parse_mysql_url(_db_url()))

    def _default_workspace_root(self) -> str:
        aid = self.agent_id
        if aid.startswith("mia-"):
            return f"agents/ai-{aid[4:]}/workspace"
        return f"agents/{aid}/workspace"

    def _ensure_agent_row(self, cur: Any) -> None:
        """``mia_working_queue_tasks.agent_id`` FK requires a parent ``mia_agents`` row."""
        cur.execute(
            """
            INSERT INTO mia_agents (id, display_name, workspace_root, metadata)
            VALUES (%s, %s, %s, JSON_OBJECT())
            ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP(6)
            """,
            (self.agent_id, self.agent_id, self._default_workspace_root()),
        )

    def upsert_task(
        self,
        task: WorkingQueueTaskPayload,
        *,
        location: str,
        file_rel: str,
        priority: int = 0,
        dedupe_key: str | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        ctx = dict(task.context or {})
        if dedupe_key:
            ctx["_dedupe_key"] = dedupe_key
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    self._ensure_agent_row(cur)
                    cur.execute(
                        """
                        INSERT INTO mia_working_queue_tasks (
                          id, agent_id, project_id, item_kind, priority, status, location,
                          message, source_role, service, enqueued_by, context, dedupe_key,
                          created_at, updated_at, completed_at, error, result_excerpt
                        ) VALUES (
                          %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s,
                          COALESCE(%s, CURRENT_TIMESTAMP(6)), CURRENT_TIMESTAMP(6),
                          %s, %s, %s
                        )
                        ON DUPLICATE KEY UPDATE
                          project_id = VALUES(project_id),
                          item_kind = VALUES(item_kind),
                          priority = VALUES(priority),
                          status = VALUES(status),
                          location = VALUES(location),
                          message = VALUES(message),
                          source_role = VALUES(source_role),
                          service = VALUES(service),
                          enqueued_by = VALUES(enqueued_by),
                          context = VALUES(context),
                          dedupe_key = VALUES(dedupe_key),
                          updated_at = CURRENT_TIMESTAMP(6),
                          completed_at = VALUES(completed_at),
                          error = VALUES(error),
                          result_excerpt = VALUES(result_excerpt)
                        """,
                        (
                            task.id,
                            self.agent_id,
                            task.project_id,
                            task.item_kind,
                            priority,
                            task.status,
                            location,
                            task.message,
                            task.source_role,
                            task.service,
                            task.enqueued_by,
                            json.dumps(ctx, ensure_ascii=False),
                            dedupe_key,
                            _iso_to_mysql(task.created_at),
                            _iso_to_mysql(task.completed_at),
                            task.error,
                            task.result_excerpt,
                        ),
                    )
            return True
        except Exception as e:
            logger.warning("Working queue DB mirror upsert failed for {}: {}", task.id, e)
            return False

    def append_event(self, task_id: str, event: str, detail: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM mia_working_queue_tasks WHERE id = %s LIMIT 1",
                        (task_id,),
                    )
                    if not cur.fetchone():
                        logger.warning(
                            "Working queue DB mirror event skipped for {}: task row missing (upsert failed?)",
                            task_id,
                        )
                        return
                    cur.execute(
                        """
                        INSERT INTO mia_working_queue_events (task_id, event, detail)
                        VALUES (%s, %s, %s)
                        """,
                        (task_id, event, json.dumps(detail or {}, ensure_ascii=False)),
                    )
        except Exception as e:
            logger.warning("Working queue DB mirror event failed for {}: {}", task_id, e)

    def record_event(
        self,
        task: WorkingQueueTaskPayload,
        *,
        location: str,
        file_rel: str,
        event: str,
        detail: dict[str, Any] | None = None,
        priority: int = 0,
        dedupe_key: str | None = None,
    ) -> None:
        """Upsert task row then append ledger event (single logical write)."""
        if self.upsert_task(
            task,
            location=location,
            file_rel=file_rel,
            priority=priority,
            dedupe_key=dedupe_key,
        ):
            self.append_event(task.id, event, detail)

    def find_active_by_dedupe(self, dedupe_key: str) -> str | None:
        if not self.enabled or not dedupe_key:
            return None
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM mia_working_queue_tasks
                        WHERE agent_id = %s AND dedupe_key = %s
                          AND location IN ('pending', 'processing')
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """,
                        (self.agent_id, dedupe_key),
                    )
                    row = cur.fetchone()
                    return str(row[0]) if row else None
        except Exception as e:
            logger.warning("Working queue DB dedupe lookup failed: {}", e)
            return None

    def delete_task(self, task_id: str) -> None:
        if not self.enabled:
            return
        try:
            with self._connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM mia_working_queue_tasks WHERE id = %s", (task_id,))
        except Exception as e:
            logger.warning("Working queue DB delete failed for {}: {}", task_id, e)
