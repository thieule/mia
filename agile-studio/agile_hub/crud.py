from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
import re
import secrets

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from . import models
from .schemas import (
    CommentCreate,
    CommentUpdate,
    MemberCreate,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectPatch,
    ProjectSettingsWrite,
    WorkflowTemplateCreate,
    StoryCreate,
    StoryPatch,
    ReleaseCreate,
    ReleasePatch,
)

_COMMENT_MENTION_RE = re.compile(r"@([A-Za-z0-9._-]+)")


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
    link = models.ProjectMember(project_id=project_id, member_id=body.member_id, role=body.role.strip() or "member")
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
    s: models.Story, project_slug: str, db: Session, assignee_ids: list[int] | None = None
) -> dict:
    aids = assignee_ids if assignee_ids is not None else story_assignee_ids_get(db, s.id)
    if not aids and s.assignee_id is not None:
        aids = [s.assignee_id]
    aid0 = aids[0] if aids else None
    return {
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
    }
