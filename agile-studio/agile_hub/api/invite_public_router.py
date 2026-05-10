"""Public invite preview (no JWT)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import crud
from ..schemas import ProjectInvitePreviewOut
from .deps import get_db

router = APIRouter(tags=["invites"])


@router.get("/invites/token/{token}", response_model=ProjectInvitePreviewOut)
def project_invite_preview(token: str, db: Session = Depends(get_db)) -> ProjectInvitePreviewOut:
    row = crud.project_invite_get_by_token(db, token)
    ok, reason = crud.project_invite_is_usable(row)
    if not ok or row is None:
        return ProjectInvitePreviewOut(valid=False, reason=reason)
    p = crud.project_get(db, row.project_id)
    return ProjectInvitePreviewOut(
        valid=True,
        project_id=row.project_id,
        project_name=p.name if p else "",
        project_slug=p.slug if p else "",
        email=row.email,
        expires_at=row.expires_at,
    )
