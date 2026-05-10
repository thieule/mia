from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import INTEGER
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Khớp `schema/init_mysql.sql` (INT UNSIGNED). Trên MySQL, FK 3780 nếu cột tham chiếu unsigned mà cột gốc ký/unsigned lệch.
# Trên SQLite (dev) vẫn dùng Integer thông thường.
MUInt = Integer().with_variant(INTEGER(unsigned=True), "mysql", "mariadb")


def _utc_naive() -> datetime:
    return datetime.utcnow()


class Member(Base):
    __tablename__ = "members"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    member_type: Mapped[str] = mapped_column(String(16), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    agent_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    project_links: Mapped[list["ProjectMember"]] = relationship(back_populates="member")
    user: Mapped[Optional["User"]] = relationship(back_populates="member", uselist=False)
    comments_authored: Mapped[list["StoryComment"]] = relationship(back_populates="author")
    task_comments_authored: Mapped[list["StoryTaskComment"]] = relationship(back_populates="author")
    story_assignments: Mapped[list["StoryAssignee"]] = relationship(back_populates="member", passive_deletes=True)
    wiki_doc_comments_authored: Mapped[list["WikiComment"]] = relationship(back_populates="author")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    member: Mapped["Member"] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    workspace_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    settings_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    invites: Mapped[list["ProjectInvite"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    stories: Mapped[list["Story"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    releases: Mapped[list["Release"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    tasks: Mapped[list["StoryTask"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class WorkflowTemplate(Base):
    """Master data: mô tả quy trình làm việc dùng chung, không gắn project cụ thể."""

    __tablename__ = "workflow_templates"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )


class WorkspaceRole(Base):
    """Master data: vai trò trong dự án (slug khớp project_members.role và project_invites.role)."""

    __tablename__ = "workspace_roles"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )


class ApiCenterConnection(Base):
    """Singleton integration config for API Center (row id=1)."""

    __tablename__ = "api_center_connections"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=False, default=1)
    endpoint: Mapped[str] = mapped_column(String(2048), nullable=False)
    connect_secret: Mapped[str] = mapped_column(String(1024), nullable=False)
    session_key: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    mcp_api_key: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    api_endpoints_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planning")
    starts_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    ends_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    project: Mapped["Project"] = relationship(back_populates="releases")
    stories: Mapped[list["Story"]] = relationship(back_populates="release")


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="member")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)

    project: Mapped["Project"] = relationship(back_populates="members")
    member: Mapped["Member"] = relationship(back_populates="project_links")


class ProjectInvite(Base):
    """Email invitation to join a project; accepted via token + logged-in user email match."""

    __tablename__ = "project_invites"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token: Mapped[str] = mapped_column(String(96), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="member")
    invited_by_member_id: Mapped[Optional[int]] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="invites")


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (UniqueConstraint("project_id", "story_number", name="uq_stories_project_num"),)

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    story_number: Mapped[int] = mapped_column(MUInt, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="icebox_in_progress")
    priority: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    story_points: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2), nullable=True)
    release_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    """Optional free-form tag on the story (independent of ``release_id`` / milestones)."""
    release_id: Mapped[Optional[int]] = mapped_column(
        MUInt, ForeignKey("releases.id", ondelete="SET NULL"), nullable=True
    )
    assignee_id: Mapped[Optional[int]] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    reporter_id: Mapped[Optional[int]] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    project: Mapped["Project"] = relationship(back_populates="stories")
    release: Mapped[Optional["Release"]] = relationship(back_populates="stories")
    comments: Mapped[list["StoryComment"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="StoryComment.created_at",
    )
    status_events: Mapped[list["StoryStatusEvent"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="StoryStatusEvent.created_at.desc()",
    )
    assignments: Mapped[list["StoryAssignee"]] = relationship(
        back_populates="story", cascade="all, delete-orphan", passive_deletes=True, order_by="StoryAssignee.member_id"
    )
    task_story_links: Mapped[list["StoryTaskStory"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
    )


class StoryTask(Base):
    """Ticket / task in a project; optionally linked to one or many stories via ``story_task_stories``."""

    __tablename__ = "story_tasks"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task_status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")
    ticket_priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    ticket_type: Mapped[str] = mapped_column(String(24), nullable=False, default="task")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=False), nullable=True)
    acceptance_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(MUInt, nullable=False, default=0)
    reporter_id: Mapped[Optional[int]] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    project: Mapped["Project"] = relationship(back_populates="tasks")
    story_links: Mapped[list["StoryTaskStory"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StoryTaskStory.story_id",
    )
    assignments: Mapped[list["StoryTaskAssignee"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StoryTaskAssignee.member_id",
    )
    watchers: Mapped[list["StoryTaskWatcher"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StoryTaskWatcher.member_id",
    )
    comments: Mapped[list["StoryTaskComment"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StoryTaskComment.created_at",
    )


class StoryTaskStory(Base):
    """Many stories can link to the same project ticket; ticket may have zero links (orphan / project-only)."""

    __tablename__ = "story_task_stories"

    task_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("story_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    story_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )

    task: Mapped["StoryTask"] = relationship(back_populates="story_links")
    story: Mapped["Story"] = relationship(back_populates="task_story_links")


class StoryTaskWatcher(Base):
    __tablename__ = "story_task_watchers"

    task_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("story_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)

    task: Mapped["StoryTask"] = relationship(back_populates="watchers")


class StoryTaskComment(Base):
    __tablename__ = "story_task_comments"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    story_task_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("story_tasks.id", ondelete="CASCADE"), nullable=False
    )
    author_member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    task: Mapped["StoryTask"] = relationship(back_populates="comments")
    author: Mapped["Member"] = relationship(
        back_populates="task_comments_authored", foreign_keys=[author_member_id]
    )


class StoryTaskAssignee(Base):
    """Many assignees per story task (members of the same project)."""

    __tablename__ = "story_task_assignees"

    task_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("story_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )

    task: Mapped["StoryTask"] = relationship(back_populates="assignments")


class StoryAssignee(Base):
    """One story may have many assignees (all must be in the same project as the story)."""

    __tablename__ = "story_assignees"

    story_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True
    )
    member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="CASCADE"), primary_key=True
    )

    story: Mapped["Story"] = relationship(back_populates="assignments")
    member: Mapped["Member"] = relationship(back_populates="story_assignments")


class StoryComment(Base):
    __tablename__ = "story_comments"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(MUInt, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    author_member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    story: Mapped["Story"] = relationship(back_populates="comments")
    author: Mapped["Member"] = relationship(back_populates="comments_authored", foreign_keys=[author_member_id])


class StoryStatusEvent(Base):
    __tablename__ = "story_status_events"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(MUInt, ForeignKey("stories.id", ondelete="CASCADE"), nullable=False)
    actor_member_id: Mapped[int] = mapped_column(MUInt, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)

    story: Mapped["Story"] = relationship(back_populates="status_events")
    actor: Mapped["Member"] = relationship(foreign_keys=[actor_member_id])


class WikiFolder(Base):
    """Thư mục tài liệu wiki (cây, scoped theo project)."""

    __tablename__ = "wiki_folders"

    id: Mapped[int] = mapped_column(MUInt, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(MUInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(
        MUInt, ForeignKey("wiki_folders.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    project: Mapped["Project"] = relationship()


class WikiDocument(Base):
    """Tài liệu Markdown (wiki) scoped theo project; story qua bảng wiki_document_stories (n–n)."""

    __tablename__ = "wiki_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[int] = mapped_column(MUInt, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[Optional[int]] = mapped_column(
        MUInt, ForeignKey("wiki_folders.id", ondelete="SET NULL"), nullable=True
    )
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    author_member_id: Mapped[int] = mapped_column(
        MUInt, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False
    )
    is_draft: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    embedding_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    project: Mapped["Project"] = relationship()
    folder: Mapped[Optional["WikiFolder"]] = relationship()
    author: Mapped["Member"] = relationship()
    story_links: Mapped[list["WikiDocumentStory"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )
    wiki_comments: Mapped[list["WikiComment"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class WikiDocumentStory(Base):
    """Liên kết nhiều story ↔ một wiki doc (cùng project)."""

    __tablename__ = "wiki_document_stories"

    wiki_document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("wiki_documents.id", ondelete="CASCADE"), primary_key=True
    )
    story_id: Mapped[int] = mapped_column(MUInt, ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)

    document: Mapped["WikiDocument"] = relationship(back_populates="story_links")
    story: Mapped["Story"] = relationship()


class WikiComment(Base):
    """Bình luận / thảo luận trong nội dung wiki (neo theo trích đoạn Markdown)."""

    __tablename__ = "wiki_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("wiki_documents.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("wiki_comments.id", ondelete="CASCADE"), nullable=True
    )
    quoted_comment_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("wiki_comments.id", ondelete="SET NULL"), nullable=True
    )
    quoted_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quoted_author_display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    author_member_id: Mapped[int] = mapped_column(MUInt, ForeignKey("members.id", ondelete="RESTRICT"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    prefix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suffix: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text_offset_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text_offset_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), default=_utc_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), default=_utc_naive, onupdate=_utc_naive
    )

    document: Mapped["WikiDocument"] = relationship(back_populates="wiki_comments")
    author: Mapped["Member"] = relationship(back_populates="wiki_doc_comments_authored")
    parent: Mapped[Optional["WikiComment"]] = relationship(
        back_populates="replies",
        remote_side=[id],
        foreign_keys=lambda: [WikiComment.parent_id],
    )
    replies: Mapped[list["WikiComment"]] = relationship(
        back_populates="parent",
        foreign_keys=lambda: [WikiComment.parent_id],
    )
