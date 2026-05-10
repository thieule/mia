from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from typing import Dict, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

MemberType = Literal["human", "ai"]
StoryStatus = Literal[
    "icebox_in_progress",
    "icebox_approved",
    "icebox_rejected",
    "icebox_feedback",
    "backlog_unstart",
    "current_unstart",
    "current_started",
    "current_review",
    "current_delivery",
    "done",
]
ReleaseStatus = Literal["planning", "active", "released", "archived"]
ProjectStatus = Literal["active", "archived"]

TaskTicketStatus = Literal["open", "in_progress", "blocked", "done"]
TaskTicketPriority = Literal["low", "medium", "high", "urgent"]
TaskTicketType = Literal["task", "bug", "feature", "chore", "technical_debt", "docs", "support", "other"]

_LEGACY_STORY_STATUS_MAP: dict[str, str] = {
    "icebox": "icebox_in_progress",
    "backlog": "backlog_unstart",
    "ready": "current_unstart",
    "in_progress": "current_started",
    "review": "current_review",
    "cancelled": "icebox_rejected",
}


def _normalize_story_status(v: object) -> object:
    if not isinstance(v, str):
        return v
    s = v.strip()
    if not s:
        return s
    return _LEGACY_STORY_STATUS_MAP.get(s, s)


class MemberCreate(BaseModel):
    member_type: MemberType
    display_name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = Field(None, max_length=320)
    agent_id: Optional[str] = Field(None, max_length=128)
    meta_json: Optional[Dict] = None


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_type: str
    display_name: str
    email: Optional[str]
    agent_id: Optional[str]
    meta_json: Optional[Dict]
    created_at: datetime
    updated_at: datetime


class ProjectCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: ProjectStatus = "active"
    workspace_ref: Optional[str] = Field(None, max_length=512)

    @field_validator("slug")
    @classmethod
    def slug_ok(cls, v: str) -> str:
        s = v.strip().lower()
        if not _SLUG_RE.match(s):
            raise ValueError("slug: lowercase letters/digits, must start with letter or digit, max 64 chars")
        return s


class ProjectSettingsPublic(BaseModel):
    """Trả về API — không lộ PAT / URL / secret AI webhook, chỉ báo đã cấu hình hay chưa."""

    github_repository: Optional[str] = None
    github_default_branch: Optional[str] = None
    github_token_configured: bool = False
    slack_channel: Optional[str] = None
    slack_webhook_configured: bool = False
    discord_channel_label: Optional[str] = None
    discord_webhook_configured: bool = False
    ai_working_queue_configured: bool = False
    ai_working_queue_agent_id: Optional[str] = None
    workflow_template_id: Optional[int] = None
    storage_overview: Optional[str] = None
    documents_storage_path: Optional[str] = None
    notes: Optional[str] = None
    agile_event_notifications_enabled: bool = True
    """Bật fan-out sự kiện tới API Center (mỗi agent tự lọc). Tắt: false trong settings_json."""


class ProjectSettingsWrite(BaseModel):
    """PATCH: trường None = giữ nguyên; token / URL / secret \"\" = xóa giá trị đã lưu."""

    github_repository: Optional[str] = Field(None, max_length=200)
    github_default_branch: Optional[str] = Field(None, max_length=128)
    github_token: Optional[str] = Field(None, max_length=4000)
    slack_channel: Optional[str] = Field(None, max_length=200)
    slack_webhook_url: Optional[str] = Field(None, max_length=2048)
    discord_channel_label: Optional[str] = Field(None, max_length=200)
    discord_webhook_url: Optional[str] = Field(None, max_length=2048)
    ai_working_queue_url: Optional[str] = Field(None, max_length=2048)
    ai_working_queue_secret: Optional[str] = Field(None, max_length=4000)
    ai_working_queue_agent_id: Optional[str] = Field(None, max_length=128)
    workflow_template_id: Optional[int] = None
    storage_overview: Optional[str] = Field(None, max_length=20000)
    documents_storage_path: Optional[str] = Field(None, max_length=1024)
    notes: Optional[str] = Field(None, max_length=4000)
    agile_event_notifications_enabled: Optional[bool] = None
    """None = giữ; True/False = cập nhật fan-out sự kiện tới API Center."""


class ProjectPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ProjectStatus] = None
    workspace_ref: Optional[str] = Field(None, max_length=512)
    settings: Optional[ProjectSettingsWrite] = None


class ProjectOut(BaseModel):
    """Luôn dựng qua ``project_to_out`` — không map trực tiếp từ ORM (có ``settings_json``)."""

    id: int
    slug: str
    name: str
    description: Optional[str]
    status: str
    workspace_ref: Optional[str]
    settings: ProjectSettingsPublic
    created_at: datetime
    updated_at: datetime


def project_settings_public(raw: Optional[Dict]) -> ProjectSettingsPublic:
    if not raw or not isinstance(raw, dict):
        return ProjectSettingsPublic()

    def s(key: str) -> Optional[str]:
        v = raw.get(key)
        if v is None:
            return None
        t = str(v).strip()
        return t or None

    def i(key: str) -> Optional[int]:
        v = raw.get(key)
        if v is None:
            return None
        try:
            iv = int(v)
        except Exception:
            return None
        return iv if iv > 0 else None

    url_ok = bool(s("ai_working_queue_url"))
    sec_ok = bool(s("ai_working_queue_secret"))
    aid = s("ai_working_queue_agent_id")
    nfan = raw.get("agile_event_notifications_enabled")
    if nfan is None:
        fanout_en = True
    else:
        fanout_en = bool(nfan)
    return ProjectSettingsPublic(
        github_repository=s("github_repository"),
        github_default_branch=s("github_default_branch"),
        github_token_configured=bool(s("github_token")),
        slack_channel=s("slack_channel"),
        slack_webhook_configured=bool(s("slack_webhook_url")),
        discord_channel_label=s("discord_channel_label"),
        discord_webhook_configured=bool(s("discord_webhook_url")),
        ai_working_queue_configured=bool(url_ok and sec_ok and aid),
        ai_working_queue_agent_id=aid,
        workflow_template_id=i("workflow_template_id"),
        storage_overview=s("storage_overview"),
        documents_storage_path=s("documents_storage_path"),
        notes=s("notes"),
        agile_event_notifications_enabled=fanout_en,
    )


def project_to_out(p: "models.Project") -> ProjectOut:
    from . import models

    if not isinstance(p, models.Project):
        raise TypeError("expected Project ORM")
    return ProjectOut(
        id=p.id,
        slug=p.slug,
        name=p.name,
        description=p.description,
        status=p.status,
        workspace_ref=p.workspace_ref,
        settings=project_settings_public(getattr(p, "settings_json", None)),
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


class ProjectMemberAdd(BaseModel):
    member_id: int
    role: str = Field("member", max_length=64)


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    member_id: int
    role: str
    joined_at: datetime
    member: Optional[MemberOut] = None


class WorkflowTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class WorkflowTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime


class WorkspaceRoleCreate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    sort_order: int = 0


class WorkspaceRolePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    sort_order: Optional[int] = None


class WorkspaceRoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    description: Optional[str]
    sort_order: int
    is_system: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _mysql_zero_datetime(cls, v: object) -> object:
        """MySQL có thể trả về '0000-00-00 …' khi INSERT không gán cột datetime — tránh lỗi Pydantic."""
        if isinstance(v, datetime) and v.year < 1900:
            return datetime(1970, 1, 1, 0, 0, 0)
        if isinstance(v, str) and v.strip().startswith("0000-00-00"):
            return datetime(1970, 1, 1, 0, 0, 0)
        return v


class ApiCenterConnectIn(BaseModel):
    endpoint: str = Field(..., min_length=1, max_length=2048)
    secret: str = Field(..., min_length=1, max_length=1024)


class ApiCenterStatusOut(BaseModel):
    endpoint: Optional[str] = None
    connected: bool = False
    has_mcp_api_key: bool = False
    mcp_api_key_masked: Optional[str] = None
    endpoints: Dict = Field(default_factory=dict)
    chat_ws_url: Optional[str] = None


class ApiCenterAllowMcpIn(BaseModel):
    """``mcp_url`` có thể là base Hub (vd. http://host:9120) hoặc endpoint MCP (vd. http://host:9121/mcp). Tuỳ chọn tách riêng."""
    mcp_url: str = Field(..., min_length=1, max_length=2048)
    hub_reply_base_url: Optional[str] = Field(None, max_length=2048)
    mcp_tools_url: Optional[str] = Field(None, max_length=2048)
    mcp_server_id: str = Field("agile-studio", min_length=1, max_length=128)
    metadata: Optional[Dict] = None


class ApiCenterAgentOut(BaseModel):
    id: str
    name: Optional[str] = None
    role: Optional[str] = None
    description: Optional[str] = None
    workspace: Optional[str] = None
    supported_item_kinds: list[str] = Field(default_factory=list)


class ApiCenterChatDispatchIn(BaseModel):
    trace_id: Optional[str] = Field(None, max_length=128)
    project_id: str = Field(..., min_length=1, max_length=128)
    project_context: Optional[Dict] = None
    channel_id: str = Field(..., min_length=1, max_length=160)
    channel_type: str = Field(..., min_length=1, max_length=64)
    sender: Dict
    message: str = Field(..., min_length=1, max_length=4000)
    mentions: list[str] = Field(default_factory=list)
    target_agent_id: Optional[str] = Field(None, max_length=128)
    story_context: Optional[Dict] = None
    conversation_history: list[Dict] = Field(default_factory=list)
    callback_api_url: Optional[str] = Field(None, max_length=2048)


class ApiCenterAgileNotificationIn(BaseModel):
    trace_id: Optional[str] = Field(None, max_length=128)
    event_type: str = Field(..., min_length=1, max_length=128)
    project_id: str = Field(..., min_length=1, max_length=128)
    project_name: Optional[str] = Field(None, max_length=255)
    summary: Optional[str] = Field(None, max_length=2000)
    changed_fields: list[str] = Field(default_factory=list)
    target_agent_id: Optional[str] = Field(None, max_length=128)
    agent_id: Optional[str] = Field(None, max_length=128)
    agent_ids: list[str] = Field(default_factory=list)
    item_kind: Optional[str] = Field("notification", max_length=64)
    source_role: Optional[str] = Field(None, max_length=128)
    service: Optional[str] = Field("agile-studio", max_length=128)
    routing: Optional[Dict] = None
    data: Dict = Field(default_factory=dict)


class ReleaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: ReleaseStatus = "planning"
    """Planning window: ``starts_at`` and optional ``ends_at`` (inclusive). If only ``starts_at`` is set, the day is treated as a single-day window."""
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    released_at: Optional[datetime] = None


class ReleasePatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ReleaseStatus] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    released_at: Optional[datetime] = None


class ReleaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    description: Optional[str]
    status: str
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    released_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class StoryCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    description: Optional[str] = None
    status: StoryStatus = "icebox_in_progress"
    priority: Optional[str] = Field(None, max_length=24)
    story_points: Optional[Decimal] = None
    release_id: Optional[int] = None
    release_label: Optional[str] = Field(None, max_length=64)
    assignee_id: Optional[int] = None
    """Legacy single assignee. Ignored if ``assignee_ids`` is set."""
    assignee_ids: Optional[list[int]] = None
    """Zero or more project members to assign. If both ``assignee_id`` and ``assignee_ids`` are sent, ``assignee_ids`` wins."""
    reporter_id: Optional[int] = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: object) -> object:
        return _normalize_story_status(v)


class StoryPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    description: Optional[str] = None
    status: Optional[StoryStatus] = None
    priority: Optional[str] = Field(None, max_length=24)
    story_points: Optional[Decimal] = None
    release_id: Optional[int] = None
    release_label: Optional[str] = Field(None, max_length=64)
    assignee_id: Optional[int] = None
    assignee_ids: Optional[list[int]] = None
    reporter_id: Optional[int] = None

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, v: object) -> object:
        return _normalize_story_status(v)


class StoryTaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    body: Optional[str] = None
    done: bool = False
    task_status: Optional[TaskTicketStatus] = None
    """If omitted, derived from ``done`` (done → done, else open)."""
    ticket_priority: TaskTicketPriority = "medium"
    ticket_type: TaskTicketType = "task"
    due_at: Optional[datetime] = None
    acceptance_criteria: Optional[str] = None
    sort_order: Optional[int] = None
    assignee_ids: list[int] = Field(default_factory=list)
    reporter_id: Optional[int] = None
    story_ids: list[int] = Field(default_factory=list)
    """Stories in the same project to link (optional). Omit or empty = project-only ticket."""


class StoryTaskPatch(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    body: Optional[str] = None
    done: Optional[bool] = None
    task_status: Optional[TaskTicketStatus] = None
    ticket_priority: Optional[TaskTicketPriority] = None
    ticket_type: Optional[TaskTicketType] = None
    due_at: Optional[datetime] = None
    acceptance_criteria: Optional[str] = None
    sort_order: Optional[int] = None
    assignee_ids: Optional[list[int]] = None
    reporter_id: Optional[int] = None
    story_ids: Optional[list[int]] = None
    """Replace all story links when set (including empty list for no stories)."""


class StoryTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    story_ids: list[int] = Field(default_factory=list)
    story_id: Optional[int] = None
    """First linked story (compat with older clients)."""
    title: str
    body: Optional[str] = None
    done: bool
    task_status: str = "open"
    ticket_priority: str = "medium"
    ticket_type: str = "task"
    due_at: Optional[datetime] = None
    acceptance_criteria: Optional[str] = None
    sort_order: int
    assignee_ids: list[int] = Field(default_factory=list)
    assignee_id: Optional[int] = None
    """First assignee (same convention as ``StoryOut``)."""
    reporter_id: Optional[int] = None
    watcher_member_ids: list[int] = Field(default_factory=list)
    story_keys: list[str] = Field(default_factory=list)
    story_titles: list[str] = Field(default_factory=list)
    story_key: Optional[str] = None
    """First linked story key (project-wide listing convenience)."""
    story_title: Optional[str] = None
    """First linked story title."""
    created_at: datetime
    updated_at: datetime


class StoryTaskListPage(BaseModel):
    """Paginated ``GET /projects/{id}/tasks`` response."""

    items: list[StoryTaskOut]
    total: int
    limit: int
    offset: int


class StoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    story_key: str = ""
    story_number: int
    title: str
    description: Optional[str]
    status: str
    priority: Optional[str]
    story_points: Optional[Decimal]
    release_id: Optional[int]
    release_label: Optional[str] = None
    assignee_id: Optional[int] = None
    """First assignee (for backward compatibility; same as first of ``assignee_ids``)."""
    assignee_ids: list[int] = Field(default_factory=list)
    reporter_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    tasks: list[StoryTaskOut] = Field(default_factory=list)


class CommentCreate(BaseModel):
    """Request JSON: only ``body``. Author is always the authenticated user (``member_id`` from JWT)."""

    model_config = ConfigDict(extra="ignore")

    body: str = Field(..., min_length=1)


class CommentUpdate(BaseModel):
    """PATCH comment: chỉ tác giả được sửa."""

    model_config = ConfigDict(extra="ignore")

    body: str = Field(..., min_length=1)


class CommentAuthorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    email: Optional[str] = None
    member_type: str = "human"


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    story_id: int
    author_member_id: int
    body: str
    created_at: datetime
    updated_at: datetime
    author: Optional[CommentAuthorOut] = None


class TaskCommentOut(BaseModel):
    """Comment on a project ticket (`story_tasks`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    story_task_id: int
    author_member_id: int
    body: str
    created_at: datetime
    updated_at: datetime
    author: Optional[CommentAuthorOut] = None


class StoryStatusActorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    email: Optional[str] = None
    member_type: str = "human"


class StoryStatusEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    story_id: int
    actor_member_id: int
    from_status: str
    to_status: str
    created_at: datetime
    actor: Optional[StoryStatusActorOut] = None


# --- Wiki / Docs ---
class WikiFolderCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1, max_length=255)
    parent_id: Optional[int] = None


class WikiFolderPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = Field(None, min_length=1, max_length=255)


class WikiFolderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    parent_id: Optional[int] = None
    name: str
    sort_order: int
    created_at: datetime
    updated_at: datetime


class WikiFolderTreeNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    parent_id: Optional[int] = None
    name: str
    sort_order: int = 0
    children: list["WikiFolderTreeNode"] = Field(default_factory=list)


class WikiFolderTreeResponse(BaseModel):
    tree: list[WikiFolderTreeNode]


WikiFolderTreeNode.model_rebuild()


class WikiDocCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(..., min_length=1, max_length=500)
    content: str = ""
    slug: Optional[str] = Field(None, max_length=128)
    folder_id: Optional[int] = None
    """Thư mục wiki (``wiki_folders``); ``None`` = ngoài thư mục."""
    story_id: Optional[int] = None
    """Một story (tương thích cũ); gộp vào ``story_ids``."""
    story_ids: list[int] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    is_draft: bool = True


class WikiDocPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: Optional[str] = Field(None, max_length=500)
    content: Optional[str] = None
    slug: Optional[str] = Field(None, max_length=128)
    folder_id: Optional[int] = None
    """Đặt thư mục; gửi ``null`` JSON để đưa doc ra gốc (unfiled)."""
    story_id: Optional[int] = None
    """Một story; chỉ áp khi không gửi ``story_ids``."""
    story_ids: Optional[list[int]] = None
    """Thay toàn bộ liên kết story; danh sách rỗng = gỡ hết."""
    tags: Optional[list[str]] = None
    is_draft: Optional[bool] = None


class WikiDocOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: int
    folder_id: Optional[int] = None
    story_id: Optional[int] = None
    """Story đầu tiên trong ``story_ids`` (tương thích client cũ)."""
    story_ids: list[int] = Field(default_factory=list)
    story_keys: list[str] = Field(default_factory=list)
    """Mỗi story: ``project_slug-story_number``."""
    slug: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    author_member_id: int
    is_draft: bool
    created_at: datetime
    updated_at: datetime
    story_key: Optional[str] = None
    """Giống phần tử đầu của ``story_keys`` (tương thích)."""
    semantic_score: Optional[float] = None
    """Chỉ khi response từ search."""
    embedding_dims: Optional[int] = None
    """Số chiều vector (không trả raw vector)."""
    context_role: Optional[str] = None
    """attached_to_story | semantic (chỉ endpoint context)."""


class WikiDocSearchOut(BaseModel):
    """Kết quả tìm kiếm (text + semantic)."""

    query: Optional[str] = None
    semantic_query: Optional[str] = None
    results: list[WikiDocOut]


class WikiCommentCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str = Field(..., min_length=1)
    parent_id: Optional[str] = None
    quoted_comment_id: Optional[str] = Field(None, max_length=36)
    quoted_text: Optional[str] = Field(None, max_length=12000)
    quote: Optional[str] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    text_offset_start: Optional[int] = None
    text_offset_end: Optional[int] = None


class WikiCommentPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: Optional[str] = Field(None, min_length=1)
    status: Optional[str] = Field(None, pattern="^(open|resolved)$")


class WikiCommentCountOut(BaseModel):
    """Message count for sidebar badge; plus root-thread tallies for this document."""

    visible_count: int
    open_thread_count: int = 0
    resolved_thread_count: int = 0


class WikiCommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doc_id: str
    parent_id: Optional[str] = None
    quoted_comment_id: Optional[str] = None
    quoted_excerpt: Optional[str] = None
    quoted_author_display_name: Optional[str] = None
    author_member_id: int
    author_display_name: str = ""
    content: str
    quote: Optional[str] = None
    prefix: Optional[str] = None
    suffix: Optional[str] = None
    text_offset_start: Optional[int] = None
    text_offset_end: Optional[int] = None
    status: str
    created_at: datetime
    updated_at: datetime


# --- Project invites (email) ---
class ProjectInviteCreate(BaseModel):
    email: EmailStr
    role: str = Field("member", max_length=64)


class ProjectInvitePendingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    created_at: datetime
    expires_at: datetime


class ProjectInvitePreviewOut(BaseModel):
    valid: bool
    reason: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    project_slug: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[datetime] = None


class MyProjectInviteOut(BaseModel):
    token: str
    project_id: int
    project_name: str
    project_slug: str
    role: str
    expires_at: datetime


# --- Auth (users + JWT) ---
class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=255)
    invite_token: Optional[str] = Field(None, max_length=96)


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    member_id: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
