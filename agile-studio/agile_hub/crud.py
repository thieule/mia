from __future__ import annotations

from typing import Any

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import re
import secrets
import uuid

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from . import models, wiki_embedding
from .schemas import (
    CommentCreate,
    CommentUpdate,
    MemberCreate,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectPatch,
    ProjectSettingsWrite,
    WorkflowTemplateCreate,
    WorkspaceRoleCreate,
    WorkspaceRolePatch,
    StoryCreate,
    StoryPatch,
    StoryTaskCreate,
    StoryTaskPatch,
    ReleaseCreate,
    ReleasePatch,
    WikiFolderCreate,
    WikiFolderPatch,
    WikiDocCreate,
    WikiDocPatch,
    WikiCommentCreate,
    WikiCommentPatch,
)

_COMMENT_MENTION_RE = re.compile(r"@([A-Za-z0-9._-]+)")


def _ticket_dt_naive_utc(d: datetime | None) -> datetime | None:
    """Store due dates as naive UTC datetimes for MySQL DATETIME consistency."""
    if d is None:
        return None
    if getattr(d, "tzinfo", None) is not None:
        return d.astimezone(timezone.utc).replace(tzinfo=None)
    return d

TASK_STATUS_VALUES = frozenset({"open", "in_progress", "blocked", "done"})
TASK_PRIORITY_VALUES = frozenset({"low", "medium", "high", "urgent"})
TASK_TYPE_VALUES = frozenset({"task", "bug", "feature", "chore", "technical_debt", "docs", "support", "other"})

INVITE_VALID_DAYS = 14

_WORKSPACE_ROLE_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def workspace_role_get_by_slug(db: Session, slug: str) -> models.WorkspaceRole | None:
    s = (slug or "").strip().lower()
    if not s:
        return None
    return db.scalar(select(models.WorkspaceRole).where(models.WorkspaceRole.slug == s))


def workspace_role_resolve_slug(db: Session, role: str | None) -> str:
    slug = (role or "member").strip().lower() or "member"
    if workspace_role_get_by_slug(db, slug) is None:
        raise ValueError(
            f"Unknown role «{slug}». Add it in Master data (Roles) or use an existing slug."
        )
    return slug


def _normalize_invite_email(email: str) -> str:
    return (email or "").strip().lower()


def project_invite_revoke_pending(db: Session, project_id: int, email_norm: str) -> None:
    now = datetime.utcnow()
    rows = db.scalars(
        select(models.ProjectInvite).where(
            models.ProjectInvite.project_id == project_id,
            models.ProjectInvite.email == email_norm,
            models.ProjectInvite.accepted_at.is_(None),
            models.ProjectInvite.revoked_at.is_(None),
        )
    ).all()
    for r in rows:
        r.revoked_at = now


def project_invite_create(
    db: Session,
    *,
    project_id: int,
    email: str,
    role: str,
    invited_by_member_id: int | None,
) -> models.ProjectInvite:
    email_norm = _normalize_invite_email(email)
    if not email_norm or "@" not in email_norm:
        raise ValueError("Invalid email")
    mids = project_member_ids(db, project_id)
    u = user_get_by_email(db, email_norm)
    if u is not None and u.member_id in mids:
        raise ValueError("That user is already a member of this project")
    project_invite_revoke_pending(db, project_id, email_norm)
    token = secrets.token_urlsafe(48)[:96]
    now = datetime.utcnow()
    exp = now + timedelta(days=INVITE_VALID_DAYS)
    resolved_role = workspace_role_resolve_slug(db, role)
    row = models.ProjectInvite(
        project_id=project_id,
        email=email_norm,
        token=token,
        role=resolved_role,
        invited_by_member_id=invited_by_member_id,
        created_at=now,
        expires_at=exp,
    )
    db.add(row)
    db.flush()
    return row


def project_invite_get_by_token(db: Session, token: str) -> models.ProjectInvite | None:
    t = (token or "").strip()
    if not t:
        return None
    return db.scalar(select(models.ProjectInvite).where(models.ProjectInvite.token == t))


def project_invite_is_usable(row: models.ProjectInvite | None) -> tuple[bool, str]:
    if row is None:
        return False, "not_found"
    now = datetime.utcnow()
    if row.revoked_at is not None:
        return False, "revoked"
    if row.accepted_at is not None:
        return False, "accepted"
    if row.expires_at <= now:
        return False, "expired"
    return True, "ok"


def project_invite_list_pending_for_project(db: Session, project_id: int) -> list[models.ProjectInvite]:
    now = datetime.utcnow()
    return list(
        db.scalars(
            select(models.ProjectInvite)
            .where(
                models.ProjectInvite.project_id == project_id,
                models.ProjectInvite.accepted_at.is_(None),
                models.ProjectInvite.revoked_at.is_(None),
                models.ProjectInvite.expires_at > now,
            )
            .order_by(models.ProjectInvite.created_at.desc())
        ).all()
    )


def project_invite_list_pending_for_user_email(db: Session, email: str) -> list[models.ProjectInvite]:
    email_norm = _normalize_invite_email(email)
    now = datetime.utcnow()
    return list(
        db.scalars(
            select(models.ProjectInvite)
            .where(
                models.ProjectInvite.email == email_norm,
                models.ProjectInvite.accepted_at.is_(None),
                models.ProjectInvite.revoked_at.is_(None),
                models.ProjectInvite.expires_at > now,
            )
            .order_by(models.ProjectInvite.created_at.desc())
        ).all()
    )


def project_invite_accept(db: Session, token: str, user: models.User) -> tuple[models.ProjectMember, bool]:
    """Returns (link, joined_as_new_member)."""
    row = project_invite_get_by_token(db, token)
    ok, reason = project_invite_is_usable(row)
    if not ok or row is None:
        raise ValueError(reason)
    email_norm = _normalize_invite_email(user.email)
    if email_norm != row.email:
        raise ValueError("email_mismatch")
    mids = project_member_ids(db, row.project_id)
    if user.member_id in mids:
        row.accepted_at = datetime.utcnow()
        db.flush()
        link = db.get(models.ProjectMember, (row.project_id, user.member_id))
        if link is None:
            raise RuntimeError("member_missing_link")
        return link, False
    body = ProjectMemberAdd(member_id=user.member_id, role=row.role or "member")
    link = project_add_member(db, row.project_id, body)
    row.accepted_at = datetime.utcnow()
    db.flush()
    return link, True


def project_invite_try_accept_for_new_user(db: Session, token: str | None, user: models.User) -> bool:
    if not (token or "").strip():
        return False
    try:
        project_invite_accept(db, token.strip(), user)
        return True
    except ValueError:
        return False


def project_invite_revoke(db: Session, invite_id: int, project_id: int) -> bool:
    row = db.get(models.ProjectInvite, invite_id)
    if row is None or row.project_id != project_id:
        return False
    if row.accepted_at is not None:
        return False
    row.revoked_at = datetime.utcnow()
    db.flush()
    return True


def _mention_key_from_display_name(name: str) -> str:
    return re.sub(r"\s+", "", (name or "").strip()).lower()


def _normalize_agent_mention_token(raw: str) -> str:
    """Khớp @miamia-ba (UI) với catalog agent id ``mia-ba``."""
    t = (raw or "").strip().lower()
    if t.startswith("miamia-"):
        return "mia-" + t[7:]
    return t


def _extract_comment_mention_keys(body: str) -> set[str]:
    return {m.group(1).lower() for m in _COMMENT_MENTION_RE.finditer(body or "")}


def _mention_match_keys_for_ai_member(mem: models.Member) -> set[str]:
    keys: set[str] = set()
    aid = (mem.agent_id or "").strip()
    if not aid:
        return keys
    al = aid.lower()
    keys.add(al)
    keys.add(_normalize_agent_mention_token(al))
    if (mem.display_name or "").strip():
        keys.add(_mention_key_from_display_name(mem.display_name))
    if al.startswith("mia-"):
        keys.add("miamia-" + al[4:])
    return {k for k in keys if k}


def mentioned_agent_ids_from_comment_body(db: Session, project_id: int, body: str) -> list[str]:
    """Agent catalog ids (@mention trong comment khớp member AI của project)."""
    raw_keys = _extract_comment_mention_keys(body)
    if not raw_keys:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for link in project_members_list(db, project_id):
        mem = member_get(db, link.member_id)
        if mem is None or (mem.member_type or "").strip().lower() != "ai":
            continue
        catalog_aid = (mem.agent_id or "").strip()
        if not catalog_aid:
            continue
        match_keys = _mention_match_keys_for_ai_member(mem)
        hit = False
        for rk in raw_keys:
            nrk = _normalize_agent_mention_token(rk)
            if rk in match_keys or nrk in match_keys:
                hit = True
                break
        if hit:
            low = catalog_aid.lower()
            if low not in seen:
                seen.add(low)
                out.append(catalog_aid)
    return out


def story_ai_assignee_agent_ids(db: Session, story_id: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for mid in story_assignee_ids_get(db, story_id):
        mem = member_get(db, mid)
        if mem is None or (mem.member_type or "").strip().lower() != "ai":
            continue
        aid = (mem.agent_id or "").strip()
        if aid and aid.lower() not in seen:
            seen.add(aid.lower())
            out.append(aid)
    return out


def project_ai_agent_catalog_ids(db: Session, project_id: int) -> list[str]:
    """Các ``agent_id`` runtime (catalog) của member AI trên project."""
    out: list[str] = []
    seen: set[str] = set()
    for link in project_members_list(db, project_id):
        mem = member_get(db, link.member_id)
        if mem is None or (mem.member_type or "").strip().lower() != "ai":
            continue
        aid = (mem.agent_id or "").strip()
        if aid and aid.lower() not in seen:
            seen.add(aid.lower())
            out.append(aid)
    return out


def project_ai_agent_member_ids_map(db: Session, project_id: int) -> dict[str, int]:
    """Catalog ``agent_id`` -> ``members.id`` for AI project members (MCP ``agile_comment_create`` author)."""
    out: dict[str, int] = {}
    seen: set[str] = set()
    for link in project_members_list(db, project_id):
        mem = member_get(db, link.member_id)
        if mem is None or (mem.member_type or "").strip().lower() != "ai":
            continue
        aid = (mem.agent_id or "").strip()
        if not aid or aid.lower() in seen:
            continue
        seen.add(aid.lower())
        out[aid] = int(mem.id)
    return out


def recipient_hints_for_wiki_comment(
    db: Session,
    project_id: int,
    doc: models.WikiDocument,
    *,
    comment_body: str,
    author_member_id: int,
) -> dict[str, Any]:
    mentioned = mentioned_agent_ids_from_comment_body(db, project_id, comment_body)
    excerpt = (comment_body or "").strip()
    if len(excerpt) > 4000:
        excerpt = excerpt[:3997] + "..."
    return {
        "mentioned_agent_ids": mentioned,
        "comment_excerpt": excerpt,
        "author_member_id": author_member_id,
        "ai_member_ids_by_agent": project_ai_agent_member_ids_map(db, project_id),
        "wiki_document_id": doc.id,
        "wiki_doc_slug": doc.slug,
        "wiki_doc_title": doc.title,
    }


def recipient_hints_for_story_comment(
    db: Session,
    project_id: int,
    story: models.Story,
    *,
    comment_body: str,
    author_member_id: int,
) -> dict[str, Any]:
    mentioned = mentioned_agent_ids_from_comment_body(db, project_id, comment_body)
    assignees = story_ai_assignee_agent_ids(db, story.id)
    excerpt = (comment_body or "").strip()
    if len(excerpt) > 4000:
        excerpt = excerpt[:3997] + "..."
    return {
        "mentioned_agent_ids": mentioned,
        "story_assignee_agent_ids": assignees,
        "comment_excerpt": excerpt,
        "author_member_id": author_member_id,
        "ai_member_ids_by_agent": project_ai_agent_member_ids_map(db, project_id),
    }


def recipient_hints_for_task_comment(
    db: Session,
    project_id: int,
    *,
    comment_body: str,
    author_member_id: int,
) -> dict[str, Any]:
    mentioned = mentioned_agent_ids_from_comment_body(db, project_id, comment_body)
    excerpt = (comment_body or "").strip()
    if len(excerpt) > 4000:
        excerpt = excerpt[:3997] + "..."
    return {
        "mentioned_agent_ids": mentioned,
        "comment_excerpt": excerpt,
        "author_member_id": author_member_id,
        "ai_member_ids_by_agent": project_ai_agent_member_ids_map(db, project_id),
    }


def _validate_comment_mentions_in_project(db: Session, project_id: int, body_text: str) -> None:
    keys = _extract_comment_mention_keys(body_text)
    if not keys:
        return
    members = project_members_list(db, project_id)
    allowed = {
        _mention_key_from_display_name(mem.display_name)
        for mem in (member_get(db, link.member_id) for link in members)
        if mem is not None and (mem.display_name or "").strip()
    }
    unknown = sorted(k for k in keys if k not in allowed)
    if unknown:
        raise ValueError(f"Unknown mention(s): {', '.join('@' + k for k in unknown)}")


def _workflow_status_normalize(status: str) -> str:
    """
    Normalize workflow-specific statuses on backend so behavior is consistent
    even when clients send intermediate labels.
    """
    s = (status or "").strip()
    if s == "icebox_approved":
        # Approved idea leaves Icebox and enters Backlog.
        return "backlog_unstart"
    return s


def member_create(db: Session, body: MemberCreate) -> models.Member:
    m = models.Member(
        member_type=body.member_type,
        display_name=body.display_name.strip(),
        email=(body.email or "").strip() or None,
        agent_id=(body.agent_id or "").strip() or None,
        meta_json=body.meta_json,
    )
    db.add(m)
    db.flush()
    return m


def member_get(db: Session, member_id: int) -> models.Member | None:
    return db.get(models.Member, member_id)


def member_get_by_agent_id(db: Session, agent_id: str) -> models.Member | None:
    aid = (agent_id or "").strip()
    if not aid:
        return None
    return db.scalar(select(models.Member).where(models.Member.agent_id == aid))


def members_list(db: Session, *, limit: int = 200) -> list[models.Member]:
    return list(db.scalars(select(models.Member).order_by(models.Member.id.desc()).limit(limit)).all())


def merge_project_settings_json(existing: dict | None, write: ProjectSettingsWrite) -> dict:
    out = dict(existing or {})
    for k, v in write.model_dump(exclude_unset=True).items():
        if k == "workflow_template_id":
            if v is None:
                continue
            try:
                iv = int(v)
            except Exception:
                out.pop(k, None)
                continue
            if iv <= 0:
                out.pop(k, None)
            else:
                out[k] = iv
            continue
        if v is None:
            continue
        if isinstance(v, str):
            t = v.strip()
            if not t:
                out.pop(k, None)
            else:
                out[k] = t
        else:
            out[k] = v
    return out


def api_center_connection_get(db: Session) -> models.ApiCenterConnection | None:
    return db.get(models.ApiCenterConnection, 1)


def api_center_connection_upsert(
    db: Session,
    *,
    endpoint: str,
    connect_secret: str,
    session_key: str | None,
    api_endpoints: dict | None = None,
) -> models.ApiCenterConnection:
    row = api_center_connection_get(db)
    if row is None:
        row = models.ApiCenterConnection(
            id=1,
            endpoint=endpoint.strip().rstrip("/"),
            connect_secret=connect_secret,
            session_key=(session_key or "").strip() or None,
            api_endpoints_json=api_endpoints if isinstance(api_endpoints, dict) else None,
        )
    else:
        row.endpoint = endpoint.strip().rstrip("/")
        row.connect_secret = connect_secret
        row.session_key = (session_key or "").strip() or None
        if isinstance(api_endpoints, dict):
            row.api_endpoints_json = api_endpoints
    db.add(row)
    db.flush()
    return row


def api_center_connection_set_mcp_api_key(db: Session, *, mcp_api_key: str) -> models.ApiCenterConnection:
    row = api_center_connection_get(db)
    if row is None:
        raise ValueError("api_center_not_connected")
    row.mcp_api_key = (mcp_api_key or "").strip() or None
    db.add(row)
    db.flush()
    return row


def api_center_generate_mcp_api_key() -> str:
    return f"mcp_{secrets.token_urlsafe(24)}"


def project_create(db: Session, body: ProjectCreate) -> models.Project:
    p = models.Project(
        slug=body.slug,
        name=body.name.strip(),
        description=body.description,
        status=body.status,
        workspace_ref=(body.workspace_ref or "").strip() or None,
        settings_json=None,
    )
    db.add(p)
    db.flush()
    return p


def project_get(db: Session, project_id: int) -> models.Project | None:
    return db.get(models.Project, project_id)


def project_get_by_slug(db: Session, slug: str) -> models.Project | None:
    return db.scalar(select(models.Project).where(models.Project.slug == slug))


def projects_list(db: Session, *, limit: int = 100) -> list[models.Project]:
    return list(db.scalars(select(models.Project).order_by(models.Project.id.desc()).limit(limit)).all())


def workflow_templates_list(db: Session, *, limit: int = 200) -> list[models.WorkflowTemplate]:
    return list(
        db.scalars(select(models.WorkflowTemplate).order_by(models.WorkflowTemplate.id.desc()).limit(limit)).all()
    )


def workflow_template_get(db: Session, template_id: int) -> models.WorkflowTemplate | None:
    return db.get(models.WorkflowTemplate, template_id)


def workflow_template_create(db: Session, body: WorkflowTemplateCreate) -> models.WorkflowTemplate:
    row = models.WorkflowTemplate(
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
    )
    db.add(row)
    db.flush()
    return row


def workspace_roles_list(db: Session, *, limit: int = 500) -> list[models.WorkspaceRole]:
    lim = min(max(limit, 1), 1000)
    return list(
        db.scalars(
            select(models.WorkspaceRole)
            .order_by(models.WorkspaceRole.sort_order.asc(), models.WorkspaceRole.slug.asc())
            .limit(lim)
        ).all()
    )


def workspace_role_get(db: Session, role_id: int) -> models.WorkspaceRole | None:
    return db.get(models.WorkspaceRole, role_id)


def workspace_role_create(db: Session, body: WorkspaceRoleCreate) -> models.WorkspaceRole:
    slug = body.slug.strip().lower()
    if not _WORKSPACE_ROLE_SLUG_RE.match(slug):
        raise ValueError(
            "Slug must start with a letter and use only lowercase letters, digits, underscores (max 63 chars)."
        )
    row = models.WorkspaceRole(
        slug=slug,
        name=body.name.strip(),
        description=(body.description or "").strip() or None,
        sort_order=int(body.sort_order),
        is_system=False,
    )
    db.add(row)
    db.flush()
    return row


def workspace_role_patch(db: Session, row: models.WorkspaceRole, body: WorkspaceRolePatch) -> models.WorkspaceRole:
    if body.name is not None:
        row.name = body.name.strip()
    if body.description is not None:
        row.description = (body.description or "").strip() or None
    if body.sort_order is not None:
        row.sort_order = int(body.sort_order)
    db.add(row)
    db.flush()
    return row


def workspace_role_usage_count(db: Session, slug: str) -> int:
    s = (slug or "").strip().lower()
    n_pm = db.scalar(select(func.count()).select_from(models.ProjectMember).where(models.ProjectMember.role == s))
    n_pi = db.scalar(
        select(func.count()).select_from(models.ProjectInvite).where(
            models.ProjectInvite.role == s,
            models.ProjectInvite.accepted_at.is_(None),
            models.ProjectInvite.revoked_at.is_(None),
        )
    )
    return int(n_pm or 0) + int(n_pi or 0)


def workspace_role_delete(db: Session, row: models.WorkspaceRole) -> None:
    if row.is_system:
        raise ValueError("Cannot delete a system role")
    if workspace_role_usage_count(db, row.slug) > 0:
        raise ValueError("Role is still used by project members or pending invitations")
    db.delete(row)


def project_patch(db: Session, p: models.Project, body: ProjectPatch) -> models.Project:
    if body.name is not None:
        p.name = body.name.strip()
    if body.description is not None:
        p.description = body.description
    if body.status is not None:
        p.status = body.status
    if body.workspace_ref is not None:
        p.workspace_ref = (body.workspace_ref or "").strip() or None
    if body.settings is not None:
        merged = merge_project_settings_json(p.settings_json, body.settings)
        wf_id = merged.get("workflow_template_id")
        if wf_id is not None and workflow_template_get(db, int(wf_id)) is None:
            raise ValueError("workflow_template_id does not exist")
        p.settings_json = merged
    db.add(p)
    db.flush()
    return p


def project_member_ids(db: Session, project_id: int) -> set[int]:
    rows = db.scalars(
        select(models.ProjectMember.member_id).where(models.ProjectMember.project_id == project_id)
    ).all()
    return set(rows)


def project_add_member(db: Session, project_id: int, body: ProjectMemberAdd) -> models.ProjectMember:
    resolved = workspace_role_resolve_slug(db, body.role)
    link = models.ProjectMember(project_id=project_id, member_id=body.member_id, role=resolved)
    db.add(link)
    db.flush()
    return link


def project_remove_member(db: Session, project_id: int, member_id: int) -> bool:
    link = db.get(models.ProjectMember, (project_id, member_id))
    if link is None:
        return False
    db.delete(link)
    return True


def project_members_list(db: Session, project_id: int) -> list[models.ProjectMember]:
    return list(
        db.scalars(
            select(models.ProjectMember)
            .where(models.ProjectMember.project_id == project_id)
            .order_by(models.ProjectMember.joined_at)
        ).all()
    )


def _dedupe_preserve(ids: list[int]) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


def _assignee_ids_from_create(body: StoryCreate) -> list[int]:
    if body.assignee_ids is not None:
        return _dedupe_preserve(list(body.assignee_ids))
    if body.assignee_id is not None:
        return [body.assignee_id]
    return []


def story_assignee_ids_get(db: Session, story_id: int) -> list[int]:
    rows = db.scalars(
        select(models.StoryAssignee.member_id)
        .where(models.StoryAssignee.story_id == story_id)
        .order_by(models.StoryAssignee.member_id)
    ).all()
    return [int(x) for x in rows]


def story_assignee_ids_map_for_stories(db: Session, story_ids: list[int]) -> dict[int, list[int]]:
    if not story_ids:
        return {}
    rows = db.execute(
        select(models.StoryAssignee.story_id, models.StoryAssignee.member_id)
        .where(models.StoryAssignee.story_id.in_(story_ids))
        .order_by(models.StoryAssignee.story_id, models.StoryAssignee.member_id)
    ).all()
    out: dict[int, list[int]] = {}
    for sid, mid in rows:
        out.setdefault(int(sid), []).append(int(mid))
    return out


def story_set_assignees(
    db: Session, s: models.Story, member_ids: list[int], project_member_ids_set: set[int]
) -> None:
    for mid in member_ids:
        if mid not in project_member_ids_set:
            raise ValueError("assignee must be a project member in this project")
    ordered = _dedupe_preserve(member_ids)
    db.execute(delete(models.StoryAssignee).where(models.StoryAssignee.story_id == s.id))
    for mid in ordered:
        db.add(models.StoryAssignee(story_id=s.id, member_id=mid))
    s.assignee_id = ordered[0] if ordered else None
    db.add(s)
    db.flush()


def _next_story_number(db: Session, project_id: int) -> int:
    m = db.scalar(select(func.max(models.Story.story_number)).where(models.Story.project_id == project_id))
    return int(m or 0) + 1


def _release_in_project_or_none(db: Session, release_id: int | None, project_id: int) -> int | None:
    if release_id is None:
        return None
    r = release_get(db, release_id)
    if r is None or r.project_id != project_id:
        raise ValueError("release_id must be a release in this project")
    return release_id


def story_create(db: Session, project_id: int, body: StoryCreate) -> models.Story:
    mids_set = project_member_ids(db, project_id)
    want_assignees = _assignee_ids_from_create(body)
    for mid in want_assignees:
        if mid not in mids_set:
            raise ValueError("assignee must be a member assigned to this project")
    if body.reporter_id is not None and body.reporter_id not in mids_set:
        raise ValueError("reporter_id must be a member assigned to this project")
    rel_id = _release_in_project_or_none(db, body.release_id, project_id)
    n = _next_story_number(db, project_id)
    rlab = (body.release_label or "").strip() or None
    s = models.Story(
        project_id=project_id,
        story_number=n,
        title=body.title.strip(),
        description=body.description,
        status=_workflow_status_normalize(body.status),
        priority=body.priority,
        story_points=body.story_points,
        release_label=rlab,
        assignee_id=want_assignees[0] if want_assignees else None,
        reporter_id=body.reporter_id,
        release_id=rel_id,
    )
    db.add(s)
    db.flush()
    if want_assignees:
        story_set_assignees(db, s, want_assignees, mids_set)
    return s


def story_get(db: Session, story_id: int) -> models.Story | None:
    return db.get(models.Story, story_id)


def stories_list(db: Session, project_id: int, *, status: str | None = None) -> list[models.Story]:
    q = select(models.Story).where(models.Story.project_id == project_id)
    if status:
        q = q.where(models.Story.status == status)
    q = q.order_by(models.Story.story_number)
    return list(db.scalars(q).all())


def story_patch(db: Session, s: models.Story, body: StoryPatch, *, project_member_ids_set: set[int]) -> models.Story:
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        s.title = str(data["title"]).strip()
    if "description" in data:
        s.description = data["description"]
    if "status" in data and data["status"] is not None:
        s.status = _workflow_status_normalize(str(data["status"]))
    if "priority" in data:
        s.priority = data["priority"]
    if "story_points" in data:
        s.story_points = data["story_points"]
    if "assignee_ids" in data or "assignee_id" in data:
        if "assignee_ids" in data:
            mlist = _dedupe_preserve([int(x) for x in (data.get("assignee_ids") or [])])
        else:
            aid = data.get("assignee_id")
            mlist = [int(aid)] if aid is not None else []
        story_set_assignees(db, s, mlist, project_member_ids_set)
    if "reporter_id" in data:
        rid = data["reporter_id"]
        if rid is not None and rid not in project_member_ids_set:
            raise ValueError("reporter_id must be a member assigned to this project")
        s.reporter_id = rid
    if "release_id" in data:
        rid = data["release_id"]
        s.release_id = _release_in_project_or_none(db, rid, s.project_id)
    if "release_label" in data:
        lab = data["release_label"]
        if lab is None:
            s.release_label = None
        else:
            t = str(lab).strip()
            s.release_label = t or None
    db.add(s)
    db.flush()
    return s


def _end_of_local_day(d: datetime) -> datetime:
    day = d.date() if isinstance(d, datetime) else d
    return datetime.combine(day, time(23, 59, 59, 999000))


def _resolve_new_release_window(
    starts_at: datetime | None, ends_at: datetime | None
) -> tuple[datetime | None, datetime | None]:
    if starts_at is None and ends_at is None:
        return None, None
    if starts_at is None and ends_at is not None:
        raise ValueError("ends_at cannot be set without starts_at")
    s = starts_at
    e = ends_at
    if s is not None and e is None:
        e = _end_of_local_day(s)
    if s is not None and e is not None and s > e:
        raise ValueError("starts_at must be on or before ends_at")
    return s, e


def release_create(db: Session, project_id: int, body: ReleaseCreate) -> models.Release:
    s, e = _resolve_new_release_window(body.starts_at, body.ends_at)
    r = models.Release(
        project_id=project_id,
        name=body.name.strip(),
        description=body.description,
        status=body.status,
        starts_at=s,
        ends_at=e,
        released_at=body.released_at,
    )
    db.add(r)
    db.flush()
    return r


def release_get(db: Session, release_id: int) -> models.Release | None:
    return db.get(models.Release, release_id)


def releases_list(db: Session, project_id: int) -> list[models.Release]:
    return list(
        db.scalars(
            select(models.Release)
            .where(models.Release.project_id == project_id)
            .order_by(models.Release.created_at.desc())
        ).all()
    )


def release_patch(db: Session, r: models.Release, body: ReleasePatch) -> models.Release:
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        r.name = data["name"].strip()
    if "description" in data:
        r.description = data["description"]
    if "status" in data and data["status"] is not None:
        r.status = data["status"]
    if "released_at" in data:
        r.released_at = data["released_at"]
    if "starts_at" in data or "ends_at" in data:
        s = r.starts_at if "starts_at" not in data else data.get("starts_at")
        e = r.ends_at if "ends_at" not in data else data.get("ends_at")
        if s is None and e is not None:
            raise ValueError("ends_at cannot be set without starts_at")
        if s is not None and e is None:
            e = _end_of_local_day(s)
        if s is not None and e is not None and s > e:
            raise ValueError("starts_at must be on or before ends_at")
        r.starts_at = s
        r.ends_at = e
    db.add(r)
    db.flush()
    return r


def release_delete(db: Session, r: models.Release) -> None:
    db.delete(r)
    db.flush()


def comment_create(db: Session, story: models.Story, *, author_member_id: int, body: CommentCreate) -> models.StoryComment:
    mids = project_member_ids(db, story.project_id)
    if author_member_id not in mids:
        raise ValueError("You must be a project member to comment on this story")
    clean_body = body.body.strip()
    _validate_comment_mentions_in_project(db, story.project_id, clean_body)
    c = models.StoryComment(story_id=story.id, author_member_id=author_member_id, body=clean_body)
    db.add(c)
    db.flush()
    return c


def comments_list(db: Session, story_id: int) -> list[models.StoryComment]:
    return list(
        db.scalars(
            select(models.StoryComment)
            .options(joinedload(models.StoryComment.author))
            .where(models.StoryComment.story_id == story_id)
            .order_by(models.StoryComment.created_at)
        )
        .unique()
        .all()
    )


def comment_get(db: Session, comment_id: int) -> models.StoryComment | None:
    return db.scalar(
        select(models.StoryComment)
        .options(joinedload(models.StoryComment.author))
        .where(models.StoryComment.id == comment_id)
    )


def comment_update(
    db: Session, comment: models.StoryComment, *, editor_member_id: int, body: CommentUpdate
) -> models.StoryComment:
    if comment.author_member_id != editor_member_id:
        raise PermissionError("Only the author can edit this comment")
    clean_body = body.body.strip()
    story = story_get(db, comment.story_id)
    if story is None:
        raise ValueError("Story not found")
    _validate_comment_mentions_in_project(db, story.project_id, clean_body)
    comment.body = clean_body
    db.add(comment)
    db.flush()
    return comment


def comment_delete(db: Session, comment: models.StoryComment, *, editor_member_id: int) -> None:
    if comment.author_member_id != editor_member_id:
        raise PermissionError("Only the author can delete this comment")
    db.delete(comment)
    db.flush()


def task_comment_create(
    db: Session, task: models.StoryTask, *, author_member_id: int, body: CommentCreate
) -> models.StoryTaskComment:
    mids = project_member_ids(db, task.project_id)
    if author_member_id not in mids:
        raise ValueError("You must be a project member to comment on this ticket")
    clean_body = body.body.strip()
    _validate_comment_mentions_in_project(db, task.project_id, clean_body)
    c = models.StoryTaskComment(story_task_id=task.id, author_member_id=author_member_id, body=clean_body)
    db.add(c)
    db.flush()
    return c


def task_comments_list(db: Session, task_id: int) -> list[models.StoryTaskComment]:
    return list(
        db.scalars(
            select(models.StoryTaskComment)
            .options(joinedload(models.StoryTaskComment.author))
            .where(models.StoryTaskComment.story_task_id == task_id)
            .order_by(models.StoryTaskComment.created_at)
        )
        .unique()
        .all()
    )


def task_comment_get(db: Session, comment_id: int) -> models.StoryTaskComment | None:
    return db.scalar(
        select(models.StoryTaskComment)
        .options(joinedload(models.StoryTaskComment.author))
        .where(models.StoryTaskComment.id == comment_id)
    )


def task_comment_update(
    db: Session, comment: models.StoryTaskComment, *, editor_member_id: int, body: CommentUpdate
) -> models.StoryTaskComment:
    if comment.author_member_id != editor_member_id:
        raise PermissionError("Only the author can edit this comment")
    clean_body = body.body.strip()
    task = story_task_get(db, comment.story_task_id)
    if task is None:
        raise ValueError("Ticket not found")
    _validate_comment_mentions_in_project(db, task.project_id, clean_body)
    comment.body = clean_body
    db.add(comment)
    db.flush()
    return comment


def task_comment_delete(db: Session, comment: models.StoryTaskComment, *, editor_member_id: int) -> None:
    if comment.author_member_id != editor_member_id:
        raise PermissionError("Only the author can delete this comment")
    db.delete(comment)
    db.flush()


def story_status_event_create(
    db: Session,
    *,
    story_id: int,
    actor_member_id: int,
    from_status: str,
    to_status: str,
) -> models.StoryStatusEvent:
    ev = models.StoryStatusEvent(
        story_id=story_id,
        actor_member_id=actor_member_id,
        from_status=(from_status or "").strip(),
        to_status=(to_status or "").strip(),
    )
    db.add(ev)
    db.flush()
    return ev


def story_status_events_list(db: Session, story_id: int, *, limit: int = 100) -> list[models.StoryStatusEvent]:
    return list(
        db.scalars(
            select(models.StoryStatusEvent)
            .options(joinedload(models.StoryStatusEvent.actor))
            .where(models.StoryStatusEvent.story_id == story_id)
            .order_by(models.StoryStatusEvent.created_at.desc(), models.StoryStatusEvent.id.desc())
            .limit(limit)
        )
        .unique()
        .all()
    )


def story_touch_updated(db: Session, story_id: int) -> None:
    s = story_get(db, story_id)
    if s is None:
        return
    s.updated_at = datetime.utcnow()
    db.add(s)
    db.flush()


def story_task_story_ids_get(db: Session, task_id: int) -> list[int]:
    rows = db.scalars(
        select(models.StoryTaskStory.story_id)
        .where(models.StoryTaskStory.task_id == task_id)
        .order_by(models.StoryTaskStory.story_id)
    ).all()
    return [int(x) for x in rows]


def story_task_story_ids_map_for_tasks(db: Session, task_ids: list[int]) -> dict[int, list[int]]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(models.StoryTaskStory.task_id, models.StoryTaskStory.story_id).where(
            models.StoryTaskStory.task_id.in_(task_ids)
        )
    ).all()
    m: dict[int, list[int]] = {tid: [] for tid in task_ids}
    for tid, sid in rows:
        m[int(tid)].append(int(sid))
    for tid in m:
        m[tid].sort()
    return m


def story_task_linked_to_story(db: Session, task_id: int, story_id: int) -> bool:
    return (
        db.scalar(
            select(func.count())
            .select_from(models.StoryTaskStory)
            .where(
                models.StoryTaskStory.task_id == task_id,
                models.StoryTaskStory.story_id == story_id,
            )
        )
        or 0
    ) > 0


def _validate_story_ids_in_project(db: Session, project_id: int, story_ids: list[int]) -> None:
    if not story_ids:
        return
    q = select(models.Story.id).where(
        models.Story.project_id == project_id,
        models.Story.id.in_(story_ids),
    )
    found = set(int(x) for x in db.scalars(q).all())
    missing = [x for x in story_ids if x not in found]
    if missing:
        raise ValueError("every story_id must belong to this project")


def story_task_set_story_links(db: Session, task: models.StoryTask, story_ids: list[int], project_id: int) -> None:
    _validate_story_ids_in_project(db, project_id, story_ids)
    ordered = _dedupe_preserve(list(story_ids))
    db.execute(delete(models.StoryTaskStory).where(models.StoryTaskStory.task_id == task.id))
    for sid in ordered:
        db.add(models.StoryTaskStory(task_id=task.id, story_id=sid))
    db.flush()


def story_tasks_list(db: Session, story_id: int) -> list[models.StoryTask]:
    stmt = (
        select(models.StoryTask)
        .join(models.StoryTaskStory, models.StoryTaskStory.task_id == models.StoryTask.id)
        .where(models.StoryTaskStory.story_id == story_id)
        .order_by(models.StoryTask.sort_order, models.StoryTask.id)
    )
    return list(db.scalars(stmt).all())


def _project_tasks_filtered_select(
    project_id: int,
    *,
    assignee_member_id: int | None = None,
    task_status: str | None = None,
    ticket_priority: str | None = None,
    ticket_type: str | None = None,
    story_id: int | None = None,
    watched_by_member_id: int | None = None,
    q: str | None = None,
):
    stmt = select(models.StoryTask).where(models.StoryTask.project_id == project_id)
    if story_id is not None:
        stmt = stmt.where(
            exists().where(
                models.StoryTaskStory.task_id == models.StoryTask.id,
                models.StoryTaskStory.story_id == story_id,
            )
        )
    if assignee_member_id is not None:
        stmt = stmt.where(
            exists().where(
                models.StoryTaskAssignee.task_id == models.StoryTask.id,
                models.StoryTaskAssignee.member_id == assignee_member_id,
            )
        )
    if task_status is not None:
        stmt = stmt.where(models.StoryTask.task_status == task_status)
    if ticket_priority is not None:
        stmt = stmt.where(models.StoryTask.ticket_priority == ticket_priority)
    if ticket_type is not None:
        stmt = stmt.where(models.StoryTask.ticket_type == ticket_type)
    if watched_by_member_id is not None:
        stmt = stmt.where(
            exists().where(
                models.StoryTaskWatcher.task_id == models.StoryTask.id,
                models.StoryTaskWatcher.member_id == watched_by_member_id,
            )
        )
    if isinstance(q, str) and q.strip():
        pat = f"%{q.strip()}%"
        stmt = stmt.where(models.StoryTask.title.like(pat))
    return stmt


def project_tasks_count_filtered(
    db: Session,
    project_id: int,
    *,
    assignee_member_id: int | None = None,
    task_status: str | None = None,
    ticket_priority: str | None = None,
    ticket_type: str | None = None,
    story_id: int | None = None,
    watched_by_member_id: int | None = None,
    q: str | None = None,
) -> int:
    stmt = _project_tasks_filtered_select(
        project_id,
        assignee_member_id=assignee_member_id,
        task_status=task_status,
        ticket_priority=ticket_priority,
        ticket_type=ticket_type,
        story_id=story_id,
        watched_by_member_id=watched_by_member_id,
        q=q,
    )
    n = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return int(n or 0)


def project_tasks_list_filtered(
    db: Session,
    project_id: int,
    *,
    assignee_member_id: int | None = None,
    task_status: str | None = None,
    ticket_priority: str | None = None,
    ticket_type: str | None = None,
    story_id: int | None = None,
    watched_by_member_id: int | None = None,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[models.StoryTask]:
    stmt = _project_tasks_filtered_select(
        project_id,
        assignee_member_id=assignee_member_id,
        task_status=task_status,
        ticket_priority=ticket_priority,
        ticket_type=ticket_type,
        story_id=story_id,
        watched_by_member_id=watched_by_member_id,
        q=q,
    )
    stmt = stmt.order_by(models.StoryTask.updated_at.desc(), models.StoryTask.sort_order, models.StoryTask.id)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def _project_tasks_rows_to_out(db: Session, project_id: int, rows: list[models.StoryTask]) -> list[dict]:
    if not rows:
        return []
    p = project_get(db, project_id)
    slug = (p.slug or "").strip() if p else ""
    tids = [x.id for x in rows]
    sid_map = story_task_story_ids_map_for_tasks(db, tids)
    all_story_ids = sorted({i for lst in sid_map.values() for i in lst})
    smap: dict[int, models.Story] = {}
    if all_story_ids:
        smap = {s.id: s for s in db.scalars(select(models.Story).where(models.Story.id.in_(all_story_ids))).all()}
    amap = story_task_assignee_ids_map_for_tasks(db, tids)
    wmap = story_task_watcher_ids_map_for_tasks(db, tids)
    out: list[dict] = []
    for x in rows:
        sids = sid_map.get(x.id, [])
        keys: list[str] = []
        titles: list[str] = []
        for sid in sids:
            s = smap.get(sid)
            if s:
                keys.append(f"{slug}-{s.story_number}" if slug else f"#{s.story_number}")
                titles.append(s.title or "")
        aids = amap.get(x.id, [])
        wids = wmap.get(x.id, [])
        aid0 = aids[0] if aids else None
        out.append(
            {
                "id": x.id,
                "project_id": x.project_id,
                "story_ids": sids,
                "story_id": sids[0] if sids else None,
                "title": x.title,
                "body": x.body,
                "done": bool(x.done),
                "task_status": x.task_status or "open",
                "ticket_priority": x.ticket_priority or "medium",
                "ticket_type": x.ticket_type or "task",
                "due_at": x.due_at,
                "acceptance_criteria": x.acceptance_criteria,
                "sort_order": x.sort_order,
                "assignee_ids": aids,
                "assignee_id": aid0,
                "reporter_id": x.reporter_id,
                "watcher_member_ids": wids,
                "story_keys": keys,
                "story_titles": titles,
                "story_key": keys[0] if keys else None,
                "story_title": titles[0] if titles else None,
                "created_at": x.created_at,
                "updated_at": x.updated_at,
            }
        )
    return out


def project_tasks_page_out(
    db: Session,
    project_id: int,
    *,
    assignee_member_id: int | None = None,
    task_status: str | None = None,
    ticket_priority: str | None = None,
    ticket_type: str | None = None,
    story_id: int | None = None,
    watched_by_member_id: int | None = None,
    q: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[dict], int]:
    filt = dict(
        assignee_member_id=assignee_member_id,
        task_status=task_status,
        ticket_priority=ticket_priority,
        ticket_type=ticket_type,
        story_id=story_id,
        watched_by_member_id=watched_by_member_id,
        q=q,
    )
    total = project_tasks_count_filtered(db, project_id, **filt)
    rows = project_tasks_list_filtered(db, project_id, **filt, limit=limit, offset=offset)
    return _project_tasks_rows_to_out(db, project_id, rows), total


def _validate_task_reporter(reporter_id: int | None, project_member_ids_set: set[int]) -> None:
    if reporter_id is None:
        return
    if reporter_id not in project_member_ids_set:
        raise ValueError("reporter must be a project member in this project")


def story_task_assignee_ids_get(db: Session, task_id: int) -> list[int]:
    rows = db.scalars(
        select(models.StoryTaskAssignee.member_id)
        .where(models.StoryTaskAssignee.task_id == task_id)
        .order_by(models.StoryTaskAssignee.member_id)
    ).all()
    return [int(x) for x in rows]


def story_task_assignee_ids_map_for_tasks(db: Session, task_ids: list[int]) -> dict[int, list[int]]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(models.StoryTaskAssignee.task_id, models.StoryTaskAssignee.member_id)
        .where(models.StoryTaskAssignee.task_id.in_(task_ids))
        .order_by(models.StoryTaskAssignee.task_id, models.StoryTaskAssignee.member_id)
    ).all()
    out: dict[int, list[int]] = {}
    for tid, mid in rows:
        out.setdefault(int(tid), []).append(int(mid))
    return out


def story_task_watcher_ids_get(db: Session, task_id: int) -> list[int]:
    rows = db.scalars(
        select(models.StoryTaskWatcher.member_id)
        .where(models.StoryTaskWatcher.task_id == task_id)
        .order_by(models.StoryTaskWatcher.member_id)
    ).all()
    return [int(x) for x in rows]


def story_task_watcher_ids_map_for_tasks(db: Session, task_ids: list[int]) -> dict[int, list[int]]:
    if not task_ids:
        return {}
    rows = db.execute(
        select(models.StoryTaskWatcher.task_id, models.StoryTaskWatcher.member_id)
        .where(models.StoryTaskWatcher.task_id.in_(task_ids))
        .order_by(models.StoryTaskWatcher.task_id, models.StoryTaskWatcher.member_id)
    ).all()
    out: dict[int, list[int]] = {}
    for tid, mid in rows:
        out.setdefault(int(tid), []).append(int(mid))
    return out


def story_task_watch_add(db: Session, task_id: int, member_id: int) -> None:
    st = story_task_get(db, task_id)
    if st is None:
        raise ValueError("Task not found")
    mids = project_member_ids(db, st.project_id)
    if member_id not in mids:
        raise ValueError("Watcher must be a project member in this project")
    exists_row = db.scalar(
        select(models.StoryTaskWatcher.member_id).where(
            models.StoryTaskWatcher.task_id == task_id,
            models.StoryTaskWatcher.member_id == member_id,
        )
    )
    if exists_row is None:
        db.add(models.StoryTaskWatcher(task_id=task_id, member_id=member_id))
        db.flush()


def story_task_watch_remove(db: Session, task_id: int, member_id: int) -> None:
    db.execute(
        delete(models.StoryTaskWatcher).where(
            models.StoryTaskWatcher.task_id == task_id,
            models.StoryTaskWatcher.member_id == member_id,
        )
    )
    db.flush()


def story_task_set_assignees(
    db: Session, task: models.StoryTask, member_ids: list[int], project_member_ids_set: set[int]
) -> None:
    for mid in member_ids:
        if mid not in project_member_ids_set:
            raise ValueError("task assignee must be a project member in this project")
    ordered = _dedupe_preserve(member_ids)
    db.execute(delete(models.StoryTaskAssignee).where(models.StoryTaskAssignee.task_id == task.id))
    for mid in ordered:
        db.add(models.StoryTaskAssignee(task_id=task.id, member_id=mid))
    db.flush()


def story_task_to_out(db: Session, task: models.StoryTask, *, project_slug: str | None = None) -> dict:
    aids = story_task_assignee_ids_get(db, task.id)
    aid0 = aids[0] if aids else None
    wids = story_task_watcher_ids_get(db, task.id)
    sids = story_task_story_ids_get(db, task.id)
    if project_slug is None:
        p = project_get(db, task.project_id)
        project_slug = (p.slug or "").strip() if p else ""
    slug = project_slug or ""
    keys: list[str] = []
    titles: list[str] = []
    if sids:
        srows = db.scalars(select(models.Story).where(models.Story.id.in_(sids))).all()
        smap = {s.id: s for s in srows}
        for sid in sids:
            s = smap.get(sid)
            if s:
                keys.append(f"{slug}-{s.story_number}" if slug else f"#{s.story_number}")
                titles.append(s.title or "")
    return {
        "id": task.id,
        "project_id": task.project_id,
        "story_ids": sids,
        "story_id": sids[0] if sids else None,
        "title": task.title,
        "body": task.body,
        "done": bool(task.done),
        "task_status": task.task_status or "open",
        "ticket_priority": task.ticket_priority or "medium",
        "ticket_type": task.ticket_type or "task",
        "due_at": task.due_at,
        "acceptance_criteria": task.acceptance_criteria,
        "sort_order": task.sort_order,
        "assignee_ids": aids,
        "assignee_id": aid0,
        "reporter_id": task.reporter_id,
        "watcher_member_ids": wids,
        "story_keys": keys,
        "story_titles": titles,
        "story_key": keys[0] if keys else None,
        "story_title": titles[0] if titles else None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def story_tasks_out_list(db: Session, story_id: int) -> list[dict]:
    rows = story_tasks_list(db, story_id)
    if not rows:
        return []
    p = project_get(db, rows[0].project_id)
    slug = (p.slug or "").strip() if p else ""
    return [story_task_to_out(db, x, project_slug=slug) for x in rows]


def _next_project_task_sort_order(db: Session, project_id: int) -> int:
    m = db.scalar(
        select(func.coalesce(func.max(models.StoryTask.sort_order), -1)).where(
            models.StoryTask.project_id == project_id
        )
    )
    return int(m) + 1


def story_task_create_for_project(db: Session, project_id: int, body: StoryTaskCreate) -> models.StoryTask:
    mids = project_member_ids(db, project_id)
    _validate_task_reporter(body.reporter_id, mids)
    ord_ = body.sort_order if body.sort_order is not None else _next_project_task_sort_order(db, project_id)
    raw_body = body.body
    body_clean = raw_body.strip() if isinstance(raw_body, str) else None
    want_aids = _dedupe_preserve(list(body.assignee_ids))
    if body.task_status is not None:
        ts = str(body.task_status).strip().lower()
        if ts not in TASK_STATUS_VALUES:
            raise ValueError("invalid task_status")
    else:
        ts = "done" if bool(body.done) else "open"
    done_val = ts == "done"
    tp = str(body.ticket_priority).strip().lower()
    if tp not in TASK_PRIORITY_VALUES:
        raise ValueError("invalid ticket_priority")
    tt = str(body.ticket_type).strip().lower()
    if tt not in TASK_TYPE_VALUES:
        raise ValueError("invalid ticket_type")
    due = _ticket_dt_naive_utc(body.due_at)
    raw_ac = body.acceptance_criteria
    ac = raw_ac.strip() if isinstance(raw_ac, str) else None
    link_ids = _dedupe_preserve(list(body.story_ids or []))
    _validate_story_ids_in_project(db, project_id, link_ids)
    st = models.StoryTask(
        project_id=project_id,
        title=body.title.strip(),
        body=body_clean or None,
        done=done_val,
        task_status=ts,
        ticket_priority=tp,
        ticket_type=tt,
        due_at=due,
        acceptance_criteria=ac or None,
        sort_order=ord_,
        reporter_id=body.reporter_id,
    )
    db.add(st)
    db.flush()
    story_task_set_assignees(db, st, want_aids, mids)
    story_task_set_story_links(db, st, link_ids, project_id)
    for sid in story_task_story_ids_get(db, st.id):
        story_touch_updated(db, sid)
    return st


def story_task_create(db: Session, story_id: int, body: StoryTaskCreate) -> models.StoryTask:
    s = story_get(db, story_id)
    if s is None:
        raise ValueError("Story not found")
    merged = body.model_copy(
        update={"story_ids": _dedupe_preserve(list(body.story_ids or []) + [story_id])}
    )
    return story_task_create_for_project(db, s.project_id, merged)


def story_task_get(db: Session, task_id: int) -> models.StoryTask | None:
    return db.get(models.StoryTask, task_id)


def story_task_out_for_project_task(db: Session, project_id: int, task_id: int) -> dict | None:
    """``story_task_to_out`` when the task belongs to ``project_id``."""
    st = story_task_get(db, task_id)
    if st is None or st.project_id != project_id:
        return None
    p = project_get(db, project_id)
    slug = (p.slug or "").strip() if p else ""
    return story_task_to_out(db, st, project_slug=slug)


def story_task_patch(db: Session, st: models.StoryTask, body: StoryTaskPatch) -> models.StoryTask:
    mids = project_member_ids(db, st.project_id)
    data = body.model_dump(exclude_unset=True)
    touch_sids_before = set(story_task_story_ids_get(db, st.id))
    if "assignee_ids" in data:
        mlist = _dedupe_preserve([int(x) for x in (data.get("assignee_ids") or [])])
        story_task_set_assignees(db, st, mlist, mids)
    if "reporter_id" in data:
        rid = data["reporter_id"]
        _validate_task_reporter(rid, mids)
        st.reporter_id = rid
    if "title" in data and data["title"] is not None:
        st.title = str(data["title"]).strip()
    if "body" in data:
        b = data["body"]
        if b is None:
            st.body = None
        else:
            t = str(b).strip()
            st.body = t or None
    if "ticket_priority" in data and data["ticket_priority"] is not None:
        tp = str(data["ticket_priority"]).strip().lower()
        if tp not in TASK_PRIORITY_VALUES:
            raise ValueError("invalid ticket_priority")
        st.ticket_priority = tp
    if "ticket_type" in data and data["ticket_type"] is not None:
        tt = str(data["ticket_type"]).strip().lower()
        if tt not in TASK_TYPE_VALUES:
            raise ValueError("invalid ticket_type")
        st.ticket_type = tt
    if "due_at" in data:
        st.due_at = _ticket_dt_naive_utc(data.get("due_at"))
    if "acceptance_criteria" in data:
        ac = data["acceptance_criteria"]
        if ac is None:
            st.acceptance_criteria = None
        else:
            t = str(ac).strip()
            st.acceptance_criteria = t or None
    done_in = data.get("done")
    ts_in = data.get("task_status")
    if ts_in is not None:
        ts = str(ts_in).strip().lower()
        if ts not in TASK_STATUS_VALUES:
            raise ValueError("invalid task_status")
        st.task_status = ts
        st.done = ts == "done"
    elif done_in is not None:
        st.done = bool(done_in)
        if st.done:
            st.task_status = "done"
        elif (st.task_status or "") == "done":
            st.task_status = "open"
    if "sort_order" in data and data["sort_order"] is not None:
        st.sort_order = int(data["sort_order"])
    if "story_ids" in data and data["story_ids"] is not None:
        story_task_set_story_links(db, st, list(data["story_ids"]), st.project_id)
    db.add(st)
    db.flush()
    touch_after = set(story_task_story_ids_get(db, st.id))
    for sid in touch_sids_before | touch_after:
        story_touch_updated(db, sid)
    return st


def story_task_delete(db: Session, st: models.StoryTask) -> None:
    sids = story_task_story_ids_get(db, st.id)
    db.delete(st)
    db.flush()
    for sid in sids:
        story_touch_updated(db, sid)


def user_get_by_email(db: Session, email: str) -> models.User | None:
    e = email.strip().lower()
    return db.scalar(select(models.User).where(models.User.email == e))


def user_create(db: Session, *, email: str, password_hash: str, display_name: str, member_id: int) -> models.User:
    u = models.User(
        email=email.strip().lower(),
        password_hash=password_hash,
        display_name=display_name.strip(),
        member_id=member_id,
    )
    db.add(u)
    db.flush()
    return u


def story_to_out(
    s: models.Story,
    project_slug: str,
    db: Session,
    assignee_ids: list[int] | None = None,
    *,
    include_tasks: bool = False,
) -> dict:
    aids = assignee_ids if assignee_ids is not None else story_assignee_ids_get(db, s.id)
    if not aids and s.assignee_id is not None:
        aids = [s.assignee_id]
    aid0 = aids[0] if aids else None
    out: dict = {
        "id": s.id,
        "project_id": s.project_id,
        "story_key": f"{project_slug}-{s.story_number}",
        "story_number": s.story_number,
        "title": s.title,
        "description": s.description,
        "status": s.status,
        "priority": s.priority,
        "story_points": s.story_points,
        "release_id": s.release_id,
        "release_label": s.release_label,
        "assignee_id": aid0,
        "assignee_ids": aids,
        "reporter_id": s.reporter_id,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
        "tasks": [],
    }
    if include_tasks:
        out["tasks"] = story_tasks_out_list(db, s.id)
    return out


# --- Wiki documents ---

_SLUG_PART = re.compile(r"[^a-z0-9]+")


def wiki_slugify(raw: str) -> str:
    s = _SLUG_PART.sub("-", (raw or "").lower().strip())
    s = re.sub(r"-+", "-", s).strip("-")
    return (s or "doc")[:128]


def wiki_unique_slug(db: Session, project_id: int, base: str) -> str:
    b = wiki_slugify(base)[:120]
    for i in range(0, 2000):
        cand = b if i == 0 else f"{b}-{i}"
        hit = db.scalar(
            select(models.WikiDocument.id).where(
                models.WikiDocument.project_id == project_id,
                models.WikiDocument.slug == cand,
            )
        )
        if hit is None:
            return cand
    return f"{b}-{uuid.uuid4().hex[:10]}"


def _wiki_story_must_be_in_project(db: Session, project_id: int, story_id: int | None) -> None:
    if story_id is None:
        return
    s = story_get(db, story_id)
    if s is None or s.project_id != project_id:
        raise ValueError("story does not exist or is not in this project")


def _wiki_story_ids_from_create(body: WikiDocCreate) -> list[int]:
    raw: list[int] = []
    for x in body.story_ids or []:
        if x is not None and int(x) > 0:
            raw.append(int(x))
    if body.story_id is not None and int(body.story_id) > 0:
        raw.append(int(body.story_id))
    out: list[int] = []
    seen: set[int] = set()
    for x in raw:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    out.sort()
    return out


def wiki_folder_get(db: Session, folder_id: int) -> models.WikiFolder | None:
    return db.get(models.WikiFolder, folder_id)


def wiki_folder_for_project(db: Session, project_id: int, folder_id: int) -> models.WikiFolder | None:
    f = wiki_folder_get(db, folder_id)
    if f is None or f.project_id != project_id:
        return None
    return f


def _wiki_folder_name_unique(
    db: Session,
    project_id: int,
    parent_id: int | None,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    stmt = select(models.WikiFolder.id).where(
        models.WikiFolder.project_id == project_id,
        models.WikiFolder.name == name,
    )
    if parent_id is None:
        stmt = stmt.where(models.WikiFolder.parent_id.is_(None))
    else:
        stmt = stmt.where(models.WikiFolder.parent_id == parent_id)
    if exclude_id is not None:
        stmt = stmt.where(models.WikiFolder.id != exclude_id)
    hit = db.scalar(stmt)
    if hit is not None:
        raise ValueError("folder name already exists in this location")


def wiki_folders_list_all(db: Session, project_id: int) -> list[models.WikiFolder]:
    return list(
        db.scalars(
            select(models.WikiFolder)
            .where(models.WikiFolder.project_id == project_id)
            .order_by(models.WikiFolder.sort_order, models.WikiFolder.name)
        ).all()
    )


def wiki_folders_build_tree(rows: list[models.WikiFolder]) -> list[dict]:
    by_parent: dict[int | None, list[models.WikiFolder]] = {}
    for f in rows:
        by_parent.setdefault(f.parent_id, []).append(f)
    for lst in by_parent.values():
        lst.sort(key=lambda x: (x.sort_order, x.name.lower()))

    def walk(pid: int | None) -> list[dict]:
        out: list[dict] = []
        for f in by_parent.get(pid, []):
            out.append(
                {
                    "id": f.id,
                    "parent_id": f.parent_id,
                    "name": f.name,
                    "sort_order": f.sort_order,
                    "children": walk(f.id),
                }
            )
        return out

    return walk(None)


def wiki_folder_create(db: Session, project_id: int, body: WikiFolderCreate) -> models.WikiFolder:
    name = (body.name or "").strip()
    if not name:
        raise ValueError("folder name required")
    par = body.parent_id
    if par is not None:
        if wiki_folder_for_project(db, project_id, int(par)) is None:
            raise ValueError("parent folder not found")
    _wiki_folder_name_unique(db, project_id, par, name)
    if par is None:
        q = select(func.coalesce(func.max(models.WikiFolder.sort_order), -1)).where(
            models.WikiFolder.project_id == project_id,
            models.WikiFolder.parent_id.is_(None),
        )
    else:
        q = select(func.coalesce(func.max(models.WikiFolder.sort_order), -1)).where(
            models.WikiFolder.project_id == project_id,
            models.WikiFolder.parent_id == par,
        )
    so = int(db.scalar(q) or -1) + 1
    fold = models.WikiFolder(project_id=project_id, parent_id=par, name=name, sort_order=so)
    db.add(fold)
    db.flush()
    return fold


def wiki_folder_patch(db: Session, fold: models.WikiFolder, body: WikiFolderPatch) -> models.WikiFolder:
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        nn = data["name"].strip()
        if not nn:
            raise ValueError("folder name required")
        _wiki_folder_name_unique(db, fold.project_id, fold.parent_id, nn, exclude_id=fold.id)
        fold.name = nn
    db.add(fold)
    db.flush()
    return fold


def wiki_folder_delete(db: Session, fold: models.WikiFolder) -> None:
    db.delete(fold)
    db.flush()


def wiki_doc_set_linked_stories(db: Session, doc: models.WikiDocument, story_ids: list[int]) -> None:
    """Thay toàn bộ liên kết story cho doc; mỗi story phải thuộc cùng project."""
    for sid in story_ids:
        _wiki_story_must_be_in_project(db, doc.project_id, sid)
    db.execute(delete(models.WikiDocumentStory).where(models.WikiDocumentStory.wiki_document_id == doc.id))
    db.flush()
    # Core delete() xóa DB nhưng instance WikiDocumentStory vẫn nằm trong doc.story_links (trạng thái deleted).
    # expire để không còn tham chiếu tới object đã xóa trước khi db.add(doc) ở wiki_doc_patch.
    db.expire(doc, ["story_links"])
    for sid in story_ids:
        db.add(models.WikiDocumentStory(wiki_document_id=doc.id, story_id=sid))
    db.flush()


def wiki_doc_recompute_embedding(doc: models.WikiDocument) -> list[float]:
    blob = f"{doc.title}\n\n{doc.content}"
    return wiki_embedding.embed_text(blob)


def wiki_doc_create(db: Session, project_id: int, body: WikiDocCreate, author_member_id: int) -> models.WikiDocument:
    link_ids = _wiki_story_ids_from_create(body)
    doc_folder_id: int | None = None
    if body.folder_id is not None:
        if wiki_folder_for_project(db, project_id, int(body.folder_id)) is None:
            raise ValueError("folder not found")
        doc_folder_id = int(body.folder_id)
    slug_in = (body.slug or "").strip()
    if slug_in:
        slug = wiki_slugify(slug_in)
        hit = db.scalar(
            select(models.WikiDocument.id).where(
                models.WikiDocument.project_id == project_id,
                models.WikiDocument.slug == slug,
            )
        )
        if hit is not None:
            raise ValueError("slug already exists in this project")
    else:
        slug = wiki_unique_slug(db, project_id, body.title)
    tags = [str(x).strip() for x in (body.tags or []) if str(x).strip()]
    doc = models.WikiDocument(
        id=str(uuid.uuid4()),
        project_id=project_id,
        folder_id=doc_folder_id,
        slug=slug,
        title=body.title.strip(),
        content=body.content or "",
        tags_json=tags if tags else None,
        author_member_id=author_member_id,
        is_draft=bool(body.is_draft),
        embedding_json=None,
    )
    doc.embedding_json = wiki_doc_recompute_embedding(doc)
    db.add(doc)
    db.flush()
    if link_ids:
        wiki_doc_set_linked_stories(db, doc, link_ids)
    db.refresh(doc)
    return doc


def wiki_doc_get(db: Session, doc_id: str) -> models.WikiDocument | None:
    return db.scalar(
        select(models.WikiDocument)
        .options(selectinload(models.WikiDocument.story_links))
        .where(models.WikiDocument.id == doc_id)
    )


def wiki_doc_get_by_slug(db: Session, project_id: int, slug: str) -> models.WikiDocument | None:
    s = wiki_slugify(slug)
    return db.scalar(
        select(models.WikiDocument)
        .options(selectinload(models.WikiDocument.story_links))
        .where(
            models.WikiDocument.project_id == project_id,
            models.WikiDocument.slug == s,
        )
    )


def wiki_doc_patch(db: Session, doc: models.WikiDocument, body: WikiDocPatch) -> models.WikiDocument:
    data = body.model_dump(exclude_unset=True)
    if "title" in data and data["title"] is not None:
        doc.title = data["title"].strip()
    if "content" in data and data["content"] is not None:
        doc.content = data["content"]
    if "story_ids" in data:
        raw = data["story_ids"]
        ids = [int(x) for x in (raw or []) if x is not None and int(x) > 0]
        ids = sorted(set(ids))
        wiki_doc_set_linked_stories(db, doc, ids)
    elif "story_id" in data:
        sid = data["story_id"]
        wiki_doc_set_linked_stories(db, doc, [] if sid is None else [int(sid)])
    if "folder_id" in data:
        fd = data["folder_id"]
        if fd is not None:
            if wiki_folder_for_project(db, doc.project_id, int(fd)) is None:
                raise ValueError("folder not found")
            doc.folder_id = int(fd)
        else:
            doc.folder_id = None
    if "is_draft" in data and data["is_draft"] is not None:
        doc.is_draft = bool(data["is_draft"])
    if "tags" in data and data["tags"] is not None:
        tags = [str(x).strip() for x in data["tags"] if str(x).strip()]
        doc.tags_json = tags if tags else None
    if "slug" in data and data["slug"] is not None:
        ns = wiki_slugify(data["slug"])
        if not ns:
            raise ValueError("invalid slug")
        hit = db.scalar(
            select(models.WikiDocument.id).where(
                models.WikiDocument.project_id == doc.project_id,
                models.WikiDocument.slug == ns,
                models.WikiDocument.id != doc.id,
            )
        )
        if hit is not None:
            raise ValueError("slug already exists in this project")
        doc.slug = ns
    emb_refresh = "title" in data or "content" in data
    if emb_refresh:
        doc.embedding_json = wiki_doc_recompute_embedding(doc)
    db.add(doc)
    db.flush()
    db.refresh(doc)
    return doc


def wiki_doc_delete(db: Session, doc: models.WikiDocument) -> None:
    db.delete(doc)
    db.flush()


def wiki_documents_list(
    db: Session,
    project_id: int,
    *,
    story_id: int | None = None,
    folder_id: int | None = None,
    unfiled_only: bool = False,
    q: str | None = None,
    tag: str | None = None,
    limit: int = 100,
) -> list[models.WikiDocument]:
    limit = min(max(limit, 1), 500)
    stmt = (
        select(models.WikiDocument)
        .options(selectinload(models.WikiDocument.story_links))
        .where(models.WikiDocument.project_id == project_id)
    )
    if unfiled_only:
        stmt = stmt.where(models.WikiDocument.folder_id.is_(None))
    elif folder_id is not None:
        stmt = stmt.where(models.WikiDocument.folder_id == folder_id)
    if story_id is not None:
        wds = models.WikiDocumentStory
        stmt = (
            stmt.join(wds, wds.wiki_document_id == models.WikiDocument.id)
            .where(wds.story_id == story_id)
            .distinct()
        )
    if (q or "").strip():
        qq = f"%{(q or '').strip()}%"
        stmt = stmt.where(or_(models.WikiDocument.title.like(qq), models.WikiDocument.content.like(qq)))
    stmt = stmt.order_by(models.WikiDocument.updated_at.desc()).limit(limit)
    rows = list(db.scalars(stmt).all())
    if (tag or "").strip() and rows:
        tl = (tag or "").strip().lower()
        rows = [
            r
            for r in rows
            if r.tags_json
            and isinstance(r.tags_json, list)
            and any(str(x).strip().lower() == tl for x in r.tags_json)
        ]
    return rows


def wiki_docs_semantic_search(
    db: Session,
    project_id: int,
    query: str,
    *,
    story_id: int | None = None,
    top_k: int = 10,
) -> list[tuple[float, models.WikiDocument]]:
    top_k = min(max(top_k, 1), 50)
    qv = wiki_embedding.embed_text(query)
    stmt = select(models.WikiDocument).where(models.WikiDocument.project_id == project_id)
    if story_id is not None:
        wds = models.WikiDocumentStory
        stmt = (
            stmt.join(wds, wds.wiki_document_id == models.WikiDocument.id)
            .where(wds.story_id == story_id)
            .distinct()
        )
    stmt = stmt.options(selectinload(models.WikiDocument.story_links))
    rows = list(db.scalars(stmt).all())
    scored: list[tuple[float, models.WikiDocument]] = []
    for r in rows:
        ej = r.embedding_json
        if not ej or not isinstance(ej, list):
            continue
        try:
            vec = [float(x) for x in ej]
        except (TypeError, ValueError):
            continue
        if len(vec) != len(qv):
            continue
        sc = wiki_embedding.cosine_similarity(qv, vec)
        scored.append((sc, r))
    scored.sort(key=lambda x: -x[0])
    return scored[:top_k]


def wiki_context_for_story(db: Session, project_id: int, story_id: int, *, limit: int = 16) -> list[dict]:
    """Ngữ cảnh tài liệu cho story: doc gắn story trước, bổ sung semantic trong cùng project."""
    st = story_get(db, story_id)
    if st is None or st.project_id != project_id:
        raise ValueError("invalid story")
    p = project_get(db, project_id)
    pslug = p.slug if p else ""
    limit = min(max(limit, 1), 80)
    attached = wiki_documents_list(db, project_id, story_id=story_id, limit=80)
    blob = f"{st.title}\n\n{(st.description or '')[:6000]}"
    sem = wiki_docs_semantic_search(db, project_id, blob, story_id=None, top_k=limit + len(attached))
    seen: set[str] = set()
    out: list[dict] = []
    for d in attached:
        seen.add(d.id)
        out.append(
            {
                **wiki_doc_to_out(db, d, project_slug=pslug, semantic_score=None),
                "context_role": "attached_to_story",
            }
        )
    for sc, d in sem:
        if d.id in seen:
            continue
        seen.add(d.id)
        out.append(
            {
                **wiki_doc_to_out(db, d, project_slug=pslug, semantic_score=sc),
                "context_role": "semantic",
            }
        )
        if len(out) >= limit:
            break
    return out[:limit]


def wiki_doc_to_out(
    db: Session,
    doc: models.WikiDocument,
    *,
    project_slug: str,
    semantic_score: float | None = None,
) -> dict:
    tags: list[str] = []
    if doc.tags_json and isinstance(doc.tags_json, list):
        tags = [str(x) for x in doc.tags_json if x is not None]
    link_ids = [ls.story_id for ls in (doc.story_links or [])]
    link_ids.sort()
    story_keys: list[str] = []
    for sid in link_ids:
        st = story_get(db, sid)
        if st:
            story_keys.append(f"{project_slug}-{st.story_number}")
    sk0 = story_keys[0] if story_keys else None
    emb_len = len(doc.embedding_json) if isinstance(doc.embedding_json, list) else None
    return {
        "id": doc.id,
        "project_id": doc.project_id,
        "folder_id": doc.folder_id,
        "story_id": link_ids[0] if link_ids else None,
        "story_ids": link_ids,
        "story_keys": story_keys,
        "slug": doc.slug,
        "title": doc.title,
        "content": doc.content,
        "tags": tags,
        "author_member_id": doc.author_member_id,
        "is_draft": bool(doc.is_draft),
        "created_at": doc.created_at,
        "updated_at": doc.updated_at,
        "story_key": sk0,
        "semantic_score": semantic_score,
        "embedding_dims": emb_len,
    }


def _wiki_comment_strip_opt(s: str | None) -> str | None:
    if s is None:
        return None
    t = s.strip()
    return t if t else None


def _wiki_comment_thread_root_id(db: Session, start_id: str) -> str | None:
    cid = (start_id or "").strip()
    if not cid:
        return None
    seen: set[str] = set()
    while cid:
        if cid in seen:
            return None
        seen.add(cid)
        r = db.get(models.WikiComment, cid)
        if r is None:
            return None
        if r.parent_id is None:
            return r.id
        cid = r.parent_id


def _wiki_comment_quote_excerpt_snap(text: str, max_len: int = 480) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) > max_len:
        return t[: max_len - 1] + "…"
    return t


def _quoted_selection_in_comment(fragment: str, full: str) -> bool:
    """True if fragment appears as a contiguous span in full (whitespace-normalized)."""

    def norm(s: str) -> str:
        return " ".join((s or "").split())

    f, g = norm(fragment), norm(full)
    return bool(f) and f in g


def wiki_comment_to_dict(db: Session, row: models.WikiComment) -> dict:
    m = member_get(db, row.author_member_id)
    name = (m.display_name or "").strip() if m else ""
    return {
        "id": row.id,
        "doc_id": row.doc_id,
        "parent_id": row.parent_id,
        "quoted_comment_id": row.quoted_comment_id,
        "quoted_excerpt": row.quoted_excerpt,
        "quoted_author_display_name": row.quoted_author_display_name,
        "author_member_id": row.author_member_id,
        "author_display_name": name,
        "content": row.content,
        "quote": row.quote,
        "prefix": row.prefix,
        "suffix": row.suffix,
        "text_offset_start": row.text_offset_start,
        "text_offset_end": row.text_offset_end,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def wiki_comments_list_for_doc(db: Session, doc_id: str, *, include_resolved: bool = False) -> list[models.WikiComment]:
    """Danh sách comment; ẩn cả subtree khi **root thread** có status resolved (unless include_resolved)."""
    stmt = (
        select(models.WikiComment)
        .where(models.WikiComment.doc_id == doc_id)
        .order_by(models.WikiComment.created_at.asc())
    )
    all_rows: list[models.WikiComment] = list(db.scalars(stmt).all())
    if include_resolved:
        return all_rows
    by_id = {r.id: r for r in all_rows}
    root_resolved: set[str] = set()
    for r in all_rows:
        if r.parent_id is None and str(r.status) == "resolved":
            root_resolved.add(r.id)

    def thread_root(r: models.WikiComment) -> models.WikiComment | None:
        cur: models.WikiComment | None = r
        seen: set[str] = set()
        while cur is not None and cur.parent_id:
            if cur.id in seen:
                return None
            seen.add(cur.id)
            cur = by_id.get(cur.parent_id)
        return cur

    out: list[models.WikiComment] = []
    for r in all_rows:
        root = thread_root(r)
        if root is None:
            continue
        if root.id in root_resolved:
            continue
        out.append(r)
    return out


def wiki_comments_visible_count(db: Session, doc_id: str) -> int:
    """Count messages visible with default sidebar filter (resolved root threads hidden)."""
    return len(wiki_comments_list_for_doc(db, doc_id, include_resolved=False))


def wiki_comment_root_thread_counts(db: Session, doc_id: str) -> tuple[int, int]:
    """Count feedback threads (root comments only): open vs resolved."""
    wc = models.WikiComment
    stmt = select(wc.status).where(wc.doc_id == doc_id, wc.parent_id.is_(None))
    statuses = list(db.scalars(stmt).all())
    resolved_n = sum(1 for s in statuses if str(s) == "resolved")
    open_n = len(statuses) - resolved_n
    return open_n, resolved_n


def wiki_comment_create(
    db: Session, doc: models.WikiDocument, body: WikiCommentCreate, author_member_id: int
) -> models.WikiComment:
    parent_key: str | None = None
    if body.parent_id:
        par = db.get(models.WikiComment, (body.parent_id or "").strip())
        if par is None or par.doc_id != doc.id:
            raise ValueError("invalid parent comment")
        parent_key = par.id
    content = (body.content or "").strip()
    if not content:
        raise ValueError("content required")
    _validate_comment_mentions_in_project(db, doc.project_id, content)
    qc: str | None
    px: str | None
    sx: str | None
    ost: int | None
    oen: int | None
    if parent_key:
        qc, px, sx, ost, oen = None, None, None, None, None
    else:
        qc = _wiki_comment_strip_opt(body.quote)
        px = _wiki_comment_strip_opt(body.prefix)
        sx = _wiki_comment_strip_opt(body.suffix)
        ost, oen = body.text_offset_start, body.text_offset_end

    q_snap_id: str | None = None
    q_excerpt: str | None = None
    q_author_snap: str | None = None
    raw_qcid = _wiki_comment_strip_opt(body.quoted_comment_id)
    if raw_qcid:
        if not parent_key:
            raise ValueError("quoted_comment_id is only allowed on thread replies")
        qrow = db.get(models.WikiComment, raw_qcid)
        if qrow is None or qrow.doc_id != doc.id:
            raise ValueError("invalid quoted comment")
        thr = _wiki_comment_thread_root_id(db, parent_key)
        qthr = _wiki_comment_thread_root_id(db, raw_qcid)
        if thr is None or qthr is None or thr != qthr:
            raise ValueError("quoted comment must be in the same feedback thread")
        qm = member_get(db, qrow.author_member_id)
        q_author_snap = ((qm.display_name or "").strip() if qm else "") or f"Member {qrow.author_member_id}"
        raw_sel = _wiki_comment_strip_opt(body.quoted_text)
        if raw_sel:
            if not _quoted_selection_in_comment(raw_sel, qrow.content or ""):
                raise ValueError("quoted text must be selected from that comment")
            q_excerpt = _wiki_comment_quote_excerpt_snap(raw_sel)
        else:
            q_excerpt = _wiki_comment_quote_excerpt_snap(qrow.content or "")
        q_snap_id = raw_qcid

    row = models.WikiComment(
        id=str(uuid.uuid4()),
        doc_id=doc.id,
        parent_id=parent_key,
        quoted_comment_id=q_snap_id,
        quoted_excerpt=q_excerpt,
        quoted_author_display_name=q_author_snap,
        author_member_id=author_member_id,
        content=content,
        quote=qc,
        prefix=px,
        suffix=sx,
        text_offset_start=ost,
        text_offset_end=oen,
        status="open",
    )
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def wiki_comment_patch(
    db: Session, row: models.WikiComment, body: WikiCommentPatch
) -> models.WikiComment:
    data = body.model_dump(exclude_unset=True)
    if "content" in data and data["content"] is not None:
        c = str(data["content"]).strip()
        if not c:
            raise ValueError("content required")
        did = getattr(row, "doc_id", None)
        doc = wiki_doc_get(db, did) if did else None
        if doc is None:
            raise ValueError("document not found for comment")
        _validate_comment_mentions_in_project(db, doc.project_id, c)
        row.content = c
    if "status" in data and data["status"] is not None:
        row.status = str(data["status"])
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def wiki_comment_delete(db: Session, row: models.WikiComment, *, editor_member_id: int) -> None:
    if row.author_member_id != editor_member_id:
        raise PermissionError("Only the author can delete this comment")
    db.delete(row)
    db.flush()


def wiki_comments_open_summaries_for_docs(
    db: Session,
    doc_ids: list[str],
    *,
    limit_per_doc: int = 12,
) -> dict[str, list[dict]]:
    """Gợn mở rộng MCP: vài comment đang open theo tài liệu (theo doc_id)."""
    if not doc_ids:
        return {}
    limit_per_doc = min(max(limit_per_doc, 1), 50)
    uniq = list(dict.fromkeys([x for x in doc_ids if (x or "").strip()]))
    if not uniq:
        return {}
    out: dict[str, list[dict]] = {did: [] for did in uniq}
    wc = models.WikiComment
    rows = list(
        db.scalars(
            select(wc)
            .where(wc.doc_id.in_(uniq), wc.status == "open", wc.parent_id.is_(None))
            .order_by(wc.doc_id.asc(), wc.created_at.desc())
        ).all()
    )
    for r in rows:
        if len(out[r.doc_id]) >= limit_per_doc:
            continue
        q = (r.quote or "").strip()
        out[r.doc_id].append(
            {
                "id": r.id,
                "content_excerpt": (r.content or "").strip()[:400],
                "quote_excerpt": (q[:280] + "…") if len(q) > 280 else q,
            }
        )
    return out
