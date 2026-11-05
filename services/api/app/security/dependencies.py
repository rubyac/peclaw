import hashlib
import hmac
from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_engine
from app.models.identity import AuthSession, Membership, Project, ProjectMember, User, now
from app.services.audit import audit

COOKIE_NAME = "peclaw_session"


def get_db(request: Request):
    with Session(get_engine(), expire_on_commit=False) as db:
        db.info["request_id"] = request.state.request_id
        yield db


Db = Annotated[Session, Depends(get_db)]


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token: str) -> str:
    return digest("peclaw-csrf:" + token)


def require_origin(request: Request) -> None:
    if request.headers.get("origin") not in get_settings().auth_allowed_origins:
        raise HTTPException(403, detail={"code": "INVALID_ORIGIN", "message": "请求来源不受信任"})


def deny(
    db: Session,
    user: User,
    action: str,
    resource_id: UUID | None = None,
    organization_id: UUID | None = None,
    status: int = 404,
) -> None:
    audit(db, user.id, organization_id, action, resource_id, result="denied")
    db.commit()
    raise HTTPException(status)


def current_user(request: Request, db: Db) -> User:
    token = request.cookies.get(COOKIE_NAME, "")
    if not 32 <= len(token) <= 128:
        raise HTTPException(401)
    session = db.get(AuthSession, digest(token))
    if not session or session.revoked_at or session.expires_at <= now():
        raise HTTPException(401)
    user = db.get(User, session.user_id)
    if not user or not user.is_active:
        raise HTTPException(401)
    request.state.actor_id = user.id
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request)
        provided = request.headers.get("x-csrf-token", "")
        if (
            len(provided) != 64
            or not provided.isascii()
            or not hmac.compare_digest(provided, csrf_token(token))
        ):
            deny(db, user, "csrf.reject", status=403)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def organization_access(
    db: Session, user: User, organization_id: UUID, manage: bool = False
) -> Membership:
    member = db.get(Membership, (organization_id, user.id))
    if not member or not member.is_active:
        deny(db, user, "organization.access", organization_id)
    if manage and member.role not in {"owner", "admin"}:
        deny(db, user, "organization.manage", organization_id, organization_id, 403)
    return member


def project_access(
    db: Session,
    user: User,
    organization_id: UUID,
    project_id: UUID,
    permission: Literal["read", "write", "manage_members"] = "read",
) -> Project:
    member = organization_access(db, user, organization_id)
    project = db.scalar(
        select(Project).where(Project.id == project_id, Project.organization_id == organization_id)
    )
    if not project:
        deny(db, user, "project.access", project_id, organization_id)
    project_member = db.get(ProjectMember, (project_id, user.id))
    if permission == "manage_members" and member.role in {"owner", "admin"}:
        return project
    if not project_member:
        deny(db, user, "project.access", project_id, organization_id)
    if permission == "write" and (
        member.role == "viewer" or project_member.role not in {"manager", "editor"}
    ):
        deny(db, user, "project.write", project_id, organization_id, 403)
    if permission == "manage_members" and (
        member.role == "viewer" or project_member.role != "manager"
    ):
        deny(db, user, "project.members", project_id, organization_id, 403)
    return project
