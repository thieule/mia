from __future__ import annotations

from collections.abc import Generator
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .. import models
from ..db import get_session
from ..security import decode_token

_bearer = HTTPBearer(auto_error=False)


def get_db() -> Generator[Session, None, None]:
    yield from get_session()


def get_current_user(
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Session = Depends(get_db),
) -> models.User:
    if cred is None or (cred.scheme or "").lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(cred.credentials)
        uid = int(payload["sub"])
    except Exception as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    u = db.get(models.User, uid)
    if u is None:
        raise HTTPException(status_code=401, detail="Account no longer exists", headers={"WWW-Authenticate": "Bearer"})
    return u
