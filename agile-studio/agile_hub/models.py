from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
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
    story_assignments: Mapped[list["StoryAssignee"]] = relationship(back_populates="member", passive_deletes=True)


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
    stories: Mapped[list["Story"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    releases: Mapped[list["Release"]] = relationship(back_populates="project", cascade="all, delete-orphan")


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
