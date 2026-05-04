from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Nạp agile-studio/.env (không ghi đè biến môi trường đã export).
_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv_file() -> None:
    p = _ROOT / ".env"
    if not p.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(p, override=False)


_load_dotenv_file()
_root_str = str(_ROOT)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)

from mcp_server._session import mcp_session
from mcp_server.jsonutil import json_out

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from agile_hub import chat_api_center_bridge, chat_sync, crud, models
from agile_hub.schemas import (
    CommentCreate,
    CommentOut,
    CommentUpdate,
    MemberCreate,
    MemberOut,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectPatch,
    ReleaseCreate,
    ReleaseOut,
    ReleasePatch,
    StoryCreate,
    StoryOut,
    StoryPatch,
    WorkflowTemplateCreate,
    WorkflowTemplateOut,
    project_to_out,
)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise SystemExit("Need to install: pip install mcp (MCP Python SDK).") from e

from starlette.requests import Request
from starlette.responses import JSONResponse

# Host/port used for transport SSE / streamable-http (stdio does not listen to port).
# Can use MCP_HOST / MCP_PORT or FASTMCP_HOST / FASTMCP_PORT.
_MCP_HOST = os.environ.get("MCP_HOST", os.environ.get("FASTMCP_HOST", "127.0.0.1"))
_MCP_PORT = int(os.environ.get("MCP_PORT", os.environ.get("FASTMCP_PORT", "8000")))
_MCP_HTTP_PATH = (os.environ.get("MCP_HTTP_PATH") or "/mcp").strip() or "/mcp"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


# Stateful streamable-http + stale Mcp-Session-Id often surfaces as HTTP 404 ("Invalid or expired session ID").
# Stateless mode avoids sticky sessions; json_response matches typical HTTP MCP clients.
_MCP_STATELESS = _env_bool("MCP_STATELESS_HTTP", True)
_MCP_JSON_RESPONSE = _env_bool("MCP_JSON_RESPONSE", True)

mcp = FastMCP(
    "agile_studio",
    host=_MCP_HOST,
    port=_MCP_PORT,
    instructions="MCP access to Agile Studio DB (same schema as API). Set AGILE_DATABASE_URL environment variable. "
    "Comment needs author_member_id (member must be in project). No JWT required. "
    "Releases: planning window via starts_at/ends_at (ISO-8601 or YYYY-MM-DD); if only starts_at is set, end is end-of-that-day (same as API).",
    streamable_http_path=_MCP_HTTP_PATH,
    stateless_http=_MCP_STATELESS,
    json_response=_MCP_JSON_RESPONSE,
)


@mcp.custom_route("/health", methods=["GET"])
async def _mcp_health_check(_request: Request) -> JSONResponse:
    """Public probe: confirms this process is the MCP server and shows the streamable POST path."""
    return JSONResponse(
        {
            "ok": True,
            "service": "agile-studio-mcp",
            "streamable_http_path": mcp.settings.streamable_http_path,
            "stateless_http": mcp.settings.stateless_http,
            "json_response": mcp.settings.json_response,
        }
    )


def _agile_db_url() -> str:
    u = (os.environ.get("AGILE_DATABASE_URL") or "").strip()
    if u:
        return u
    from agile_hub.config import get_settings

    return (get_settings().database_url or "").strip()


def _boot() -> None:
    if not _agile_db_url():
        raise SystemExit(
            "Missing AGILE_DATABASE_URL. Create .env file in agile-studio directory (see .env.example) "
            "hoặc: export AGILE_DATABASE_URL=mysql+pymysql://…"
        )


def _load_json(s: str) -> dict[str, Any]:
    s = (s or "").strip() or "{}"
    return json.loads(s)


def _sync_chat_after_project_create(project_id: int) -> dict[str, Any]:
    """Best-effort: tạo kênh chat mặc định sau khi tạo project từ MCP."""
    try:
        chat_sync.notify_chat_project_created(project_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _sync_chat_after_member_add(project_id: int, member_id: int) -> dict[str, Any]:
    """Best-effort: tạo DM channels sau khi thêm member từ MCP."""
    try:
        chat_sync.notify_chat_member_added(project_id, member_id)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _project_out_for_mcp(db, p: models.Project) -> dict[str, Any]:
    """
    Project output enriched for AI tools:
    - Keep canonical API shape from project_to_out()
    - Add workflow_template object (if selected)
    - Add convenience summary keys for quick reasoning in list/get tools
    """
    out = project_to_out(p).model_dump(mode="json")
    settings = out.get("settings") if isinstance(out, dict) else {}
    workflow_template_id = None
    storage_overview = None
    if isinstance(settings, dict):
        workflow_template_id = settings.get("workflow_template_id")
        storage_overview = settings.get("storage_overview")

    wf_row = None
    if workflow_template_id:
        wf_row = crud.workflow_template_get(db, int(workflow_template_id))

    out["workflow_template"] = WorkflowTemplateOut.model_validate(wf_row).model_dump(mode="json") if wf_row else None
    out["project_workflow"] = {
        "configured": bool(wf_row),
        "template_id": int(workflow_template_id) if workflow_template_id else None,
        "template_name": (wf_row.name if wf_row else None),
        "template_description": (wf_row.description if wf_row else None),
    }
    out["project_storage"] = {
        "configured": bool((storage_overview or "").strip()),
        "overview": storage_overview or None,
    }
    return out


def _chat_service_base() -> str:
    return (os.environ.get("AGILE_CHAT_SERVICE_URL") or "").strip().rstrip("/")


def _chat_http_json(method: str, path: str, *, query: dict[str, Any] | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    base = _chat_service_base()
    if not base:
        raise ValueError("AGILE_CHAT_SERVICE_URL is not configured")
    q = ""
    if query:
        items = {k: v for k, v in query.items() if v is not None and str(v) != ""}
        if items:
            q = "?" + urllib.parse.urlencode(items)
    url = f"{base}{path}{q}"
    headers = {"Content-Type": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return {}
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
            return {"data": parsed}
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:800]
        raise ValueError(f"chat-service HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise ValueError(f"chat-service unreachable: {e.reason}") from e


# --- health / info ---


@mcp.tool()
def agile_studio_info() -> str:
    """Thông tin phiên bản và xác nhận AGILE_DATABASE_URL đã cấu hình (giá trị bí mật không in ra)."""
    has_url = bool(_agile_db_url())
    return json_out(
        {
            "name": "agile_studio_mcp",
            "agile_database_url_set": has_url,
            "note": "Tools use shared MySQL connection; comment needs author_member_id in project.",
            "releases": "Create/update with starts_at/ends_at (planning window); see agile_release_create and agile_release_update docstrings.",
        }
    )


# --- members ---


@mcp.tool()
def agile_members_list(limit: int = 200) -> str:
    """List of members in workspace."""
    with mcp_session() as db:
        rows = crud.members_list(db, limit=min(max(limit, 1), 500))
        return json_out([MemberOut.model_validate(m).model_dump(mode="json") for m in rows])


@mcp.tool()
def agile_member_get(member_id: int) -> str:
    """Detail of a member."""
    with mcp_session() as db:
        m = crud.member_get(db, member_id)
        if m is None:
            return json_out({"error": "not_found", "member_id": member_id})
        return json_out(MemberOut.model_validate(m).model_dump(mode="json"))


@mcp.tool()
def agile_member_create(
    display_name: str,
    member_type: str = "human",
    email: str = "",
    agent_id: str = "",
) -> str:
    """Create member (human or AI; AI needs agent_id)."""
    body = MemberCreate(
        member_type=member_type,  # type: ignore[arg-type]
        display_name=display_name,
        email=email or None,
        agent_id=agent_id or None,
    )
    with mcp_session() as db:
        m = crud.member_create(db, body)
        return json_out(MemberOut.model_validate(m).model_dump(mode="json"))


# --- projects ---


@mcp.tool()
def agile_projects_list(limit: int = 100) -> str:
    """List projects with storage/workflow metadata for AI reasoning."""
    with mcp_session() as db:
        rows = crud.projects_list(db, limit=min(max(limit, 1), 500))
        return json_out([_project_out_for_mcp(db, p) for p in rows])


# --- master data (workflow templates, global) ---


@mcp.tool()
def agile_workflow_templates_list(limit: int = 200) -> str:
    """List master-data workflow templates (not tied to a project)."""
    with mcp_session() as db:
        rows = crud.workflow_templates_list(db, limit=min(max(limit, 1), 500))
        return json_out([WorkflowTemplateOut.model_validate(r).model_dump(mode="json") for r in rows])


@mcp.tool()
def agile_workflow_template_create(name: str, description: str = "") -> str:
    """Create master-data workflow template: name + description."""
    body = WorkflowTemplateCreate(name=name, description=description or None)
    with mcp_session() as db:
        try:
            row = crud.workflow_template_create(db, body)
        except IntegrityError as e:
            return json_out({"error": "workflow template name may already exist", "detail": str(e)})
        return json_out(WorkflowTemplateOut.model_validate(row).model_dump(mode="json"))


@mcp.tool()
def agile_project_get(project_id: int) -> str:
    """Detail of project (includes storage + workflow template metadata, no secrets).

    BA/docs workflows: use ``settings.github_repository``, ``documents_storage_path``, ``storage_overview``,
    and top-level ``workspace_ref`` to locate where requirements documents should live in Git.
    """
    with mcp_session() as db:
        p = crud.project_get(db, project_id)
        if p is None:
            return json_out({"error": "not_found", "project_id": project_id})
        return json_out(_project_out_for_mcp(db, p))


@mcp.tool()
def agile_project_create(
    slug: str,
    name: str,
    description: str = "",
    status: str = "active",
    workspace_ref: str = "",
) -> str:
    """Create new project (slug according to API rules)."""
    body = ProjectCreate(
        slug=slug,
        name=name,
        description=description or None,
        status=status,  # type: ignore[arg-type]
        workspace_ref=workspace_ref or None,
    )
    with mcp_session() as db:
        try:
            p = crud.project_create(db, body)
        except IntegrityError as e:
            return json_out({"error": "slug may already exist", "detail": str(e)})
        except Exception as e:
            return json_out({"error": str(e)})
        out = _project_out_for_mcp(db, p)
    out["chat_sync"] = _sync_chat_after_project_create(int(out["id"]))
    return json_out(out)


@mcp.tool()
def agile_project_update(project_id: int, patch_json: str = "{}") -> str:
    """
    PATCH project. patch_json: JSON with optional name, description, status, workspace_ref, settings
    (settings: github_repository, ai_working_queue_url, ai_working_queue_secret, ai_working_queue_agent_id, … — xem ProjectSettingsWrite).
    """
    pobj = _load_json(patch_json)
    body = ProjectPatch.model_validate(pobj)
    with mcp_session() as db:
        p = crud.project_get(db, project_id)
        if p is None:
            return json_out({"error": "not_found", "project_id": project_id})
        try:
            crud.project_patch(db, p, body)
        except Exception as e:
            return json_out({"error": str(e)})
        return json_out(_project_out_for_mcp(db, p))


# --- project members ---


@mcp.tool()
def agile_project_members_list(project_id: int) -> str:
    """Members in project."""
    with mcp_session() as db:
        if crud.project_get(db, project_id) is None:
            return json_out({"error": "not_found", "project_id": project_id})
        out = []
        for link in crud.project_members_list(db, project_id):
            mem = crud.member_get(db, link.member_id)
            out.append(
                {
                    "project_id": link.project_id,
                    "member_id": link.member_id,
                    "role": link.role,
                    "joined_at": link.joined_at.isoformat() if link.joined_at else None,
                    "member": MemberOut.model_validate(mem).model_dump(mode="json") if mem else None,
                }
            )
        return json_out(out)


@mcp.tool()
def agile_project_member_add(project_id: int, member_id: int, role: str = "member") -> str:
    """Add member to project."""
    with mcp_session() as db:
        if crud.project_get(db, project_id) is None:
            return json_out({"error": "not_found", "project_id": project_id})
        if crud.member_get(db, member_id) is None:
            return json_out({"error": "not_found", "member_id": member_id})
        try:
            link2 = crud.project_add_member(db, project_id, ProjectMemberAdd(member_id=member_id, role=role or "member"))
        except IntegrityError as e:
            return json_out({"error": "member may already be in project", "detail": str(e)})
        except Exception as e:
            return json_out({"error": str(e)})
        mem = crud.member_get(db, link2.member_id)
        out = {
            "project_id": link2.project_id,
            "member_id": link2.member_id,
            "role": link2.role,
            "joined_at": link2.joined_at.isoformat() if link2.joined_at else None,
            "member": MemberOut.model_validate(mem).model_dump(mode="json") if mem else None,
        }
    out["chat_sync"] = _sync_chat_after_member_add(project_id, member_id)
    return json_out(out)


@mcp.tool()
def agile_project_member_remove(project_id: int, member_id: int) -> str:
    """Remove member from project."""
    with mcp_session() as db:
        if not crud.project_remove_member(db, project_id, member_id):
            return json_out({"error": "not_found", "project_id": project_id, "member_id": member_id})
        return json_out({"ok": True})


# --- releases ---


@mcp.tool()
def agile_releases_list(project_id: int) -> str:
    """Milestone / release for project. Each item includes starts_at, ends_at, released_at (or null) for the planning / ship window."""
    with mcp_session() as db:
        if crud.project_get(db, project_id) is None:
            return json_out({"error": "not_found", "project_id": project_id})
        rows = crud.releases_list(db, project_id)
        return json_out([ReleaseOut.model_validate(r).model_dump(mode="json") for r in rows])


@mcp.tool()
def agile_release_get(release_id: int) -> str:
    """Detail of release: name, status, description, starts_at, ends_at (planning range), released_at, timestamps."""
    with mcp_session() as db:
        r = crud.release_get(db, release_id)
        if r is None:
            return json_out({"error": "not_found", "release_id": release_id})
        return json_out(ReleaseOut.model_validate(r).model_dump(mode="json"))


@mcp.tool()
def agile_release_create(
    project_id: int,
    name: str,
    description: str = "",
    status: str = "planning",
    starts_at: str = "",
    ends_at: str = "",
    released_at: str = "",
) -> str:
    """
    Create release (milestone). Optional planning window: starts_at, ends_at; optional actual ship time: released_at.
    All time fields: ISO-8601 datetime or date-only (YYYY-MM-DD, interpreted as 00:00:00 for that day), or empty to omit.
    If only starts_at is set, the backend extends that day to end-of-day; to span multiple days, set both ends.
    """
    try:
        d0 = _parse_optional_iso_datetime(starts_at, "starts_at")
        d1 = _parse_optional_iso_datetime(ends_at, "ends_at")
        drel = _parse_optional_iso_datetime(released_at, "released_at")
    except ValueError as e:
        return json_out({"error": str(e)})
    body = ReleaseCreate(
        name=name,
        description=description or None,
        status=status,  # type: ignore[arg-type]
        starts_at=d0,
        ends_at=d1,
        released_at=drel,
    )
    with mcp_session() as db:
        if crud.project_get(db, project_id) is None:
            return json_out({"error": "not_found", "project_id": project_id})
        try:
            r = crud.release_create(db, project_id, body)
        except ValueError as e:
            return json_out({"error": str(e)})
        return json_out(ReleaseOut.model_validate(r).model_dump(mode="json"))


def _parse_optional_iso_datetime(s: str, field_name: str = "datetime"):
    """Parse optional ISO-8601 or YYYY-MM-DD; return None for empty/whitespace."""
    from datetime import datetime

    t = (s or "").strip()
    if not t:
        return None
    v = t.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(v)
    except ValueError as e:
        raise ValueError(f"{field_name} invalid: {e}") from e


def _parse_opt_iso_field(pobj: dict, key: str) -> dict:
    """Normalize string ISO dates; empty/whitespace → null so patch can clear a window."""
    pobj = dict(pobj)
    if key not in pobj:
        return pobj
    v = pobj[key]
    if v is None:
        pobj[key] = None
        return pobj
    if isinstance(v, str):
        t = v.strip()
        if not t:
            pobj[key] = None
        else:
            pobj[key] = _parse_optional_iso_datetime(t, key)
        return pobj
    return pobj


@mcp.tool()
def agile_release_update(release_id: int, patch_json: str = "{}") -> str:
    """
    PATCH release. patch_json may include: name, description, status, released_at, starts_at, ends_at.
    Datetimes: ISO-8601 or YYYY-MM-DD (same as agile_release_create). null or \"\" clears a field when the key is present.
    Clear planning window: {"starts_at": null, "ends_at": null}.
    Single day (end filled server-side to end of day if you pass only start): e.g. {"starts_at": "2026-04-01", "ends_at": null}
    or {"starts_at": "2026-04-01T00:00:00"}.
    Inclusive range: set both starts_at and ends_at (e.g. end 2026-04-05T23:59:59.999 or date-only 2026-04-05).
    """
    pobj = _load_json(patch_json)
    pobj = _parse_opt_iso_field(pobj, "released_at")
    pobj = _parse_opt_iso_field(pobj, "starts_at")
    pobj = _parse_opt_iso_field(pobj, "ends_at")
    try:
        body = ReleasePatch.model_validate(pobj)
    except Exception as e:
        return json_out({"error": str(e)})
    with mcp_session() as db:
        r = crud.release_get(db, release_id)
        if r is None:
            return json_out({"error": "not_found", "release_id": release_id})
        try:
            r = crud.release_patch(db, r, body)
        except ValueError as e:
            return json_out({"error": str(e)})
        return json_out(ReleaseOut.model_validate(r).model_dump(mode="json"))


@mcp.tool()
def agile_release_delete(release_id: int) -> str:
    """Delete release (stories: release_id → NULL according to DB)."""
    with mcp_session() as db:
        r = crud.release_get(db, release_id)
        if r is None:
            return json_out({"error": "not_found", "release_id": release_id})
        crud.release_delete(db, r)
        return json_out({"ok": True, "release_id": release_id})


# --- stories ---


def _story_out_for(db, s: models.Story) -> dict[str, Any]:
    p = crud.project_get(db, s.project_id)
    slug = p.slug if p else "?"
    return StoryOut.model_validate(crud.story_to_out(s, slug, db)).model_dump(mode="json")


@mcp.tool()
def agile_stories_list(project_id: int, status: str = "") -> str:
    """List of stories in project. status: filter (e.g. done) — empty = all."""
    st = (status or "").strip() or None
    with mcp_session() as db:
        if crud.project_get(db, project_id) is None:
            return json_out({"error": "not_found", "project_id": project_id})
        rows = crud.stories_list(db, project_id, status=st)
        return json_out([_story_out_for(db, s) for s in rows])


@mcp.tool()
def agile_story_get(story_id: int) -> str:
    """Detail of story."""
    with mcp_session() as db:
        s = crud.story_get(db, story_id)
        if s is None:
            return json_out({"error": "not_found", "story_id": story_id})
        return json_out(_story_out_for(db, s))


@mcp.tool()
def agile_story_create(project_id: int, create_json: str) -> str:
    """
    Create story. create_json: { title, description?, status?, priority?, story_points?, release_id?, release_label? (free tag, max 64 chars), assignee_id? (legacy), assignee_ids?: int[], reporter_id? }
    """
    pobj = _load_json(create_json)
    body = StoryCreate.model_validate(pobj)
    with mcp_session() as db:
        p = crud.project_get(db, project_id)
        if p is None:
            return json_out({"error": "not_found", "project_id": project_id})
        try:
            s = crud.story_create(db, project_id, body)
        except ValueError as e:
            return json_out({"error": str(e)})
        return json_out(StoryOut.model_validate(crud.story_to_out(s, p.slug, db)).model_dump(mode="json"))


@mcp.tool()
def agile_story_update(story_id: int, patch_json: str = "{}") -> str:
    """
    PATCH story. patch_json: title, description, status, priority, story_points, release_id, release_label, assignee_id, assignee_ids, reporter_id
    (only send fields to change). Use assignee_ids: [] to clear assignees, or [id, ...] to replace the full set. release_label: null clears the tag.
    """
    pobj = _load_json(patch_json)
    body = StoryPatch.model_validate(pobj)
    with mcp_session() as db:
        s = crud.story_get(db, story_id)
        if s is None:
            return json_out({"error": "not_found", "story_id": story_id})
        p = crud.project_get(db, s.project_id)
        if p is None:
            return json_out({"error": "project missing", "story_id": story_id})
        mids = crud.project_member_ids(db, p.id)
        try:
            crud.story_patch(db, s, body, project_member_ids_set=mids)
        except ValueError as e:
            return json_out({"error": str(e)})
        return json_out(StoryOut.model_validate(crud.story_to_out(s, p.slug, db)).model_dump(mode="json"))


# --- comments ---


@mcp.tool()
def agile_comments_list(story_id: int) -> str:
    """Comments of story (with author if any)."""
    with mcp_session() as db:
        s = crud.story_get(db, story_id)
        if s is None:
            return json_out({"error": "not_found", "story_id": story_id})
        rows = crud.comments_list(db, story_id)
        return json_out(
            [CommentOut.model_validate(c, from_attributes=True).model_dump(mode="json") for c in rows]
        )


@mcp.tool()
def agile_comment_create(
    story_id: int,
    author_member_id: int,
    body: str | None = None,
    body_text: str | None = None,
    text: str | None = None,
    content: str | None = None,
    message: str | None = None,
) -> str:
    """
    Create comment on a story. author_member_id must be a member of the story's project (same as REST API).
    Comment content: pass **one** non-empty string among ``body`` (REST), ``body_text``, ``text``, ``content``, ``message``.
    Use integers for story_id and author_member_id.
    Mention format: @<mention_key>, mention_key = display_name without spaces, lower-case (e.g. "John Doe" -> @johndoe).
    Invalid mentions return ``{"error": "Unknown mention(s): ..."}``.
    """
    try:
        sid = int(story_id)
        aid = int(author_member_id)
    except (TypeError, ValueError):
        return json_out(
            {"error": "invalid_argument", "detail": "story_id and author_member_id must be integers"}
        )
    merged = ""
    for part in (body, body_text, text, content, message):
        if part is None:
            continue
        s = str(part).strip()
        if s:
            merged = s
            break
    if not merged:
        return json_out(
            {
                "error": "validation_error",
                "detail": "Provide non-empty comment text as `body`, `body_text`, `text`, `content`, or `message`.",
            }
        )
    try:
        cc = CommentCreate(body=merged)
    except ValidationError as e:
        return json_out({"error": "validation_error", "detail": e.errors(include_url=False)})
    with mcp_session() as db:
        s = crud.story_get(db, sid)
        if s is None:
            return json_out({"error": "not_found", "story_id": sid})
        try:
            c = crud.comment_create(db, s, author_member_id=aid, body=cc)
        except ValueError as e:
            return json_out({"error": str(e)})
        c2 = crud.comment_get(db, c.id) or c
        try:
            return json_out(CommentOut.model_validate(c2, from_attributes=True).model_dump(mode="json"))
        except ValidationError as e:
            return json_out(
                {"error": "serialize_failed", "comment_id": c.id, "detail": e.errors(include_url=False)}
            )


@mcp.tool()
def agile_comment_update(
    story_id: int, comment_id: int, new_body: str, editor_member_id: int
) -> str:
    """
    Update comment. editor_member_id must be the same as author (same as API rules).
    Mention rules giống agile_comment_create.
    """
    b = CommentUpdate(body=new_body)
    with mcp_session() as db:
        if crud.story_get(db, story_id) is None:
            return json_out({"error": "not_found", "story_id": story_id})
        c = crud.comment_get(db, comment_id)
        if c is None or c.story_id != story_id:
            return json_out({"error": "not_found", "comment_id": comment_id})
        try:
            crud.comment_update(db, c, editor_member_id=editor_member_id, body=b)
        except ValueError as e:
            return json_out({"error": str(e)})
        except PermissionError as e:
            return json_out({"error": str(e)})
        c2 = crud.comment_get(db, c.id) or c
        return json_out(CommentOut.model_validate(c2, from_attributes=True).model_dump(mode="json"))


@mcp.tool()
def agile_comment_delete(
    story_id: int, comment_id: int, editor_member_id: int
) -> str:
    """Delete comment. editor_member_id = author."""
    with mcp_session() as db:
        if crud.story_get(db, story_id) is None:
            return json_out({"error": "not_found", "story_id": story_id})
        c = crud.comment_get(db, comment_id)
        if c is None or c.story_id != story_id:
            return json_out({"error": "not_found", "comment_id": comment_id})
        try:
            crud.comment_delete(db, c, editor_member_id=editor_member_id)
        except PermissionError as e:
            return json_out({"error": str(e)})
        return json_out({"ok": True})


# --- chat (proxy to chat-service) ---


def _validate_chat_target(target_kind: str, channel_name: str, user_id: int) -> tuple[str, str | None, int | None]:
    tk = (target_kind or "").strip()
    if tk not in ("project_channel", "private_user"):
        raise ValueError("target_kind must be project_channel or private_user")
    if tk == "project_channel":
        name = (channel_name or "").strip()
        if not name:
            raise ValueError("channel_name is required for project_channel")
        return tk, name, None
    uid = int(user_id or 0)
    if uid <= 0:
        raise ValueError("user_id is required for private_user")
    return tk, None, uid


@mcp.tool()
def agile_chat_channels_list(project_id: int) -> str:
    """List chat channels for a project (reads chat-service API)."""
    try:
        data = _chat_http_json("GET", "/api/chat/channels", query={"projectId": project_id})
        return json_out(data)
    except Exception as e:
        return json_out({"error": str(e)})


@mcp.tool()
def agile_chat_messages_list(
    project_id: int,
    target_kind: str,
    viewer_member_id: int,
    channel_name: str = "general",
    user_id: int = 0,
) -> str:
    """List chat messages by channel scope. private_user requires user_id + viewer_member_id."""
    try:
        tk, cname, uid = _validate_chat_target(target_kind, channel_name, user_id)
        if int(viewer_member_id or 0) <= 0:
            raise ValueError("viewer_member_id must be > 0")
        query = {
            "projectId": project_id,
            "targetKind": tk,
            "channelName": cname,
            "userId": uid,
            "viewerMemberId": int(viewer_member_id),
        }
        data = _chat_http_json("GET", "/api/chat/messages", query=query)
        return json_out(data)
    except Exception as e:
        return json_out({"error": str(e)})


@mcp.tool()
def agile_chat_send(
    project_id: int,
    target_kind: str,
    sender_member_id: int,
    content: str,
    channel_name: str = "general",
    user_id: int = 0,
    sender_name: str = "",
) -> str:
    """Send chat message via chat-service.

    When the text contains @mentions, Hub schedules the same API Center chat dispatch as the web UI
    so the mentioned agent's working queue receives the message (requires API Center connected in Hub).
    """
    try:
        tk, cname, uid = _validate_chat_target(target_kind, channel_name, user_id)
        sid = int(sender_member_id or 0)
        if sid <= 0:
            raise ValueError("sender_member_id must be > 0")
        text = (content or "").strip()
        if not text:
            raise ValueError("content is required")
        body = {
            "projectId": project_id,
            "targetKind": tk,
            "channelName": cname,
            "userId": uid,
            "senderUserId": sid,
            "senderName": (sender_name or "").strip() or None,
            "content": text,
        }
        data = _chat_http_json("POST", "/api/chat/messages", body=body)
        chat_api_center_bridge.schedule_dispatch_after_mcp_chat_message(
            project_id=int(project_id),
            target_kind=str(tk),
            channel_name=cname,
            user_id=int(uid or 0),
            sender_user_id=sid,
            sender_name=(sender_name or "").strip() or None,
            content=text,
        )
        return json_out(data)
    except Exception as e:
        return json_out({"error": str(e)})


@mcp.tool()
def agile_chat_message_react(
    message_id: int,
    project_id: int,
    target_kind: str,
    actor_member_id: int,
    reaction: str,
    channel_name: str = "general",
    user_id: int = 0,
    action: str = "toggle",
) -> str:
    """React to a chat message. reaction: seen|like|love|doing|wow|angry|happy."""
    try:
        tk, cname, uid = _validate_chat_target(target_kind, channel_name, user_id)
        rid = int(message_id or 0)
        if rid <= 0:
            raise ValueError("message_id must be > 0")
        aid = int(actor_member_id or 0)
        if aid <= 0:
            raise ValueError("actor_member_id must be > 0")
        rt = (reaction or "").strip().lower()
        if rt not in ("seen", "like", "love", "doing", "wow", "angry", "happy"):
            raise ValueError("reaction must be one of: seen, like, love, doing, wow, angry, happy")
        act = (action or "toggle").strip().lower()
        if act not in ("toggle", "add", "remove"):
            raise ValueError("action must be toggle|add|remove")
        body = {
            "projectId": project_id,
            "targetKind": tk,
            "channelName": cname,
            "userId": uid,
            "actorUserId": aid,
            "reaction": rt,
            "action": act,
        }
        data = _chat_http_json("POST", f"/api/chat/messages/{rid}/reactions", body=body)
        return json_out(data)
    except Exception as e:
        return json_out({"error": str(e)})


@mcp.tool()
def agile_chat_message_delete(
    message_id: int,
    project_id: int,
    target_kind: str,
    sender_member_id: int,
    channel_name: str = "general",
    user_id: int = 0,
) -> str:
    """Delete own chat message by scoped channel info."""
    try:
        tk, cname, uid = _validate_chat_target(target_kind, channel_name, user_id)
        rid = int(message_id or 0)
        if rid <= 0:
            raise ValueError("message_id must be > 0")
        sid = int(sender_member_id or 0)
        if sid <= 0:
            raise ValueError("sender_member_id must be > 0")
        query = {
            "projectId": project_id,
            "targetKind": tk,
            "channelName": cname,
            "userId": uid,
            "senderUserId": sid,
        }
        data = _chat_http_json("DELETE", f"/api/chat/messages/{rid}", query=query)
        return json_out(data)
    except Exception as e:
        return json_out({"error": str(e)})


@mcp.tool()
def agile_chat_typing(
    project_id: int,
    target_kind: str,
    sender_member_id: int,
    is_typing: bool = True,
    channel_name: str = "general",
    user_id: int = 0,
    sender_name: str = "",
) -> str:
    """Emit typing indicator to a chat channel via chat-service."""
    try:
        tk, cname, uid = _validate_chat_target(target_kind, channel_name, user_id)
        sid = int(sender_member_id or 0)
        if sid <= 0:
            raise ValueError("sender_member_id must be > 0")
        body = {
            "projectId": project_id,
            "targetKind": tk,
            "channelName": cname,
            "userId": uid,
            "senderUserId": sid,
            "senderName": (sender_name or "").strip() or None,
            "isTyping": bool(is_typing),
        }
        data = _chat_http_json("POST", "/api/chat/typing", body=body)
        return json_out(data)
    except Exception as e:
        return json_out({"error": str(e)})


def mcp_base_url() -> str:
    """Base URL (no trailing /) when using HTTP; MCP POST path = settings.streamable_http_path (default /mcp)."""
    return f"http://{_MCP_HOST}:{_MCP_PORT}"


def run() -> None:
    _boot()
    transport = (os.environ.get("MCP_TRANSPORT", "stdio") or "stdio").strip().lower()
    if transport in ("http", "httpx", "http-streamable"):
        transport = "streamable-http"

    if transport not in ("stdio", "sse", "streamable-http"):
        print(f"MCP: MCP_TRANSPORT='{transport}' invalid — using stdio.", file=sys.stderr)
        transport = "stdio"

    if transport == "stdio":
        print("MCP Agile Studio: stdio mode (no URL). Client (Cursor) runs this process.", file=sys.stderr)
        mcp.run(transport="stdio")
        return

    if transport == "streamable-http":
        path = getattr(mcp.settings, "streamable_http_path", "/mcp")
        print(
            f"MCP Agile Studio (streamable HTTP): POST JSON-RPC to {mcp_base_url()}{path} "
            f"(GET {mcp_base_url()}/health for probe). "
            f"stateless_http={getattr(mcp.settings, 'stateless_http', '?')} "
            f"json_response={getattr(mcp.settings, 'json_response', '?')}. "
            "If clients see HTTP 404 on POST, see MCP_STATELESS_HTTP / stale session — restart the agent MCP client.",
            file=sys.stderr,
        )
        mcp.run(transport="streamable-http")
        return

    if transport == "sse":
        mount = (os.environ.get("MCP_SSE_MOUNT") or "").strip() or None
        print(
            f"MCP Agile Studio (SSE): listen to  {mcp_base_url()}/  — SSE stream usually at {mcp_base_url()}/sse "
            f"(open according to MCP documentation for mount_path={mount!r}).",
            file=sys.stderr,
        )
        mcp.run(transport="sse", mount_path=mount)
        return