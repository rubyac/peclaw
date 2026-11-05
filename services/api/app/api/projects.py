from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.models.identity import Membership, Project, ProjectMember, User
from app.schemas.identity import ProjectInput, ProjectMemberInput, ProjectOutput
from app.security.dependencies import CurrentUser, Db, deny, organization_access, project_access
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/organizations/{organization_id}/projects", tags=["projects"])


def project_output(db: Db, user: User, project: Project) -> dict:
    org_member = db.get(Membership, (project.organization_id, user.id))
    member = db.get(ProjectMember, (project.id, user.id))
    data = ProjectOutput.model_validate(project).model_dump()
    data.update(
        my_role=member.role if member else None,
        can_write=bool(
            member and org_member.role != "viewer" and member.role in {"manager", "editor"}
        ),
        can_manage_members=bool(
            org_member.role in {"owner", "admin"}
            or (org_member.role != "viewer" and member and member.role == "manager")
        ),
    )
    return data


@router.get("", response_model=list[ProjectOutput])
def projects(organization_id: UUID, user: CurrentUser, db: Db):
    organization_access(db, user, organization_id)
    rows = db.scalars(
        select(Project)
        .join(ProjectMember, Project.id == ProjectMember.project_id)
        .where(Project.organization_id == organization_id, ProjectMember.user_id == user.id)
        .order_by(Project.created_at.desc())
    ).all()
    return [project_output(db, user, row) for row in rows]


@router.post("", response_model=ProjectOutput, status_code=201)
def create_project(
    organization_id: UUID, payload: ProjectInput, request: Request, user: CurrentUser, db: Db
):
    member = organization_access(db, user, organization_id)
    if member.role == "viewer":
        deny(db, user, "project.create", organization_id, organization_id, 403)
    project = Project(
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
        created_by=user.id,
    )
    db.add(project)
    db.flush()
    db.add(
        ProjectMember(
            project_id=project.id, organization_id=organization_id, user_id=user.id, role="manager"
        )
    )
    audit(
        db,
        user.id,
        organization_id,
        "project.create",
        project.id,
        request_id=request.state.request_id,
    )
    db.commit()
    return project_output(db, user, project)


@router.get("/{project_id}", response_model=ProjectOutput)
def project_detail(organization_id: UUID, project_id: UUID, user: CurrentUser, db: Db):
    project = project_access(db, user, organization_id, project_id)
    return project_output(db, user, project)


@router.patch("/{project_id}", response_model=ProjectOutput)
def update_project(
    organization_id: UUID,
    project_id: UUID,
    payload: ProjectInput,
    request: Request,
    user: CurrentUser,
    db: Db,
):
    project = project_access(db, user, organization_id, project_id, "write")
    project.name, project.description = payload.name, payload.description
    audit(
        db,
        user.id,
        organization_id,
        "project.update",
        project_id,
        request_id=request.state.request_id,
    )
    db.commit()
    return project_output(db, user, project)


@router.get("/{project_id}/members")
def project_members(organization_id: UUID, project_id: UUID, user: CurrentUser, db: Db):
    project_access(db, user, organization_id, project_id, "manage_members")
    rows = db.execute(
        select(ProjectMember, User)
        .join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
    ).all()
    return [
        {"user_id": u.id, "full_name": u.full_name, "email": u.email, "role": m.role}
        for m, u in rows
    ]


@router.put("/{project_id}/members")
def set_project_member(
    organization_id: UUID,
    project_id: UUID,
    payload: ProjectMemberInput,
    request: Request,
    user: CurrentUser,
    db: Db,
):
    project_access(db, user, organization_id, project_id, "manage_members")
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    db.expire_all()
    project_access(db, user, organization_id, project_id, "manage_members")
    target = db.get(Membership, (organization_id, payload.user_id))
    target_user = db.get(User, payload.user_id)
    if not target or not target.is_active or not target_user or not target_user.is_active:
        raise HTTPException(404)
    existing = db.get(ProjectMember, (project_id, payload.user_id))
    if existing and existing.role == "manager" and payload.role != "manager":
        ensure_other_manager(db, project_id)
    if existing:
        existing.role = payload.role
    else:
        db.add(
            ProjectMember(
                project_id=project_id,
                organization_id=organization_id,
                user_id=payload.user_id,
                role=payload.role,
            )
        )
    audit(
        db,
        user.id,
        organization_id,
        "project.member.set",
        project_id,
        request_id=request.state.request_id,
        details={"user_id": str(payload.user_id), "role": payload.role},
    )
    db.commit()
    return {"user_id": payload.user_id, "role": payload.role}


def ensure_other_manager(db: Db, project_id: UUID) -> None:
    count = db.scalar(
        select(func.count())
        .select_from(ProjectMember)
        .where(ProjectMember.project_id == project_id, ProjectMember.role == "manager")
    )
    if count <= 1:
        raise HTTPException(
            409, detail={"code": "LAST_MANAGER", "message": "必须保留一名项目管理员"}
        )


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_project_member(
    organization_id: UUID,
    project_id: UUID,
    user_id: UUID,
    request: Request,
    user: CurrentUser,
    db: Db,
):
    project_access(db, user, organization_id, project_id, "manage_members")
    db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    db.expire_all()
    project_access(db, user, organization_id, project_id, "manage_members")
    member = db.get(ProjectMember, (project_id, user_id))
    if not member:
        raise HTTPException(404)
    if member.role == "manager":
        ensure_other_manager(db, project_id)
    db.delete(member)
    audit(
        db,
        user.id,
        organization_id,
        "project.member.remove",
        project_id,
        request_id=request.state.request_id,
        details={"user_id": str(user_id)},
    )
    db.commit()
