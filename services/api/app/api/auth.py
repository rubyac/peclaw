import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, update

from app.core.config import get_settings
from app.models.identity import AuthSession, Membership, Organization, User, now
from app.schemas.identity import LoginInput, PasswordInput
from app.security.dependencies import (
    COOKIE_NAME,
    CurrentUser,
    Db,
    csrf_token,
    digest,
    require_origin,
)
from app.security.passwords import DUMMY_HASH, hash_password, hasher, verify_password
from app.security.rate_limit import check_login_rate
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


@router.post("/login", dependencies=[Depends(require_origin), Depends(check_login_rate)])
def login(payload: LoginInput, request: Request, response: Response, db: Db):
    user = db.scalar(select(User).where(User.email == payload.email))
    valid = verify_password(user.password_hash if user else DUMMY_HASH, payload.password)
    if not user or not valid or not user.is_active:
        audit(
            db,
            user.id if user else None,
            None,
            "auth.login",
            result="denied",
            request_id=request.state.request_id,
        )
        db.commit()
        raise HTTPException(401)
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
    old_token = request.cookies.get(COOKIE_NAME, "")
    if old_token:
        old_session = db.get(AuthSession, digest(old_token))
        if old_session:
            old_session.revoked_at = now()
    token = secrets.token_urlsafe(32)
    settings = get_settings()
    db.add(
        AuthSession(
            token_digest=digest(token),
            user_id=user.id,
            expires_at=now() + timedelta(seconds=settings.auth_session_seconds),
        )
    )
    audit(db, user.id, None, "auth.login", request_id=request.state.request_id)
    db.commit()
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="strict",
        max_age=settings.auth_session_seconds,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
        "can_curate_public_data": user.is_data_curator,
        "csrf_token": csrf_token(token),
    }


@router.get("/me")
def me(request: Request, response: Response, user: CurrentUser, db: Db):
    memberships = db.execute(
        select(Membership, Organization)
        .join(Organization, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id, Membership.is_active.is_(True))
        .order_by(Organization.created_at)
    ).all()
    response.headers["Cache-Control"] = "no-store"
    return {
        "user": {"id": user.id, "email": user.email, "full_name": user.full_name},
        "organizations": [
            {"id": org.id, "name": org.name, "role": member.role} for member, org in memberships
        ],
        "can_curate_public_data": user.is_data_curator,
        "csrf_token": csrf_token(request.cookies[COOKIE_NAME]),
    }


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, user: CurrentUser, db: Db):
    session = db.get(AuthSession, digest(request.cookies[COOKIE_NAME]))
    session.revoked_at = now()
    audit(db, user.id, None, "auth.logout", request_id=request.state.request_id)
    db.commit()
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=get_settings().auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )


@router.post("/password", status_code=204)
def change_password(
    payload: PasswordInput, request: Request, response: Response, user: CurrentUser, db: Db
):
    if not verify_password(user.password_hash, payload.current_password):
        audit(db, user.id, None, "auth.password", result="denied")
        db.commit()
        raise HTTPException(403)
    user.password_hash = hash_password(payload.new_password)
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id).values(revoked_at=now()))
    audit(db, user.id, None, "auth.password", request_id=request.state.request_id)
    db.commit()
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=get_settings().auth_cookie_secure,
        httponly=True,
        samesite="strict",
    )
