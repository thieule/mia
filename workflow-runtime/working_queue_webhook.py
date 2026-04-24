#!/usr/bin/env python3
"""
HTTP endpoint để enqueue task vào `working_queue/pending` của từng agent (theo bản ghi file JSON
của mia, xem `core/mia/working_queue/`).

Chạy tách khỏi `mia gateway` — cần gateway tương ứng đang bật `workingQueue.enabled` để agent xử lý.

Ví dụ (PowerShell, sau khi cấu hình `.env` hoặc biến môi trường + JSON agent map):

  # workflow-runtime/.env: WORKFLOW_RUNTIME_CONNECT_SECRET=... (≥ 12 ký tự) — client đổi lấy session_key
  python working_queue_webhook.py --port 18880
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
import yaml

# Bootstrap giống main.py
_WR = Path(__file__).resolve().parent
_REPO = _WR.parent
_CORE = _REPO / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

_DEFAULT_AGENTS = _WR / "working_queue_webhook_agents.json"
_EXAMPLE_AGENTS = _WR / "working_queue_webhook_agents.example.json"
_DEFAULT_WQ = "working_queue"
_DEFAULT_MIN_TOKEN = 12
_DEFAULT_EVENT_WORKFLOW = _WR / "workflows" / "agile-studio.events.workflow.yaml"


def _load_dotenv(path: Path) -> None:
    """Cùng quy ước tối giản như `main.py` — tải file .env cạnh `workflow-runtime` (nếu có)."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, val = line.partition("=")
        name = name.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1]
        if name:
            os.environ[name] = val


def _err(status: int, code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "http_status": status}}


def _load_agents_file(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Agent map not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Agent map must be a JSON object keyed by agent_id")
    for k, v in raw.items():
        if not k or not isinstance(v, dict) or "workspace" not in v:
            raise ValueError(f"Invalid entry for {k!r}: need {{ \"workspace\": \"<path>\" }}")
    return raw  # type: ignore[return-value]


def _safe_under_repo(repo: Path, rel_or_abs: str) -> Path:
    """Chỉ cho phép thư mục workspace dưới gốc monorepo (an toàn path)."""
    p = Path(rel_or_abs)
    if p.is_absolute():
        r = p.resolve()
    else:
        r = (repo / p).resolve()
    base = repo.resolve()
    try:
        r.relative_to(base)
    except ValueError as e:
        raise ValueError(f"Workspace path must be inside repo: {r}") from e
    if not r.is_dir():
        raise ValueError(f"Workspace directory does not exist: {r}")
    return r


# --- API models ---


class ProjectBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(..., min_length=1, description="Dùng làm project_id trong hàng đợi / session working:<id>")
    name: str | None = None


class TaskBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    message: str = Field(..., min_length=1, description="Nhiệm vụ agent phải làm")
    source_role: str = Field(default="webhook", min_length=1, description="Nguồn gắn queue (Jira, Linear, v.v.)")
    service: str | None = None


class EnqueueRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    agent_id: str = Field(..., min_length=1, description="Khóa trong file agent map")
    # Cho phép flat hoặc lồng
    project_id: str | None = None
    project_name: str | None = None
    project: ProjectBlock | None = None
    message: str | None = None
    source_role: str = Field(default="webhook", min_length=1)
    service: str | None = None
    task: TaskBlock | None = None
    # Story, trạng thái, ticket, tùy biến
    context: dict[str, Any] = Field(default_factory=dict)
    # Alias phổ biến từ tích hợp
    story: Any | None = None
    stories: list[Any] | None = None
    task_metadata: dict[str, Any] = Field(default_factory=dict)
    # task = việc làm; notification = thông báo (cùng thư mục queue, format prompt khác)
    item_kind: str = Field(
        default="task",
        description="task | notification — cùng pending/ queue, mia phân biệt qua trường này.",
    )

    @field_validator("item_kind", mode="before")
    @classmethod
    def _ik(cls, v: Any) -> Any:
        s = (str(v) if v is not None else "task").strip().lower()
        if s in ("task", "notification", "note", "notify"):
            if s in ("note", "notify"):
                return "notification"
            return s
        return "task"

    @field_validator("message", mode="before")
    @classmethod
    def _strip_m(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip() or v
        return v

    def effective_project_id(self) -> str:
        if self.project and self.project.id:
            return self.project.id.strip()
        if self.project_id and str(self.project_id).strip():
            return str(self.project_id).strip()
        raise ValueError("Cần project_id hoặc project.id")

    def effective_message(self) -> str:
        if self.task and self.task.message and self.task.message.strip():
            return self.task.message.strip()
        if self.message and str(self.message).strip():
            return str(self.message).strip()
        raise ValueError("Cần message hoặc task.message")

    def build_context_merged(self) -> dict[str, Any]:
        p_id = self.effective_project_id()
        p_name: str | None = None
        if self.project:
            p_name = self.project.name
        elif self.project_name is not None:
            p_name = str(self.project_name) if str(self.project_name) else None
        out: dict[str, Any] = {**(self.context or {})}
        if self.project is not None:
            p_dump = self.project.model_dump()
            p_extra = {k: v for k, v in p_dump.items() if k not in ("id", "name") and v is not None}
            if p_extra:
                out["project_extra"] = p_extra
        if self.story is not None:
            out["story"] = self.story
        if self.stories is not None:
            out["stories"] = self.stories
        if self.task_metadata:
            prev = out.get("metadata")
            if isinstance(prev, dict):
                out["metadata"] = {**prev, **self.task_metadata}
            else:
                out["metadata"] = dict(self.task_metadata)
        # Canonical project record — ghi đè sau cùng
        out["project"] = {"id": p_id, "name": p_name}
        return out

    def effective_source_role(self) -> str:
        if self.task and self.task.source_role:
            return self.task.source_role.strip() or "webhook"
        return (self.source_role or "webhook").strip() or "webhook"

    def effective_service(self) -> str | None:
        if self.task and self.task.service is not None and str(self.task.service).strip():
            return str(self.task.service).strip()
        if self.service and str(self.service).strip():
            return str(self.service).strip()
        p_name: str | None = None
        if self.project and self.project.name:
            p_name = self.project.name
        elif self.project_name:
            p_name = str(self.project_name)
        if p_name and p_name.strip():
            return p_name.strip()
        return None


class AgileStoryEventRequest(BaseModel):
    """
    Webhook event from Agile Studio. Runtime translates event -> queue action.
    """

    model_config = ConfigDict(extra="allow")

    event_type: str = Field(..., min_length=1, description="e.g. story.created, story.status_changed")
    event_id: str | None = None
    timestamp: str | None = None
    project: dict[str, Any] = Field(default_factory=dict)
    story: dict[str, Any] = Field(default_factory=dict)
    changes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = Field(
        default=None,
        description="Optional explicit target agent override. If empty, server routes by event_type map.",
    )
    item_kind: str = Field(default="task", description="task|notification. Default task.")

    @field_validator("event_type", mode="before")
    @classmethod
    def _ev(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("item_kind", mode="before")
    @classmethod
    def _ev_item_kind(cls, v: Any) -> Any:
        s = (str(v) if v is not None else "task").strip().lower()
        if s in ("task", "notification", "note", "notify"):
            return "notification" if s in ("note", "notify") else s
        return "task"

    def project_id(self) -> str:
        p = self.project if isinstance(self.project, dict) else {}
        for k in ("id", "project_id", "key", "code"):
            val = p.get(k)
            if val is not None and str(val).strip():
                return str(val).strip()
        raise ValueError("Thiếu project.id/project_id/key/code trong payload event")

    def project_name(self) -> str | None:
        p = self.project if isinstance(self.project, dict) else {}
        val = p.get("name") or p.get("title")
        if val is None:
            return None
        t = str(val).strip()
        return t if t else None

    def story_id(self) -> str:
        s = self.story if isinstance(self.story, dict) else {}
        for k in ("id", "story_id", "key", "code"):
            val = s.get(k)
            if val is not None and str(val).strip():
                return str(val).strip()
        return "(unknown-story)"

    def story_title(self) -> str:
        s = self.story if isinstance(self.story, dict) else {}
        val = s.get("title") or s.get("name") or s.get("summary")
        if val is None:
            return "(untitled)"
        t = str(val).strip()
        return t if t else "(untitled)"

    def story_status(self) -> str | None:
        s = self.story if isinstance(self.story, dict) else {}
        c = self.changes if isinstance(self.changes, dict) else {}
        cand = c.get("to_status") or c.get("status") or s.get("status") or s.get("state")
        if cand is None:
            return None
        t = str(cand).strip()
        return t if t else None

    def to_queue_message(self, *, target_agent: str, action_hint: str | None = None) -> str:
        sid = self.story_id()
        title = self.story_title()
        pid = self.project_id()
        pname = self.project_name() or "(no project name)"
        status = self.story_status() or "(unknown)"
        et = self.event_type
        action_line = (
            f"Action from workflow: {action_hint}\n"
            if action_hint and str(action_hint).strip()
            else ""
        )
        if et == "story.created":
            return (
                f"[Agile event] Story created -> assign to {target_agent}\n"
                f"{action_line}"
                f"- Project: {pid} ({pname})\n"
                f"- Story: {sid} - {title}\n"
                f"- Current status: {status}\n"
                "Please triage this story and propose next concrete actions for your role."
            )
        if et in ("story.status_changed", "story.updated", "story.state_changed"):
            return (
                f"[Agile event] Story updated -> assign to {target_agent}\n"
                f"{action_line}"
                f"- Project: {pid} ({pname})\n"
                f"- Story: {sid} - {title}\n"
                f"- New status: {status}\n"
                "Assess impact, update plan/checklist, and suggest immediate follow-up actions."
            )
        return (
            f"[Agile event] {et} -> assign to {target_agent}\n"
            f"{action_line}"
            f"- Project: {pid} ({pname})\n"
            f"- Story: {sid} - {title}\n"
            "Interpret this event and decide the most appropriate next steps for your role."
        )


# --- HTTP ---


def _extract_bearer(request: "web.Request") -> str:
    h = request.headers.get("Authorization") or ""
    if h.startswith("Bearer "):
        return h[7:].strip()
    return (request.headers.get("X-Api-Key") or "").strip()


def _event_status_from_payload(ev: AgileStoryEventRequest) -> str:
    return (
        (ev.changes.get("to_status") if isinstance(ev.changes, dict) else None)
        or (ev.changes.get("status") if isinstance(ev.changes, dict) else None)
        or (ev.story.get("status") if isinstance(ev.story, dict) else None)
        or (ev.story.get("state") if isinstance(ev.story, dict) else None)
        or ""
    ).strip().lower()


def _normalize_rule_statuses(raw: Any) -> set[str]:
    if isinstance(raw, str) and raw.strip():
        return {raw.strip().lower()}
    if isinstance(raw, list):
        out: set[str] = set()
        for x in raw:
            if isinstance(x, str) and x.strip():
                out.add(x.strip().lower())
        return out
    return set()


def _load_event_workflow(workflow_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Returns (rules, metadata). File format:
      routing:
        defaultAgentId: pm
        rules:
          - when: { eventType: story.created, statusIn: [icebox] }
            dispatch: { agentId: dev, itemKind: task, action: "..." }
    """
    if not workflow_path.is_file():
        return [], {}
    try:
        raw = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return [], {}
    if not isinstance(raw, dict):
        return [], {}
    routing = raw.get("routing")
    if not isinstance(routing, dict):
        return [], {}
    rules_raw = routing.get("rules")
    if not isinstance(rules_raw, list):
        rules_raw = []
    rules: list[dict[str, Any]] = []
    for row in rules_raw:
        if isinstance(row, dict):
            rules.append(row)
    meta = {
        "name": raw.get("name"),
        "version": raw.get("version"),
        "default_agent_id": routing.get("defaultAgentId") or routing.get("default_agent_id"),
        "workflow_file": str(workflow_path),
    }
    return rules, meta


def _resolve_event_dispatch(
    ev: AgileStoryEventRequest,
    *,
    rules: list[dict[str, Any]],
    meta: dict[str, Any],
) -> tuple[str, str, str | None, str]:
    """
    Returns: (agent_id, item_kind, action_hint, route_source)
    route_source = "payload_override" | "workflow_rule:<id>" | "workflow_default" | "fallback"
    """
    if ev.agent_id and ev.agent_id.strip():
        aid = ev.agent_id.strip()
        return aid, ev.item_kind, None, "payload_override"

    ev_type = ev.event_type.strip()
    status = _event_status_from_payload(ev)

    for idx, rule in enumerate(rules):
        when = rule.get("when")
        dispatch = rule.get("dispatch")
        if not isinstance(when, dict) or not isinstance(dispatch, dict):
            continue
        req_type = when.get("eventType") or when.get("event_type")
        if isinstance(req_type, str) and req_type.strip() and req_type.strip() != ev_type:
            continue
        status_in = _normalize_rule_statuses(when.get("statusIn") or when.get("status_in"))
        if status_in and status not in status_in:
            continue
        status_not_in = _normalize_rule_statuses(when.get("statusNotIn") or when.get("status_not_in"))
        if status_not_in and status in status_not_in:
            continue

        aid = (dispatch.get("agentId") or dispatch.get("agent_id") or "").strip()
        if not aid:
            continue
        ik = str(dispatch.get("itemKind") or dispatch.get("item_kind") or ev.item_kind).strip().lower()
        if ik not in ("task", "notification"):
            ik = "task"
        action_hint = dispatch.get("action")
        rid = rule.get("id") or f"#{idx+1}"
        return aid, ik, (str(action_hint).strip() if action_hint is not None else None), f"workflow_rule:{rid}"

    dflt = str(meta.get("default_agent_id") or "").strip()
    if dflt:
        return dflt, ev.item_kind, None, "workflow_default"

    # Last resort (backward-compatible fallback)
    fallback_map = {
        "story.created": "dev",
        "story.status_changed": "pm",
        "story.updated": "pm",
        "story.state_changed": "pm",
    }
    aid = fallback_map.get(ev_type, "pm")
    return aid, ev.item_kind, None, "fallback"


def _make_handler(
    repo: Path,
    agent_map: dict[str, dict[str, Any]],
    wq_subdir: str,
    agent_rows: list[dict[str, Any]],
    data_dir: Path,
    event_rules: list[dict[str, Any]],
    event_workflow_meta: dict[str, Any],
) -> tuple[Any, ...]:
    from aiohttp import web
    from mia.working_queue import submit_task
    from mia.working_queue.store import WorkingQueueStore
    from workflow_studio import (
        append_interest,
        create_session,
        public_base_url,
        session_is_valid,
    )

    @web.middleware
    async def auth_mw(request: web.Request, handler: Any) -> web.Response:
        if request.method == "GET" and request.path in ("/", "/health", "/v1/health"):
            return await handler(request)  # type: ignore[no-any-return]
        if request.method == "POST" and request.path == "/v1/sessions":
            return await handler(request)  # type: ignore[no-any-return]
        tok = _extract_bearer(request)
        if not tok:
            return web.json_response(
                _err(401, "unauthorized", "Thiếu token. Tạo session: POST /v1/sessions với { secret } rồi gửi Bearer session_key."),
                status=401,
            )
        if session_is_valid(tok):
            request["studio_auth"] = "session"  # type: ignore[assignment]
            return await handler(request)  # type: ignore[no-any-return]
        return web.json_response(
            _err(401, "unauthorized", "Session không hợp lệ hoặc hết hạn. Gọi lại POST /v1/sessions."),
            status=401,
        )

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "workflow_runtime"})

    async def root(request: web.Request) -> web.Response:
        base = public_base_url(request)
        return web.json_response(
            {
                "service": "workflow_runtime",
                "version": 1,
                "links": {
                    "health": f"{base}/v1/health",
                    "discovery": f"{base}/v1/discovery",
                    "create_session": f"{base}/v1/sessions",
                    "enqueue": f"{base}/v1/working-queue/tasks",
                },
            }
        )

    async def discovery(request: web.Request) -> web.Response:
        base = public_base_url(request)
        return web.json_response(
            {
                "runtime": {
                    "name": "a-agents workflow-runtime",
                    "version": 1,
                    "public_base_url": base,
                },
                "auth": {
                    "connect": "Một bí mật duy nhất (env WORKFLOW_RUNTIME_CONNECT_SECRET) — chỉ dùng trong POST /v1/sessions { secret }",
                    "bearer": "Mọi API khác: Authorization: Bearer <session_key> từ phản hồi 201 /v1/sessions",
                },
                "webhook": {
                    "method": "POST",
                    "url": f"{base}/v1/working-queue/tasks",
                    "headers": {
                        "Authorization": "Bearer <session_key>",
                        "Content-Type": "application/json",
                    },
                    "body": {
                        "agent_id": "bắt buộc",
                        "item_kind": "task|notification (optional)",
                        "message": "hoặc task.message",
                        "project_id": "hoặc project.id",
                    },
                },
                "event_webhooks": {
                    "agile_story": {
                        "method": "POST",
                        "url": f"{base}/v1/events/agile-story",
                        "headers": {
                            "Authorization": "Bearer <session_key>",
                            "Content-Type": "application/json",
                        },
                        "routing": {
                            "mode": "workflow_yaml",
                            "default_agent_id": event_workflow_meta.get("default_agent_id"),
                            "rules_count": len(event_rules),
                            "workflow_file": event_workflow_meta.get("workflow_file"),
                        },
                    }
                },
                "agents": agent_rows,
            }
        )

    async def create_session_handler(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response(_err(400, "invalid_json", "Body JSON không hợp lệ"), status=400)
        if not isinstance(body, dict):
            return web.json_response(_err(400, "invalid_body", "Root phải là object JSON"), status=400)
        sec = (body.get("secret") or body.get("bootstrap_secret") or body.get("bootstrap") or "").strip()
        if not sec:
            return web.json_response(_err(400, "missing_secret", "Cần secret, bootstrap_secret hoặc bootstrap"), status=400)
        sk = create_session(sec)
        if not sk:
            return web.json_response(
                _err(401, "invalid_connect_secret", "secret không khớp WORKFLOW_RUNTIME_CONNECT_SECRET (server)"),
                status=401,
            )
        try:
            ttl_d = float((os.environ.get("WORKFLOW_STUDIO_SESSION_TTL_DAYS") or "30").strip() or "30")
        except ValueError:
            ttl_d = 30.0
        return web.json_response(
            {
                "session_key": sk,
                "token_type": "bearer",
                "usage": "Dùng Authorization: Bearer <session_key> cho mọi API đã bảo vệ (discovery, enqueue, register).",
                "ttl_hint_days": ttl_d,
            },
            status=201,
        )

    async def register_interest(request: web.Request) -> web.Response:
        agent_id = (request.match_info.get("id") or "").strip()
        if not agent_id or agent_id not in agent_map:
            return web.json_response(
                _err(404, "unknown_agent", f"agent {agent_id!r} chưa có trên server"),
                status=404,
            )
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        append_interest(data_dir, body, agent_id)
        return web.json_response(
            {
                "ok": True,
                "agent_id": agent_id,
                "message": "Ghi nhận (tùy chọn). Đổi queue thật vẫn dùng POST /v1/working-queue/tasks.",
            }
        )

    async def enqueue(request: web.Request) -> web.Response:
        ct = (request.content_type or "").lower()
        if ct and "json" not in ct and "text/plain" not in ct:
            return web.json_response(
                _err(400, "bad_request", "Dùng Content-Type: application/json (hoặc bỏ trống)"),
                status=400,
            )
        try:
            body = await request.json()
        except Exception:
            return web.json_response(_err(400, "invalid_json", "Body JSON không hợp lệ"), status=400)
        if not isinstance(body, dict):
            return web.json_response(_err(400, "invalid_body", "Root phải là object JSON"), status=400)
        try:
            req = EnqueueRequest.model_validate(body)
        except Exception as e:
            return web.json_response(_err(400, "validation_error", str(e)), status=400)

        aid = req.agent_id.strip()
        if aid not in agent_map:
            return web.json_response(
                _err(404, "unknown_agent", f"agent_id {aid!r} chưa có trong agent map"),
                status=404,
            )
        rel_ws = str(agent_map[aid]["workspace"]).strip()
        try:
            wroot = _safe_under_repo(repo, rel_ws)
        except ValueError as e:
            return web.json_response(_err(400, "bad_workspace", str(e)), status=400)
        wq = wroot / wq_subdir
        wq.mkdir(parents=True, exist_ok=True)
        try:
            pid = req.effective_project_id()
            msg = req.effective_message()
            srole = req.effective_source_role()
            svc = req.effective_service()
            ctx = req.build_context_merged()
        except ValueError as e:
            return web.json_response(_err(400, "invalid_payload", str(e)), status=400)
        try:
            store = WorkingQueueStore(wq)
            task_id = submit_task(
                store,
                project_id=pid,
                message=msg,
                source_role=srole,
                service=svc,
                context=ctx,
                enqueued_by="webhook:POST /v1/working-queue/tasks",
                item_kind=req.item_kind,
            )
        except Exception as e:
            logger.exception("enqueue failed")
            return web.json_response(_err(500, "enqueue_error", str(e)), status=500)
        return web.json_response(
            {
                "task_id": task_id,
                "item_kind": req.item_kind,
                "project_id": pid,
                "agent_id": aid,
                "queue_dir": str(wq),
                "session_hint": f"working:{pid} (khi agent xử lý)",
            },
            status=201,
        )

    async def agile_story_event(request: web.Request) -> web.Response:
        ct = (request.content_type or "").lower()
        if ct and "json" not in ct and "text/plain" not in ct:
            return web.json_response(
                _err(400, "bad_request", "Dùng Content-Type: application/json (hoặc bỏ trống)"),
                status=400,
            )
        try:
            body = await request.json()
        except Exception:
            return web.json_response(_err(400, "invalid_json", "Body JSON không hợp lệ"), status=400)
        if not isinstance(body, dict):
            return web.json_response(_err(400, "invalid_body", "Root phải là object JSON"), status=400)
        try:
            ev = AgileStoryEventRequest.model_validate(body)
            pid = ev.project_id()
        except Exception as e:
            return web.json_response(_err(400, "validation_error", str(e)), status=400)

        aid, routed_item_kind, action_hint, route_source = _resolve_event_dispatch(
            ev,
            rules=event_rules,
            meta=event_workflow_meta,
        )
        if not aid:
            return web.json_response(
                _err(
                    400,
                    "no_route",
                    f"Không tìm được route cho event_type={ev.event_type!r}. Set agent_id hoặc kiểm tra workflow YAML routing.",
                ),
                status=400,
            )
        if aid not in agent_map:
            return web.json_response(
                _err(404, "unknown_agent", f"Routed agent_id {aid!r} không có trong agent map"),
                status=404,
            )
        rel_ws = str(agent_map[aid]["workspace"]).strip()
        try:
            wroot = _safe_under_repo(repo, rel_ws)
        except ValueError as e:
            return web.json_response(_err(400, "bad_workspace", str(e)), status=400)
        wq = wroot / wq_subdir
        wq.mkdir(parents=True, exist_ok=True)

        try:
            store = WorkingQueueStore(wq)
            ctx = {
                "agile_event": {
                    "event_type": ev.event_type,
                    "event_id": ev.event_id,
                    "timestamp": ev.timestamp,
                },
                "project": ev.project,
                "story": ev.story,
                "changes": ev.changes,
                "metadata": ev.metadata,
                "routing": {
                    "target_agent": aid,
                    "route_source": route_source,
                    "workflow_file": event_workflow_meta.get("workflow_file"),
                },
            }
            msg = ev.to_queue_message(target_agent=aid, action_hint=action_hint)
            task_id = submit_task(
                store,
                project_id=pid,
                message=msg,
                source_role="agile_studio_event",
                service=ev.project_name() or "agile-story",
                context=ctx,
                enqueued_by="webhook:POST /v1/events/agile-story",
                item_kind=routed_item_kind,
            )
        except Exception as e:
            logger.exception("agile event enqueue failed")
            return web.json_response(_err(500, "enqueue_error", str(e)), status=500)
        return web.json_response(
            {
                "ok": True,
                "event_type": ev.event_type,
                "routed_agent_id": aid,
                "item_kind": routed_item_kind,
                "route_source": route_source,
                "task_id": task_id,
                "project_id": pid,
                "queue_dir": str(wq),
            },
            status=201,
        )

    return (
        auth_mw,
        health,
        root,
        discovery,
        create_session_handler,
        register_interest,
        enqueue,
        agile_story_event,
    )


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Webhook enqueue → working_queue (a-agents).")
    p.add_argument("--host", default="127.0.0.1", help="Bind (mặc định chỉ nội bộ)")
    p.add_argument("--port", type=int, default=18880, help="Cổng HTTP (mặc định 18880)")
    p.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Gốc monorepo a-agents (mẹ của ai-dev, ...). Mặc định: parent thư mục workflow-runtime.",
    )
    p.add_argument(
        "--agents",
        type=Path,
        default=None,
        help="JSON map agent (override env WORKING_QUEUE_WEBHOOK_AGENTS_FILE)",
    )
    p.add_argument(
        "--wq-subdir",
        default=None,
        help="Thư mục con dưới workspace (mặc định: env WORKING_QUEUE_SUBDIR hoặc working_queue)",
    )
    p.add_argument(
        "--env",
        type=Path,
        default=None,
        help="File .env (mặc định: workflow-runtime/.env). Nạp trước khi đọc WORKFLOW_RUNTIME_CONNECT_SECRET.",
    )
    p.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="File JSON catalog tên/role mô tả (WORKFLOW_STUDIO_CATALOG_FILE); xem studio_agents_catalog.example.json",
    )
    p.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Thư mục lưu session + audit (mặc định: workflow-runtime/studio_data).",
    )
    p.add_argument(
        "--event-workflow",
        type=Path,
        default=None,
        help="YAML event workflow (default: workflows/agile-studio.events.workflow.yaml).",
    )
    return p.parse_args()


def main() -> int:
    from aiohttp import web
    if not _CORE.is_dir() or not (_CORE / "mia").is_dir():
        print("Không tìm thấy mia: chạy với venv đã cài: pip install -e ../core", file=sys.stderr)
        return 1
    if str(_CORE) not in sys.path:
        sys.path.insert(0, str(_CORE))

    args = _parse()
    _load_dotenv((args.env or _WR / ".env").resolve())
    repo = (args.repo_root or _REPO).resolve()
    _env_path = os.environ.get("WORKING_QUEUE_WEBHOOK_AGENTS_FILE")
    if _env_path:
        _ap = Path(_env_path).expanduser()
    elif _DEFAULT_AGENTS.is_file():
        _ap = _DEFAULT_AGENTS
    elif _EXAMPLE_AGENTS.is_file():
        _ap = _EXAMPLE_AGENTS
    else:
        _ap = _DEFAULT_AGENTS
    agents_path = (args.agents or _ap).expanduser()
    wq_subdir = (args.wq_subdir or os.environ.get("WORKING_QUEUE_SUBDIR", _DEFAULT_WQ)).strip()
    from workflow_studio import get_connect_secret, init_session_store, merge_agent_catalog

    csec = get_connect_secret() or ""
    if not csec or len(csec) < _DEFAULT_MIN_TOKEN:
        print(
            f"Thiếu WORKFLOW_RUNTIME_CONNECT_SECRET (≥ {_DEFAULT_MIN_TOKEN} ký tự).",
            file=sys.stderr,
        )
        print(
            f"  Một bí mật duy nhất: client dùng trong POST /v1/sessions; sau đó chỉ dùng session_key. "
            f"Đặt trong {_WR / '.env'} — xem docs/CLIENT_INTEGRATION.md",
            file=sys.stderr,
        )
        return 1
    try:
        amap = _load_agents_file(agents_path.resolve())
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"Lỗi agent map: {e}", file=sys.stderr)
        return 1
    for aid, v in amap.items():
        try:
            r = str(v.get("workspace", "")).strip()
            _ = _safe_under_repo(repo, r)
        except Exception as e:
            print(f"[{aid}] {e}", file=sys.stderr)
            return 1

    data_dir = (args.data_dir or _WR / "studio_data").resolve()
    init_session_store(data_dir)
    wf_raw = (
        args.event_workflow
        or Path(os.environ.get("WORKFLOW_RUNTIME_EVENT_WORKFLOW_FILE", str(_DEFAULT_EVENT_WORKFLOW)))
    )
    wf_path = wf_raw.expanduser()
    if not wf_path.is_absolute():
        wf_path = (_WR / wf_path).resolve()
    else:
        wf_path = wf_path.resolve()
    event_rules, event_workflow_meta = _load_event_workflow(wf_path)
    if not event_workflow_meta:
        event_workflow_meta = {"workflow_file": str(wf_path), "default_agent_id": "pm"}

    _cat_arg = args.catalog
    _cat_env = os.environ.get("WORKFLOW_STUDIO_CATALOG_FILE", "").strip()
    if _cat_arg:
        cat_path = _cat_arg.expanduser().resolve()
    elif _cat_env:
        cat_path = Path(_cat_env).expanduser().resolve()
    else:
        cdef = _WR / "studio_agents_catalog.json"
        cat_path = cdef if cdef.is_file() else None
    if cat_path is not None and not cat_path.is_file():
        print(f"Catalog not found: {cat_path} — discovery dùng tên mặc định từ agent key.", file=sys.stderr)
        cat_path = None

    try:
        agent_rows = merge_agent_catalog(repo, amap, cat_path)
    except (OSError, TypeError) as e:
        print(f"Lỗi merge catalog: {e}", file=sys.stderr)
        return 1

    auth_mw, h, root, disc, sess, reg, enq, ev_story = _make_handler(
        repo, amap, wq_subdir, agent_rows, data_dir, event_rules, event_workflow_meta
    )
    app = web.Application(middlewares=[auth_mw])
    app.router.add_get("/", root)
    app.router.add_get("/health", h)
    app.router.add_get("/v1/health", h)
    app.router.add_get("/v1/discovery", disc)
    app.router.add_get("/v1/agents", disc)
    app.router.add_post("/v1/sessions", sess)
    app.router.add_post("/v1/agents/{id}/register", reg)
    app.router.add_post("/v1/working-queue/tasks", enq)
    app.router.add_post("/v1/events/agile-story", ev_story)
    if args.host in {"0.0.0.0", "[::]"}:
        print("[cảnh báo] lắng trên tất cả giao diện — cần reverse proxy + TLS hoặc firewall", flush=True)
    print(f"Base URL: http://{args.host}:{args.port}/  (GET /, GET /v1/discovery, POST /v1/sessions)", flush=True)
    print(f"  Webhooks: POST /v1/working-queue/tasks | POST /v1/events/agile-story", flush=True)
    print(f"  event workflow: {wf_path} (rules={len(event_rules)})", flush=True)
    print(f"  repo: {repo}", flush=True)
    print(f"  agent map: {agents_path}", flush=True)
    print(f"  studio data: {data_dir}", flush=True)
    web.run_app(app, host=args.host, port=args.port, print=lambda m: None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
