from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select

from app.models.identity import AuditLog, Membership, Organization, User
from app.schemas.identity import MemberInput, MemberUpdate
from app.security.dependencies import CurrentUser, Db, deny, organization_access
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])


def member_output(member: Membership, user: User) -> dict:
    return {
        "user_id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": member.role,
        "is_active": member.is_active,
        "user_is_active": user.is_active,
    }


@router.get("/{organization_id}/members")
def members(organization_id: UUID, user: CurrentUser, db: Db):
    organization_access(db, user, organization_id, manage=True)
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == organization_id)
        .order_by(User.email)
    ).all()
    return [member_output(m, u) for m, u in rows]


def manage_role(
    db: Db, user: User, org_id: UUID, target: Membership | None, new_role: str, active: bool
) -> None:
    # Re-read identities after the organization lock to serialize role invariants.
    db.scalar(select(Organization).where(Organization.id == org_id).with_for_update())
    db.expire_all()
    actor = organization_access(db, user, org_id, manage=True)
    if actor.role != "owner" and (new_role == "owner" or (target and target.role == "owner")):
        deny(db, user, "membership.role", org_id, org_id, 403)
    if (
        target
        and target.role == "owner"
        and target.is_active
        and (new_role != "owner" or not active)
    ):
        count = db.scalar(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == org_id,
                Membership.role == "owner",
                Membership.is_active.is_(True),
            )
        )
        if count <= 1:
            raise HTTPException(
                409, detail={"code": "LAST_OWNER", "message": "必须保留一名机构所有者"}
            )


@router.post("/{organization_id}/members", status_code=201)
def add_member(
    organization_id: UUID, payload: MemberInput, request: Request, user: CurrentUser, db: Db
):
    manage_role(db, user, organization_id, None, payload.role, True)
    target = db.scalar(
        select(User).where(User.email == str(payload.email).lower(), User.is_active.is_(True))
    )
    if not target:
        raise HTTPException(404)
    if db.get(Membership, (organization_id, target.id)):
        raise HTTPException(409)
    member = Membership(organization_id=organization_id, user_id=target.id, role=payload.role)
    db.add(member)
    audit(
        db,
        user.id,
        organization_id,
        "membership.add",
        target.id,
        request_id=request.state.request_id,
        details={"role": payload.role},
    )
    db.commit()
    return member_output(member, target)


@router.patch("/{organization_id}/members/{user_id}")
def update_member(
    organization_id: UUID,
    user_id: UUID,
    payload: MemberUpdate,
    request: Request,
    user: CurrentUser,
    db: Db,
):
    organization_access(db, user, organization_id, manage=True)
    # Lock before reading target to prevent stale role checks.
    db.scalar(select(Organization).where(Organization.id == organization_id).with_for_update())
    member = db.get(Membership, (organization_id, user_id))
    if not member:
        raise HTTPException(404)
    manage_role(db, user, organization_id, member, payload.role, payload.is_active)
    previous = {"role": member.role, "is_active": member.is_active}
    member.role, member.is_active = payload.role, payload.is_active
    audit(
        db,
        user.id,
        organization_id,
        "membership.update",
        user_id,
        request_id=request.state.request_id,
        details={"before": previous, "after": payload.model_dump()},
    )
    db.commit()
    return member_output(member, db.get(User, user_id))


@router.get("/{organization_id}/audit")
def audit_logs(
    organization_id: UUID,
    user: CurrentUser,
    db: Db,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    organization_access(db, user, organization_id, manage=True)
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id == organization_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "action": row.action,
            "resource_id": row.resource_id,
            "result": row.result,
            "created_at": row.created_at,
            "request_id": row.request_id,
            "details": row.details,
        }
        for row in logs
    ]
