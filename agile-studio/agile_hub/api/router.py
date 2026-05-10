from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import api_center_client, chat_sync, crud, models
from ..chat_api_center_bridge import merge_dispatch_payload_callback_url
from ..api_center_urls import normalize_api_center_endpoints, normalize_websocket_url
from .. import working_queue_webhook as wq_webhook
from ..api_center_notify import (
    forward_webhook_to_api_center,
    schedule_api_center_event_fanout,
    wiki_comment_webhook_data_dict,
    wiki_document_webhook_data_dict,
)
from ..schemas import (
    CommentCreate,
    CommentOut,
    CommentUpdate,
    MemberCreate,
    MemberOut,
    ProjectCreate,
    ProjectInviteCreate,
    ProjectInvitePendingOut,
    ProjectMemberAdd,
    ProjectMemberOut,
    MyProjectInviteOut,
    ProjectOut,
    ProjectPatch,
    ReleaseCreate,
    ReleaseOut,
    ReleasePatch,
    StoryCreate,
    WorkflowTemplateCreate,
    WorkflowTemplateOut,
    WorkspaceRoleCreate,
    WorkspaceRoleOut,
    WorkspaceRolePatch,
    StoryStatusEventOut,
    StoryOut,
    StoryPatch,
    StoryTaskCreate,
    StoryTaskListPage,
    StoryTaskOut,
    StoryTaskPatch,
    TaskCommentOut,
    ApiCenterAgentOut,
    ApiCenterAllowMcpIn,
    ApiCenterConnectIn,
    ApiCenterStatusOut,
    ApiCenterChatDispatchIn,
    ApiCenterAgileNotificationIn,
    project_to_out,
    WikiDocCreate,
    WikiDocOut,
    WikiDocPatch,
    WikiDocSearchOut,
    WikiFolderCreate,
    WikiFolderOut,
    WikiFolderPatch,
    WikiFolderTreeNode,
    WikiFolderTreeResponse,
    WikiCommentCreate,
    WikiCommentCountOut,
    WikiCommentOut,
    WikiCommentPatch,
)
from .deps import get_current_user, get_db

router = APIRouter(tags=["agile-studio"], dependencies=[Depends(get_current_user)])


def _project_or_404(db: Session, project_id: int) -> models.Project:
    p = crud.project_get(db, project_id)
    if p is None:
        raise HTTPException(404, "Project not found")
    return p


def _comment_out_json(db: Session, c: models.StoryComment) -> dict:
    c2 = crud.comment_get(db, c.id) or c
    return CommentOut.model_validate(c2, from_attributes=True).model_dump(mode="json")


def _wiki_comment_out_json(db: Session, row: models.WikiComment) -> dict:
    return WikiCommentOut.model_validate(crud.wiki_comment_to_dict(db, row)).model_dump(mode="json")


def _story_or_404(db: Session, story_id: int) -> models.Story:
    s = crud.story_get(db, story_id)
    if s is None:
        raise HTTPException(404, "Story not found")
    return s


def _member_or_404(db: Session, member_id: int) -> models.Member:
    m = crud.member_get(db, member_id)
    if m is None:
        raise HTTPException(404, "Member not found")
    return m


def _release_or_404(db: Session, release_id: int) -> models.Release:
    r = crud.release_get(db, release_id)
    if r is None:
        raise HTTPException(404, "Release not found")
    return r


def _require_project_member(db: Session, project_id: int, member_id: int) -> None:
    if member_id not in crud.project_member_ids(db, project_id):
        raise HTTPException(403, "Not a member of this project")


def _require_project_workflow_selected(db: Session, p: models.Project) -> None:
    settings = p.settings_json if isinstance(p.settings_json, dict) else {}
    wf_id = settings.get("workflow_template_id")
    if wf_id is None:
        raise HTTPException(400, "Project must select a workflow template in Settings before creating/updating stories")
    try:
        wf_id_int = int(wf_id)
    except Exception:
        raise HTTPException(400, "Project workflow_template_id is invalid") from None
    if wf_id_int <= 0 or crud.workflow_template_get(db, wf_id_int) is None:
        raise HTTPException(400, "Project workflow_template_id is missing or no longer exists")


# --- Members ---
@router.post("/members", response_model=MemberOut)
def create_member(body: MemberCreate, db: Session = Depends(get_db)) -> models.Member:
    if body.member_type == "ai" and not (body.agent_id or "").strip():
        raise HTTPException(400, "member_type=ai requires agent_id (runtime agent id)")
    return crud.member_create(db, body)


@router.get("/members", response_model=list[MemberOut])
def list_members(db: Session = Depends(get_db), limit: int = 200) -> list[models.Member]:
    return crud.members_list(db, limit=min(limit, 500))


@router.get("/members/{member_id}", response_model=MemberOut)
def get_member(member_id: int, db: Session = Depends(get_db)) -> models.Member:
    return _member_or_404(db, member_id)


def _mask_token(v: str | None) -> str | None:
    s = (v or "").strip()
    if not s:
        return None
    if len(s) <= 7:
        return "***"
    return f"{s[:3]}***{s[-2:]}"


@router.get("/integrations/api-center/status", response_model=ApiCenterStatusOut)
def get_api_center_status(db: Session = Depends(get_db)) -> ApiCenterStatusOut:
    row = crud.api_center_connection_get(db)
    if row is None:
        return ApiCenterStatusOut()
    raw_ep = row.api_endpoints_json if isinstance(row.api_endpoints_json, dict) else {}
    cw = str(raw_ep.get("chat_ws") or "").strip()
    return ApiCenterStatusOut(
        endpoint=row.endpoint,
        connected=bool((row.session_key or "").strip()),
        has_mcp_api_key=bool((row.mcp_api_key or "").strip()),
        mcp_api_key_masked=_mask_token(row.mcp_api_key),
        endpoints=normalize_api_center_endpoints(raw_ep),
        chat_ws_url=normalize_websocket_url(cw) if cw else None,
    )


@router.post("/integrations/api-center/connect", response_model=ApiCenterStatusOut)
def connect_api_center(body: ApiCenterConnectIn, db: Session = Depends(get_db)) -> ApiCenterStatusOut:
    try:
        session_info = api_center_client.create_session_info(body.endpoint.strip().rstrip("/"), body.secret)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    row = crud.api_center_connection_upsert(
        db,
        endpoint=body.endpoint.strip(),
        connect_secret=body.secret,
        session_key=str(session_info.get("session_key") or ""),
        api_endpoints=session_info.get("endpoints") if isinstance(session_info.get("endpoints"), dict) else {},
    )
    raw_ep = row.api_endpoints_json if isinstance(row.api_endpoints_json, dict) else {}
    cw = str(raw_ep.get("chat_ws") or "").strip()
    return ApiCenterStatusOut(
        endpoint=row.endpoint,
        connected=True,
        has_mcp_api_key=bool((row.mcp_api_key or "").strip()),
        mcp_api_key_masked=_mask_token(row.mcp_api_key),
        endpoints=normalize_api_center_endpoints(raw_ep),
        chat_ws_url=normalize_websocket_url(cw) if cw else None,
    )


@router.get("/integrations/api-center/agents", response_model=list[ApiCenterAgentOut])
def list_api_center_agents(db: Session = Depends(get_db)) -> list[ApiCenterAgentOut]:
    row = crud.api_center_connection_get(db)
    if row is None or not (row.session_key or "").strip():
        raise HTTPException(400, "API Center is not connected")
    try:
        agents = api_center_client.list_agents(row.endpoint, row.session_key or "")
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    out: list[ApiCenterAgentOut] = []
    for a in agents:
        try:
            out.append(
                ApiCenterAgentOut(
                    id=str(a.get("id") or ""),
                    name=(str(a.get("name")) if a.get("name") is not None else None),
                    role=(str(a.get("role")) if a.get("role") is not None else None),
                    description=(str(a.get("description")) if a.get("description") is not None else None),
                    workspace=(str(a.get("workspace")) if a.get("workspace") is not None else None),
                    supported_item_kinds=[str(x) for x in (a.get("supported_item_kinds") or []) if x is not None],
                )
            )
        except Exception:
            continue
    return [x for x in out if x.id]


@router.post("/integrations/api-center/allow-mcp")
def allow_api_center_mcp_access(body: ApiCenterAllowMcpIn, db: Session = Depends(get_db)) -> dict:
    row = crud.api_center_connection_get(db)
    if row is None or not (row.session_key or "").strip():
        raise HTTPException(400, "API Center is not connected")
    api_key = crud.api_center_generate_mcp_api_key()
    try:
        saved = api_center_client.save_mcp_credentials(
            row.endpoint,
            row.session_key or "",
            mcp_server_id=body.mcp_server_id,
            mcp_url=body.mcp_url.strip(),
            api_key=api_key,
            metadata=body.metadata or {},
            hub_reply_base_url=(body.hub_reply_base_url or "").strip() or None,
            mcp_tools_url=(body.mcp_tools_url or "").strip() or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    crud.api_center_connection_set_mcp_api_key(db, mcp_api_key=api_key)
    return {
        "ok": True,
        "mcp_server_id": body.mcp_server_id,
        "mcp_url": body.mcp_url.strip(),
        "api_key_masked": _mask_token(api_key),
        "api_center_response": saved,
    }


@router.post("/integrations/api-center/allow-mcp-access")
def allow_api_center_mcp_access_alias(body: ApiCenterAllowMcpIn, db: Session = Depends(get_db)) -> dict:
    return allow_api_center_mcp_access(body, db)


@router.post("/integrations/api-center/reconnect", response_model=ApiCenterStatusOut)
def reconnect_api_center(db: Session = Depends(get_db)) -> ApiCenterStatusOut:
    row = crud.api_center_connection_get(db)
    if row is None:
        raise HTTPException(400, "API Center is not connected")
    if not (row.connect_secret or "").strip():
        raise HTTPException(400, "API Center connect secret is missing")
    try:
        session_info = api_center_client.reconnect_session_info(row.endpoint, row.connect_secret)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    row = crud.api_center_connection_upsert(
        db,
        endpoint=row.endpoint,
        connect_secret=row.connect_secret,
        session_key=str(session_info.get("session_key") or ""),
        api_endpoints=session_info.get("endpoints") if isinstance(session_info.get("endpoints"), dict) else {},
    )
    raw_ep = row.api_endpoints_json if isinstance(row.api_endpoints_json, dict) else {}
    cw = str(raw_ep.get("chat_ws") or "").strip()
    return ApiCenterStatusOut(
        endpoint=row.endpoint,
        connected=True,
        has_mcp_api_key=bool((row.mcp_api_key or "").strip()),
        mcp_api_key_masked=_mask_token(row.mcp_api_key),
        endpoints=normalize_api_center_endpoints(raw_ep),
        chat_ws_url=normalize_websocket_url(cw) if cw else None,
    )


@router.post("/integrations/api-center/chat/dispatch")
def api_center_chat_dispatch(body: ApiCenterChatDispatchIn, db: Session = Depends(get_db)) -> dict:
    row = crud.api_center_connection_get(db)
    if row is None or not (row.session_key or "").strip():
        raise HTTPException(400, "API Center is not connected")
    payload = merge_dispatch_payload_callback_url(body.model_dump(exclude_none=True))
    if os.environ.get("AGILE_HUB_CHAT_DEBUG", "").strip().lower() in ("1", "true", "yes"):
        tid = payload.get("trace_id") or ""
        print(
            f"[agile-hub][chat-dispatch] trace_id={tid!r} channel_id={payload.get('channel_id')!r} "
            f"target_agent_id={payload.get('target_agent_id')!r} endpoint={row.endpoint!r}",
            flush=True,
        )
    try:
        return api_center_client.chat_dispatch(row.endpoint, row.session_key or "", payload)
    except ValueError as e:
        msg = str(e)
        if "HTTP 401" in msg and (row.connect_secret or "").strip():
            try:
                reconnect_info = api_center_client.reconnect_session_info(row.endpoint, row.connect_secret)
                new_sk = str(reconnect_info.get("session_key") or "")
                crud.api_center_connection_upsert(
                    db,
                    endpoint=row.endpoint,
                    connect_secret=row.connect_secret,
                    session_key=new_sk,
                    api_endpoints=reconnect_info.get("endpoints") if isinstance(reconnect_info.get("endpoints"), dict) else {},
                )
                return api_center_client.chat_dispatch(row.endpoint, new_sk, payload)
            except ValueError as e2:
                raise HTTPException(400, str(e2)) from e2
        raise HTTPException(400, msg) from e


@router.post("/integrations/api-center/webhooks/agile-notifications")
def api_center_agile_notifications(body: ApiCenterAgileNotificationIn, db: Session = Depends(get_db)) -> dict:
    payload = body.model_dump(exclude_none=True)
    try:
        return forward_webhook_to_api_center(db, payload)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# --- Master data (workflow templates, workspace roles) ---
@router.get("/workflow-templates", response_model=list[WorkflowTemplateOut])
def list_workflow_templates(db: Session = Depends(get_db), limit: int = 200) -> list[models.WorkflowTemplate]:
    return crud.workflow_templates_list(db, limit=min(limit, 500))


@router.post("/workflow-templates", response_model=WorkflowTemplateOut)
def create_workflow_template(body: WorkflowTemplateCreate, db: Session = Depends(get_db)) -> models.WorkflowTemplate:
    try:
        return crud.workflow_template_create(db, body)
    except IntegrityError:
        raise HTTPException(409, "Workflow template name already exists") from None


@router.get("/workspace-roles", response_model=list[WorkspaceRoleOut])
def list_workspace_roles(db: Session = Depends(get_db), limit: int = 500) -> list[models.WorkspaceRole]:
    return crud.workspace_roles_list(db, limit=min(limit, 1000))


@router.post("/workspace-roles", response_model=WorkspaceRoleOut)
def create_workspace_role(body: WorkspaceRoleCreate, db: Session = Depends(get_db)) -> models.WorkspaceRole:
    try:
        return crud.workspace_role_create(db, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except IntegrityError:
        raise HTTPException(409, "Role slug already exists") from None


@router.patch("/workspace-roles/{role_id}", response_model=WorkspaceRoleOut)
def patch_workspace_role(role_id: int, body: WorkspaceRolePatch, db: Session = Depends(get_db)) -> models.WorkspaceRole:
    row = crud.workspace_role_get(db, role_id)
    if row is None:
        raise HTTPException(404, "Role not found")
    try:
        return crud.workspace_role_patch(db, row, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.delete("/workspace-roles/{role_id}", status_code=204)
def delete_workspace_role(role_id: int, db: Session = Depends(get_db)) -> Response:
    row = crud.workspace_role_get(db, role_id)
    if row is None:
        raise HTTPException(404, "Role not found")
    try:
        crud.workspace_role_delete(db, row)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return Response(status_code=204)


# --- Projects ---
@router.post("/projects", response_model=ProjectOut)
def create_project(
    body: ProjectCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ProjectOut:
    try:
        p = crud.project_create(db, body)
    except IntegrityError:
        raise HTTPException(409, "Project slug already exists") from None
    background_tasks.add_task(chat_sync.notify_chat_project_created, p.id)
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=p.id,
        project_name=p.name,
        event_type="agile_studio.project.created",
        summary=f"Project created: {p.name} ({p.slug})",
        changed_fields=["created"],
        data={"project_id": p.id, "slug": p.slug},
    )
    return project_to_out(p)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), limit: int = 100) -> list[ProjectOut]:
    rows = crud.projects_list(db, limit=min(limit, 500))
    return [project_to_out(p) for p in rows]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)) -> ProjectOut:
    return project_to_out(_project_or_404(db, project_id))


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def patch_project(
    project_id: int,
    body: ProjectPatch,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ProjectOut:
    p = _project_or_404(db, project_id)
    try:
        crud.project_patch(db, p, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    changed = [str(k) for k in body.model_dump(exclude_unset=True).keys() if k]
    if changed:
        schedule_api_center_event_fanout(
            background_tasks,
            project_id=p.id,
            project_name=p.name,
            event_type="agile_studio.project.updated",
            summary=f"Project {p.name} updated",
            changed_fields=changed,
            data={"project_id": p.id, "patched_field_names": changed},
        )
    return project_to_out(p)


# --- Project members ---
@router.get("/projects/{project_id}/members", response_model=list[ProjectMemberOut])
def list_project_members(project_id: int, db: Session = Depends(get_db)) -> list[ProjectMemberOut]:
    _project_or_404(db, project_id)
    out: list[ProjectMemberOut] = []
    for link in crud.project_members_list(db, project_id):
        mem = crud.member_get(db, link.member_id)
        out.append(
            ProjectMemberOut(
                project_id=link.project_id,
                member_id=link.member_id,
                role=link.role,
                joined_at=link.joined_at,
                member=MemberOut.model_validate(mem) if mem else None,
            )
        )
    return out


@router.post("/projects/{project_id}/members", response_model=ProjectMemberOut)
def add_project_member(
    project_id: int,
    body: ProjectMemberAdd,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ProjectMemberOut:
    p = _project_or_404(db, project_id)
    _member_or_404(db, body.member_id)
    try:
        link = crud.project_add_member(db, project_id, body)
    except IntegrityError:
        raise HTTPException(409, "Member is already in this project") from None
    background_tasks.add_task(chat_sync.notify_chat_member_added, project_id, body.member_id)
    mem = crud.member_get(db, link.member_id)
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="agile_studio.project.member_added",
        summary=(f"Member {mem.display_name if mem else body.member_id} added to {p.name} (role: {link.role})"),
        changed_fields=["project_members"],
        data={
            "project_id": project_id,
            "member_id": body.member_id,
            "role": link.role,
        },
    )
    return ProjectMemberOut(
        project_id=link.project_id,
        member_id=link.member_id,
        role=link.role,
        joined_at=link.joined_at,
        member=MemberOut.model_validate(mem) if mem else None,
    )


@router.delete("/projects/{project_id}/members/{member_id}", status_code=204)
def remove_project_member(
    project_id: int,
    member_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> None:
    p = _project_or_404(db, project_id)
    if not crud.project_remove_member(db, project_id, member_id):
        raise HTTPException(404, "No project–member link for this pair")
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="agile_studio.project.member_removed",
        summary=f"Member {member_id} removed from {p.name}",
        changed_fields=["project_members"],
        data={"project_id": project_id, "member_id": member_id},
    )


_log_inv = logging.getLogger(__name__)


def _bg_send_project_invite_email(to_email: str, inviter_name: str, project_name: str, token: str) -> None:
    try:
        from ..mail import project_invite_accept_url, send_project_invite_email

        send_project_invite_email(
            to_email=to_email,
            inviter_display_name=inviter_name,
            project_name=project_name,
            accept_url=project_invite_accept_url(token),
        )
    except Exception:
        _log_inv.exception("Failed to send project invite email to %s", to_email)


@router.get("/me/project-invites", response_model=list[MyProjectInviteOut])
def list_my_project_invites(
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> list[MyProjectInviteOut]:
    rows = crud.project_invite_list_pending_for_user_email(db, current.email)
    out: list[MyProjectInviteOut] = []
    for r in rows:
        p = crud.project_get(db, r.project_id)
        out.append(
            MyProjectInviteOut(
                token=r.token,
                project_id=r.project_id,
                project_name=p.name if p else "Project",
                project_slug=p.slug if p else "",
                role=r.role,
                expires_at=r.expires_at,
            )
        )
    return out


@router.post("/projects/{project_id}/invites", response_model=ProjectInvitePendingOut)
def create_project_invite(
    project_id: int,
    body: ProjectInviteCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> ProjectInvitePendingOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    try:
        row = crud.project_invite_create(
            db,
            project_id=project_id,
            email=str(body.email),
            role=body.role,
            invited_by_member_id=current.member_id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    inviter = crud.member_get(db, current.member_id)
    inviter_name = inviter.display_name if inviter else "Teammate"
    background_tasks.add_task(_bg_send_project_invite_email, row.email, inviter_name, p.name, row.token)
    return ProjectInvitePendingOut.model_validate(row)


@router.get("/projects/{project_id}/invites/pending", response_model=list[ProjectInvitePendingOut])
def list_pending_project_invites(
    project_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> list[ProjectInvitePendingOut]:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    rows = crud.project_invite_list_pending_for_project(db, project_id)
    return [ProjectInvitePendingOut.model_validate(r) for r in rows]


@router.delete("/projects/{project_id}/invites/{invite_id}", status_code=204)
def revoke_project_invite(
    project_id: int,
    invite_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    if not crud.project_invite_revoke(db, invite_id, project_id):
        raise HTTPException(404, "Invite not found or already used")
    return Response(status_code=204)


@router.post("/invites/token/{token}/accept", response_model=ProjectMemberOut)
def accept_project_invite_route(
    token: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> ProjectMemberOut:
    try:
        link, joined_new = crud.project_invite_accept(db, token, current)
    except ValueError as e:
        code = str(e)
        if code == "email_mismatch":
            raise HTTPException(403, "Sign-in email must match the invited email") from None
        raise HTTPException(400, f"Cannot accept invitation ({code})") from None
    mem = crud.member_get(db, link.member_id)
    if joined_new:
        background_tasks.add_task(chat_sync.notify_chat_member_added, link.project_id, link.member_id)
        p = crud.project_get(db, link.project_id)
        if p:
            schedule_api_center_event_fanout(
                background_tasks,
                project_id=link.project_id,
                project_name=p.name,
                event_type="agile_studio.project.member_added",
                summary=f"Member {mem.display_name if mem else link.member_id} joined {p.name} (invite)",
                changed_fields=["project_members"],
                data={"project_id": link.project_id, "member_id": link.member_id, "role": link.role},
            )
    return ProjectMemberOut(
        project_id=link.project_id,
        member_id=link.member_id,
        role=link.role,
        joined_at=link.joined_at,
        member=MemberOut.model_validate(mem) if mem else None,
    )


# --- Releases ---
@router.post("/projects/{project_id}/releases", response_model=ReleaseOut)
def create_release(
    project_id: int,
    body: ReleaseCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> models.Release:
    p = _project_or_404(db, project_id)
    try:
        r = crud.release_create(db, project_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="agile_studio.release.created",
        summary=f"Release {r.name} created on {p.name}",
        changed_fields=["created"],
        data={"project_id": project_id, "release_id": r.id, "name": r.name, "status": r.status},
    )
    return r


@router.get("/projects/{project_id}/releases", response_model=list[ReleaseOut])
def list_releases(project_id: int, db: Session = Depends(get_db)) -> list[models.Release]:
    _project_or_404(db, project_id)
    return crud.releases_list(db, project_id)


@router.get("/releases/{release_id}", response_model=ReleaseOut)
def get_release(release_id: int, db: Session = Depends(get_db)) -> models.Release:
    return _release_or_404(db, release_id)


@router.patch("/releases/{release_id}", response_model=ReleaseOut)
def patch_release(
    release_id: int,
    body: ReleasePatch,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> models.Release:
    r = _release_or_404(db, release_id)
    p = _project_or_404(db, r.project_id)
    try:
        out = crud.release_patch(db, r, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    keys = [str(k) for k in body.model_dump(exclude_unset=True).keys() if k]
    if keys:
        schedule_api_center_event_fanout(
            background_tasks,
            project_id=p.id,
            project_name=p.name,
            event_type="agile_studio.release.updated",
            summary=f"Release {out.name} updated",
            changed_fields=keys,
            data={"project_id": p.id, "release_id": out.id, "patched_field_names": keys},
        )
    return out


@router.delete("/releases/{release_id}", status_code=204)
def delete_release(
    release_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Response:
    r = _release_or_404(db, release_id)
    p = _project_or_404(db, r.project_id)
    rid, rname = r.id, r.name
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=p.id,
        project_name=p.name,
        event_type="agile_studio.release.deleted",
        summary=f"Release {rname!r} (id={rid}) deleted from {p.name}",
        changed_fields=["deleted"],
        data={"project_id": p.id, "release_id": rid},
    )
    crud.release_delete(db, r)
    return Response(status_code=204)


# --- Stories ---
@router.post("/projects/{project_id}/stories", response_model=StoryOut)
def create_story(
    project_id: int,
    body: StoryCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> StoryOut:
    p = _project_or_404(db, project_id)
    _require_project_workflow_selected(db, p)
    try:
        s = crud.story_create(db, project_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    out = crud.story_to_out(s, p.slug, db)
    sk = f"{p.slug}-{s.story_number}"
    cfg = wq_webhook.parse_webhook_config(
        p.settings_json if isinstance(p.settings_json, dict) else None
    )
    if cfg:
        post_url, token, agent_id = cfg
        background_tasks.add_task(
            wq_webhook.background_new_story,
            post_url,
            token,
            agent_id,
            p.slug,
            p.name,
            sk,
            s.title,
            s.description,
            s.status,
        )
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="agile_studio.story.created",
        summary=f"Story {sk} created: {s.title}",
        changed_fields=["created"],
        data={
            "project_id": project_id,
            "story_id": s.id,
            "story_key": sk,
            "title": s.title,
            "status": s.status,
        },
    )
    return StoryOut.model_validate(out)


@router.get("/projects/{project_id}/tasks", response_model=StoryTaskListPage)
def list_project_tasks(
    project_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
    assignee_member_id: Optional[int] = None,
    task_status: Optional[str] = None,
    ticket_priority: Optional[str] = None,
    ticket_type: Optional[str] = None,
    story_id: Optional[int] = None,
    q: Optional[str] = None,
    watched_by_me: bool = False,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> StoryTaskListPage:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    if task_status is not None and task_status not in crud.TASK_STATUS_VALUES:
        raise HTTPException(400, "invalid task_status")
    if ticket_priority is not None and ticket_priority not in crud.TASK_PRIORITY_VALUES:
        raise HTTPException(400, "invalid ticket_priority")
    if ticket_type is not None and ticket_type not in crud.TASK_TYPE_VALUES:
        raise HTTPException(400, "invalid ticket_type")
    if story_id is not None:
        s = crud.story_get(db, story_id)
        if s is None or s.project_id != project_id:
            raise HTTPException(404, "Story not found")
    pm = crud.project_member_ids(db, project_id)
    if assignee_member_id is not None and assignee_member_id not in pm:
        raise HTTPException(400, "assignee_member_id is not a member of this project")
    watched_mid = current.member_id if watched_by_me else None
    rows, total = crud.project_tasks_page_out(
        db,
        project_id,
        assignee_member_id=assignee_member_id,
        task_status=task_status,
        ticket_priority=ticket_priority,
        ticket_type=ticket_type,
        story_id=story_id,
        watched_by_member_id=watched_mid,
        q=q,
        limit=limit,
        offset=offset,
    )
    return StoryTaskListPage(
        items=[StoryTaskOut.model_validate(x) for x in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/projects/{project_id}/tasks/{task_id}", response_model=StoryTaskOut)
def get_project_story_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> StoryTaskOut:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    row = crud.story_task_out_for_project_task(db, project_id, task_id)
    if row is None:
        raise HTTPException(404, "Ticket not found")
    return StoryTaskOut.model_validate(row)


@router.patch("/projects/{project_id}/tasks/{task_id}", response_model=StoryTaskOut)
def patch_project_task(
    project_id: int,
    task_id: int,
    body: StoryTaskPatch,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> StoryTaskOut:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Task not found")
    try:
        st2 = crud.story_task_patch(db, st, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return StoryTaskOut.model_validate(crud.story_task_to_out(db, st2))


@router.delete("/projects/{project_id}/tasks/{task_id}", status_code=204)
def delete_project_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Task not found")
    crud.story_task_delete(db, st)
    return Response(status_code=204)


@router.post("/projects/{project_id}/tasks", response_model=StoryTaskOut)
def create_project_task(
    project_id: int,
    body: StoryTaskCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> StoryTaskOut:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    try:
        st = crud.story_task_create_for_project(db, project_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return StoryTaskOut.model_validate(crud.story_task_to_out(db, st))


@router.post("/projects/{project_id}/tasks/{task_id}/watch", status_code=204)
def watch_project_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Task not found")
    try:
        crud.story_task_watch_add(db, task_id, current.member_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return Response(status_code=204)


@router.delete("/projects/{project_id}/tasks/{task_id}/watch", status_code=204)
def unwatch_project_task(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Task not found")
    crud.story_task_watch_remove(db, task_id, current.member_id)
    return Response(status_code=204)


@router.get("/projects/{project_id}/tasks/{task_id}/comments", response_model=list[TaskCommentOut])
def list_project_task_comments(
    project_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> list[models.StoryTaskComment]:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Ticket not found")
    return crud.task_comments_list(db, task_id)


@router.post("/projects/{project_id}/tasks/{task_id}/comments", response_model=TaskCommentOut)
def create_project_task_comment(
    project_id: int,
    task_id: int,
    comment: CommentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> models.StoryTaskComment:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Ticket not found")
    try:
        c = crud.task_comment_create(db, st, author_member_id=current.member_id, body=comment)
        db.refresh(c)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=p.id,
        project_name=p.name,
        event_type="agile_studio.task_comment.created",
        summary=f'New comment on ticket "{st.title[:80]}"',
        changed_fields=["task_comment"],
        data={
            "project_id": p.id,
            "task_id": st.id,
            "comment_id": c.id,
            "author_member_id": current.member_id,
            "story_ids": crud.story_task_story_ids_get(db, st.id),
            "body_preview": (c.body or "")[:8000],
            "recipient_hints": crud.recipient_hints_for_task_comment(
                db,
                p.id,
                comment_body=c.body,
                author_member_id=current.member_id,
            ),
        },
    )
    return c


@router.patch("/projects/{project_id}/tasks/{task_id}/comments/{comment_id}", response_model=TaskCommentOut)
def patch_project_task_comment(
    project_id: int,
    task_id: int,
    comment_id: int,
    body: CommentUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> models.StoryTaskComment:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Ticket not found")
    c = crud.task_comment_get(db, comment_id)
    if c is None or c.story_task_id != task_id:
        raise HTTPException(404, "Comment not found")
    try:
        crud.task_comment_update(db, c, editor_member_id=current.member_id, body=body)
        db.refresh(c)
        schedule_api_center_event_fanout(
            background_tasks,
            project_id=p.id,
            project_name=p.name,
            event_type="agile_studio.task_comment.updated",
            summary=f"Comment {c.id} updated on ticket {st.id}",
            changed_fields=["body"],
            data={
                "project_id": p.id,
                "task_id": st.id,
                "comment_id": c.id,
                "story_ids": crud.story_task_story_ids_get(db, st.id),
                "body_preview": (c.body or "")[:8000],
                "recipient_hints": crud.recipient_hints_for_task_comment(
                    db,
                    p.id,
                    comment_body=c.body,
                    author_member_id=current.member_id,
                ),
            },
        )
        return c
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e


@router.delete("/projects/{project_id}/tasks/{task_id}/comments/{comment_id}", status_code=204)
def delete_project_task_comment(
    project_id: int,
    task_id: int,
    comment_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        raise HTTPException(404, "Ticket not found")
    c = crud.task_comment_get(db, comment_id)
    if c is None or c.story_task_id != task_id:
        raise HTTPException(404, "Comment not found")
    cid = c.id
    try:
        crud.task_comment_delete(db, c, editor_member_id=current.member_id)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=p.id,
        project_name=p.name,
        event_type="agile_studio.task_comment.deleted",
        summary=f"Comment {cid} deleted on ticket {st.id}",
        changed_fields=["task_comment"],
        data={"project_id": p.id, "task_id": st.id, "comment_id": cid},
    )
    return Response(status_code=204)


@router.get("/projects/{project_id}/stories", response_model=list[StoryOut])
def list_stories(project_id: int, db: Session = Depends(get_db), status: Optional[str] = None) -> list[StoryOut]:
    p = _project_or_404(db, project_id)
    rows = crud.stories_list(db, project_id, status=status)
    sids = [s.id for s in rows]
    a_map = crud.story_assignee_ids_map_for_stories(db, sids)
    return [StoryOut.model_validate(crud.story_to_out(s, p.slug, db, assignee_ids=a_map.get(s.id, []))) for s in rows]


@router.get("/stories/{story_id}", response_model=StoryOut)
def get_story(story_id: int, db: Session = Depends(get_db)) -> StoryOut:
    s = _story_or_404(db, story_id)
    p = _project_or_404(db, s.project_id)
    return StoryOut.model_validate(crud.story_to_out(s, p.slug, db, include_tasks=True))


@router.get("/stories/{story_id}/tasks", response_model=list[StoryTaskOut])
def list_story_tasks(story_id: int, db: Session = Depends(get_db)) -> list[StoryTaskOut]:
    _story_or_404(db, story_id)
    return [StoryTaskOut.model_validate(x) for x in crud.story_tasks_out_list(db, story_id)]


@router.post("/stories/{story_id}/tasks", response_model=StoryTaskOut)
def create_story_task(
    story_id: int,
    body: StoryTaskCreate,
    db: Session = Depends(get_db),
) -> StoryTaskOut:
    _story_or_404(db, story_id)
    try:
        st = crud.story_task_create(db, story_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return StoryTaskOut.model_validate(crud.story_task_to_out(db, st))


@router.patch("/stories/{story_id}/tasks/{task_id}", response_model=StoryTaskOut)
def patch_story_task(
    story_id: int,
    task_id: int,
    body: StoryTaskPatch,
    db: Session = Depends(get_db),
) -> StoryTaskOut:
    _story_or_404(db, story_id)
    st = crud.story_task_get(db, task_id)
    if st is None or not crud.story_task_linked_to_story(db, task_id, story_id):
        raise HTTPException(404, "Task not found")
    try:
        st2 = crud.story_task_patch(db, st, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return StoryTaskOut.model_validate(crud.story_task_to_out(db, st2))


@router.delete("/stories/{story_id}/tasks/{task_id}", status_code=204)
def delete_story_task(story_id: int, task_id: int, db: Session = Depends(get_db)) -> Response:
    _story_or_404(db, story_id)
    st = crud.story_task_get(db, task_id)
    if st is None or not crud.story_task_linked_to_story(db, task_id, story_id):
        raise HTTPException(404, "Task not found")
    crud.story_task_delete(db, st)
    return Response(status_code=204)


@router.post("/stories/{story_id}/tasks/{task_id}/watch", status_code=204)
def watch_story_task(
    story_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    s = _story_or_404(db, story_id)
    _require_project_member(db, s.project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or not crud.story_task_linked_to_story(db, task_id, story_id):
        raise HTTPException(404, "Task not found")
    try:
        crud.story_task_watch_add(db, task_id, current.member_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return Response(status_code=204)


@router.delete("/stories/{story_id}/tasks/{task_id}/watch", status_code=204)
def unwatch_story_task(
    story_id: int,
    task_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    s = _story_or_404(db, story_id)
    _require_project_member(db, s.project_id, current.member_id)
    st = crud.story_task_get(db, task_id)
    if st is None or not crud.story_task_linked_to_story(db, task_id, story_id):
        raise HTTPException(404, "Task not found")
    crud.story_task_watch_remove(db, task_id, current.member_id)
    return Response(status_code=204)


@router.patch("/stories/{story_id}", response_model=StoryOut)
def patch_story(
    story_id: int,
    body: StoryPatch,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> StoryOut:
    s = _story_or_404(db, story_id)
    p = _project_or_404(db, s.project_id)
    _require_project_workflow_selected(db, p)
    mids = crud.project_member_ids(db, p.id)
    old_status = s.status
    try:
        crud.story_patch(db, s, body, project_member_ids_set=mids)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if body.status is not None and s.status != old_status:
        crud.story_status_event_create(
            db,
            story_id=s.id,
            actor_member_id=current.member_id,
            from_status=old_status,
            to_status=s.status,
        )
    db.refresh(s)
    keys = [str(k) for k in body.model_dump(exclude_unset=True).keys() if k]
    if keys:
        st_key = f"{p.slug}-{s.story_number}"
        schedule_api_center_event_fanout(
            background_tasks,
            project_id=p.id,
            project_name=p.name,
            event_type="agile_studio.story.updated",
            summary=f"Story {st_key} updated: {s.title}",
            changed_fields=keys,
            data={
                "project_id": p.id,
                "story_id": s.id,
                "story_key": st_key,
                "from_status": old_status,
                "to_status": s.status,
                "title": s.title,
                "patched_field_names": keys,
            },
        )
    return StoryOut.model_validate(crud.story_to_out(s, p.slug, db, include_tasks=True))


@router.get("/stories/{story_id}/status-events", response_model=list[StoryStatusEventOut])
def list_story_status_events(
    story_id: int, db: Session = Depends(get_db), limit: int = 100
) -> list[models.StoryStatusEvent]:
    _story_or_404(db, story_id)
    return crud.story_status_events_list(db, story_id, limit=min(limit, 300))


# --- Comments ---
@router.get("/stories/{story_id}/comments", response_model=list[CommentOut])
def list_comments(story_id: int, db: Session = Depends(get_db)) -> list[models.StoryComment]:
    _story_or_404(db, story_id)
    return crud.comments_list(db, story_id)


@router.post("/stories/{story_id}/comments", response_model=CommentOut)
def create_comment(
    story_id: int,
    comment: CommentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> models.StoryComment:
    s = _story_or_404(db, story_id)
    p = _project_or_404(db, s.project_id)
    try:
        c = crud.comment_create(db, s, author_member_id=current.member_id, body=comment)
        db.refresh(c)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    st_key = f"{p.slug}-{s.story_number}"
    cfg = wq_webhook.parse_webhook_config(
        p.settings_json if isinstance(p.settings_json, dict) else None
    )
    if cfg:
        post_url, token, agent_id = cfg
        author = crud.member_get(db, current.member_id)
        author_name = author.display_name if author else "member"
        background_tasks.add_task(
            wq_webhook.background_story_comment,
            post_url,
            token,
            agent_id,
            p.slug,
            p.name,
            st_key,
            s.title,
            s.status,
            c.body,
            author_name,
        )
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=p.id,
        project_name=p.name,
        event_type="agile_studio.comment.created",
        summary=f"New comment on {st_key}",
        changed_fields=["comment"],
        data={
            "project_id": p.id,
            "story_id": s.id,
            "story_key": st_key,
            "comment_id": c.id,
            "author_member_id": current.member_id,
            "body_preview": (c.body or "")[:8000],
            "recipient_hints": crud.recipient_hints_for_story_comment(
                db,
                p.id,
                s,
                comment_body=c.body,
                author_member_id=current.member_id,
            ),
        },
    )
    chat_sync.notify_story_chat_event(
        p.id,
        s.id,
        "story.comment.created",
        {"comment": _comment_out_json(db, c)},
    )
    return c


@router.patch("/stories/{story_id}/comments/{comment_id}", response_model=CommentOut)
def patch_comment(
    story_id: int,
    comment_id: int,
    body: CommentUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> models.StoryComment:
    s = _story_or_404(db, story_id)
    p = _project_or_404(db, s.project_id)
    c = crud.comment_get(db, comment_id)
    if c is None or c.story_id != story_id:
        raise HTTPException(404, "Comment not found")
    try:
        crud.comment_update(db, c, editor_member_id=current.member_id, body=body)
        db.refresh(c)
        st_key = f"{p.slug}-{s.story_number}"
        schedule_api_center_event_fanout(
            background_tasks,
            project_id=p.id,
            project_name=p.name,
            event_type="agile_studio.comment.updated",
            summary=f"Comment {c.id} updated on {st_key}",
            changed_fields=["body"],
            data={
                "project_id": p.id,
                "story_id": s.id,
                "story_key": st_key,
                "comment_id": c.id,
                "body_preview": (c.body or "")[:8000],
                "recipient_hints": crud.recipient_hints_for_story_comment(
                    db,
                    p.id,
                    s,
                    comment_body=c.body,
                    author_member_id=current.member_id,
                ),
            },
        )
        chat_sync.notify_story_chat_event(
            p.id,
            s.id,
            "story.comment.updated",
            {"comment": _comment_out_json(db, c)},
        )
        return c
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e


@router.delete("/stories/{story_id}/comments/{comment_id}", status_code=204)
def delete_comment(
    story_id: int,
    comment_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    s = _story_or_404(db, story_id)
    p = _project_or_404(db, s.project_id)
    c = crud.comment_get(db, comment_id)
    if c is None or c.story_id != story_id:
        raise HTTPException(404, "Comment not found")
    st_key = f"{p.slug}-{s.story_number}"
    cid = c.id
    try:
        crud.comment_delete(db, c, editor_member_id=current.member_id)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=p.id,
        project_name=p.name,
        event_type="agile_studio.comment.deleted",
        summary=f"Comment {cid} deleted on {st_key}",
        changed_fields=["comment"],
        data={"project_id": p.id, "story_id": s.id, "story_key": st_key, "comment_id": cid},
    )
    chat_sync.notify_story_chat_event(
        p.id,
        s.id,
        "story.comment.deleted",
        {"comment_id": cid},
    )
    return Response(status_code=204)


# --- Wiki / Docs ---
@router.get("/projects/{project_id}/wiki-folders/tree", response_model=WikiFolderTreeResponse)
def wiki_folders_tree(
    project_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiFolderTreeResponse:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    rows = crud.wiki_folders_list_all(db, project_id)
    tree_raw = crud.wiki_folders_build_tree(rows)
    return WikiFolderTreeResponse(
        tree=[WikiFolderTreeNode.model_validate(n) for n in tree_raw],
    )


@router.post("/projects/{project_id}/wiki-folders", response_model=WikiFolderOut)
def wiki_folder_create(
    project_id: int,
    body: WikiFolderCreate,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiFolderOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    try:
        fold = crud.wiki_folder_create(db, project_id, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return WikiFolderOut.model_validate(fold)


@router.patch("/projects/{project_id}/wiki-folders/{folder_id}", response_model=WikiFolderOut)
def wiki_folder_patch_route(
    project_id: int,
    folder_id: int,
    body: WikiFolderPatch,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiFolderOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    fold = crud.wiki_folder_for_project(db, project_id, folder_id)
    if fold is None:
        raise HTTPException(404, "folder not found")
    try:
        fold2 = crud.wiki_folder_patch(db, fold, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return WikiFolderOut.model_validate(fold2)


@router.delete("/projects/{project_id}/wiki-folders/{folder_id}", status_code=204)
def wiki_folder_delete_route(
    project_id: int,
    folder_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    fold = crud.wiki_folder_for_project(db, project_id, folder_id)
    if fold is None:
        raise HTTPException(404, "folder not found")
    crud.wiki_folder_delete(db, fold)
    return Response(status_code=204)


@router.post("/projects/{project_id}/docs", response_model=WikiDocOut)
def wiki_doc_create(
    project_id: int,
    body: WikiDocCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiDocOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    try:
        doc = crud.wiki_doc_create(db, project_id, body, current.member_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="agile_studio.wiki_document.created",
        summary=f'Wiki doc created «{doc.title}»',
        changed_fields=["wiki_document"],
        data=wiki_document_webhook_data_dict(doc),
    )
    return WikiDocOut.model_validate(crud.wiki_doc_to_out(db, doc, project_slug=p.slug))


@router.get("/projects/{project_id}/docs", response_model=list[WikiDocOut])
def wiki_doc_list(
    project_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
    story_id: Optional[int] = None,
    in_folder: Optional[int] = Query(None, description="Only documents in this folder id"),
    unfiled: bool = Query(False, description="Only documents without a folder"),
    q: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 100,
) -> list[WikiDocOut]:
    if unfiled and in_folder is not None:
        raise HTTPException(400, "use either unfiled or in_folder, not both")
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    rows = crud.wiki_documents_list(
        db,
        project_id,
        story_id=story_id,
        folder_id=in_folder,
        unfiled_only=unfiled,
        q=q,
        tag=tag,
        limit=limit,
    )
    return [WikiDocOut.model_validate(crud.wiki_doc_to_out(db, r, project_slug=p.slug)) for r in rows]


@router.get("/projects/{project_id}/docs/search", response_model=WikiDocSearchOut)
def wiki_doc_search(
    project_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
    query: Optional[str] = None,
    semantic_query: Optional[str] = None,
    story_id: Optional[int] = None,
    in_folder: Optional[int] = Query(None),
    unfiled: bool = Query(False),
    tag: Optional[str] = None,
    top_k: int = 15,
) -> WikiDocSearchOut:
    if unfiled and in_folder is not None:
        raise HTTPException(400, "use either unfiled or in_folder, not both")
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    top_k = min(max(top_k, 1), 50)
    sem_q = (semantic_query or "").strip()
    kw_q = (query or "").strip()

    if sem_q:
        pairs = crud.wiki_docs_semantic_search(db, project_id, sem_q, story_id=story_id, top_k=top_k)
        results: list[WikiDocOut] = []
        tl = (tag or "").strip().lower()
        for sc, d in pairs:
            if tl:
                if not d.tags_json or not any(str(x).strip().lower() == tl for x in d.tags_json):
                    continue
            results.append(
                WikiDocOut.model_validate(
                    crud.wiki_doc_to_out(db, d, project_slug=p.slug, semantic_score=float(sc)),
                )
            )
        return WikiDocSearchOut(query=kw_q or None, semantic_query=sem_q, results=results[:top_k])

    rows = crud.wiki_documents_list(
        db,
        project_id,
        story_id=story_id,
        folder_id=in_folder,
        unfiled_only=unfiled,
        q=kw_q or None,
        tag=tag,
        limit=top_k,
    )
    return WikiDocSearchOut(
        query=kw_q or None,
        semantic_query=None,
        results=[WikiDocOut.model_validate(crud.wiki_doc_to_out(db, r, project_slug=p.slug)) for r in rows],
    )


@router.get("/projects/{project_id}/docs/context", response_model=list[WikiDocOut])
def wiki_doc_context(
    project_id: int,
    story_id: int,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
    limit: int = 16,
) -> list[WikiDocOut]:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    try:
        rows = crud.wiki_context_for_story(db, project_id, story_id, limit=min(limit, 80))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return [WikiDocOut.model_validate(x) for x in rows]


@router.get("/projects/{project_id}/docs/slug/{slug}", response_model=WikiDocOut)
def wiki_doc_get_by_slug_route(
    project_id: int,
    slug: str,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiDocOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get_by_slug(db, project_id, slug)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return WikiDocOut.model_validate(crud.wiki_doc_to_out(db, doc, project_slug=p.slug))


@router.get("/projects/{project_id}/docs/{doc_id}", response_model=WikiDocOut)
def wiki_doc_get(
    project_id: int,
    doc_id: str,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiDocOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    return WikiDocOut.model_validate(crud.wiki_doc_to_out(db, doc, project_slug=p.slug))


@router.put("/projects/{project_id}/docs/{doc_id}", response_model=WikiDocOut)
def wiki_doc_put(
    project_id: int,
    doc_id: str,
    body: WikiDocPatch,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiDocOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    try:
        doc2 = crud.wiki_doc_patch(db, doc, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="agile_studio.wiki_document.updated",
        summary=f'Wiki doc updated «{doc2.title}»',
        changed_fields=["wiki_document"],
        data=wiki_document_webhook_data_dict(doc2),
    )
    return WikiDocOut.model_validate(crud.wiki_doc_to_out(db, doc2, project_slug=p.slug))


@router.delete("/projects/{project_id}/docs/{doc_id}", status_code=204)
def wiki_doc_delete(
    project_id: int,
    doc_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    snap = wiki_document_webhook_data_dict(doc)
    crud.wiki_doc_delete(db, doc)
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="agile_studio.wiki_document.deleted",
        summary=f'Wiki doc deleted «{snap.get("title", "")}»',
        changed_fields=["wiki_document"],
        data=snap,
    )
    return Response(status_code=204)


@router.get(
    "/projects/{project_id}/docs/{doc_id}/comments",
    response_model=list[WikiCommentOut],
)
def wiki_comments_list_route(
    project_id: int,
    doc_id: str,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
    include_resolved: bool = False,
) -> list[WikiCommentOut]:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    rows = crud.wiki_comments_list_for_doc(db, doc_id, include_resolved=include_resolved)
    return [WikiCommentOut.model_validate(crud.wiki_comment_to_dict(db, r)) for r in rows]


@router.get(
    "/projects/{project_id}/docs/{doc_id}/comments/count",
    response_model=WikiCommentCountOut,
)
def wiki_comments_count_route(
    project_id: int,
    doc_id: str,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiCommentCountOut:
    _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    n = crud.wiki_comments_visible_count(db, doc_id)
    open_tc, resolved_tc = crud.wiki_comment_root_thread_counts(db, doc_id)
    return WikiCommentCountOut(
        visible_count=n,
        open_thread_count=open_tc,
        resolved_thread_count=resolved_tc,
    )


@router.post("/projects/{project_id}/docs/{doc_id}/comments", response_model=WikiCommentOut)
def wiki_comments_create_route(
    project_id: int,
    doc_id: str,
    body: WikiCommentCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiCommentOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    try:
        row = crud.wiki_comment_create(db, doc, body, current.member_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="wiki_comment_created",
        summary=f'New wiki comment on «{doc.title}»',
        changed_fields=["wiki_comment"],
        data=wiki_comment_webhook_data_dict(
            db, project_id, doc, row, current.member_id,
        ),
    )
    chat_sync.notify_wiki_doc_chat_event(
        project_id,
        doc_id,
        "wiki.comment.created",
        {"comment": _wiki_comment_out_json(db, row)},
    )
    return WikiCommentOut.model_validate(crud.wiki_comment_to_dict(db, row))


@router.patch(
    "/projects/{project_id}/docs/{doc_id}/comments/{comment_id}",
    response_model=WikiCommentOut,
)
def wiki_comments_patch_route(
    project_id: int,
    doc_id: str,
    comment_id: str,
    body: WikiCommentPatch,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> WikiCommentOut:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    row = db.get(models.WikiComment, comment_id)
    if row is None or row.doc_id != doc_id:
        raise HTTPException(404, "Comment not found")
    patch_data = body.model_dump(exclude_unset=True)
    if not patch_data:
        raise HTTPException(400, "No fields to update")
    if "status" in patch_data and row.parent_id is not None:
        raise HTTPException(
            400,
            "Only the root message of a feedback thread can be resolved or reopened",
        )
    if "content" in patch_data:
        if row.author_member_id != current.member_id:
            raise HTTPException(403, "Only the author may edit this comment text")
    try:
        row2 = crud.wiki_comment_patch(db, row, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    extra_hints = (
        crud.recipient_hints_for_wiki_comment(
            db,
            project_id,
            doc,
            comment_body=row2.content,
            author_member_id=current.member_id,
        )
        if "content" in patch_data
        else None
    )
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="wiki_comment_updated",
        summary=f'Wiki comment updated on «{doc.title}»',
        changed_fields=list(patch_data.keys()),
        data=(
            dict(
                **wiki_comment_webhook_data_dict(db, project_id, doc, row2, current.member_id),
                status=row2.status,
            )
            if extra_hints is not None
            else {
                "wiki_document_id": doc.id,
                "wiki_comment_id": row2.id,
                "wiki_thread_root_id": row2.parent_id or row2.id,
                "doc_slug": doc.slug,
                "doc_title": doc.title,
                "author_member_id": current.member_id,
                "status": row2.status,
                "body_preview": (row2.content or "")[:2000],
                "content_preview": (row2.content or "")[:2000],
            }
        ),
    )
    chat_sync.notify_wiki_doc_chat_event(
        project_id,
        doc_id,
        "wiki.comment.updated",
        {"comment": _wiki_comment_out_json(db, row2)},
    )
    return WikiCommentOut.model_validate(crud.wiki_comment_to_dict(db, row2))


@router.delete(
    "/projects/{project_id}/docs/{doc_id}/comments/{comment_id}",
    status_code=204,
)
def wiki_comments_delete_route(
    project_id: int,
    doc_id: str,
    comment_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current: models.User = Depends(get_current_user),
) -> Response:
    p = _project_or_404(db, project_id)
    _require_project_member(db, project_id, current.member_id)
    doc = crud.wiki_doc_get(db, doc_id)
    if doc is None or doc.project_id != project_id:
        raise HTTPException(404, "Document not found")
    row = db.get(models.WikiComment, comment_id)
    if row is None or row.doc_id != doc_id:
        raise HTTPException(404, "Comment not found")
    cid = row.id
    was_root = row.parent_id is None
    try:
        crud.wiki_comment_delete(db, row, editor_member_id=current.member_id)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    schedule_api_center_event_fanout(
        background_tasks,
        project_id=project_id,
        project_name=p.name,
        event_type="wiki_comment_deleted",
        summary=f'Wiki comment deleted on «{doc.title}»',
        changed_fields=["wiki_comment"],
        data={
            "wiki_document_id": doc.id,
            "wiki_comment_id": cid,
            "doc_slug": doc.slug,
            "doc_title": doc.title,
            "author_member_id": current.member_id,
            "deleted_thread_root": was_root,
        },
    )
    chat_sync.notify_wiki_doc_chat_event(
        project_id,
        doc_id,
        "wiki.comment.deleted",
        {"comment_id": cid},
    )
    return Response(status_code=204)
