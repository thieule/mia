from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import crud, models
from ..schemas import MemberCreate, TokenResponse, UserLogin, UserPublic, UserRegister
from ..security import create_access_token, hash_password, verify_password
from .deps import get_current_user, get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _user_public(u: models.User) -> UserPublic:
    return UserPublic(id=u.id, email=u.email, display_name=u.display_name, member_id=u.member_id)


@router.post("/register", response_model=TokenResponse)
def auth_register(body: UserRegister, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(body.email).strip().lower()
    if crud.user_get_by_email(db, email):
        raise HTTPException(409, "Email is already registered")
    try:
        m = crud.member_create(
            db,
            MemberCreate(
                member_type="human",
                display_name=body.display_name.strip(),
                email=email,
                agent_id=None,
                meta_json=None,
            ),
        )
        db.flush()
        ph = hash_password(body.password)
        u = crud.user_create(
            db,
            email=email,
            password_hash=ph,
            display_name=body.display_name.strip(),
            member_id=m.id,
        )
    except IntegrityError:
        raise HTTPException(409, "Could not create account (duplicate data)") from None
    token = create_access_token(user_id=u.id, email=u.email)
    return TokenResponse(access_token=token, user=_user_public(u))


@router.post("/login", response_model=TokenResponse)
def auth_login(body: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(body.email).strip().lower()
    u = crud.user_get_by_email(db, email)
    if u is None or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Invalid email or password")
    token = create_access_token(user_id=u.id, email=u.email)
    return TokenResponse(access_token=token, user=_user_public(u))


@router.get("/me", response_model=UserPublic)
def auth_me(current: models.User = Depends(get_current_user)) -> UserPublic:
    return _user_public(current)
