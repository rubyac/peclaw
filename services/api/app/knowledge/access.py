from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models.identity import Membership, ProjectMember, User
from app.models.knowledge import DocumentGrant, PrivateDocument
from app.security.dependencies import deny, project_access


def project_writer(db: Session, user: User, org_id: UUID, project_id: UUID) -> bool:
    member = db.get(Membership, (org_id, user.id))
    project_member = db.get(ProjectMember, (project_id, user.id))
    return bool(
        member
        and member.is_active
        and member.role != "viewer"
        and project_member
        and project_member.role in {"manager", "editor"}
    )


def acl_manager(db: Session, user: User, org_id: UUID, project_id: UUID) -> bool:
    member = db.get(ProjectMember, (project_id, user.id))
    return bool(project_writer(db, user, org_id, project_id) and member.role == "manager")


def can_read(db: Session, user: User, doc: PrivateDocument) -> bool:
    if doc.access_scope == "project":
        return True  # Callers must have already checked active project membership.
    return db.get(DocumentGrant, (doc.id, user.id)) is not None


def can_write(db: Session, user: User, doc: PrivateDocument) -> bool:
    if not project_writer(db, user, doc.organization_id, doc.project_id):
        return False
    grant = db.get(DocumentGrant, (doc.id, user.id))
    return doc.access_scope == "project" or bool(grant and grant.role == "editor")


def can_manage(db: Session, user: User, doc: PrivateDocument) -> bool:
    return can_write(db, user, doc) or acl_manager(db, user, doc.organization_id, doc.project_id)


def document_access(
    db: Session,
    user: User,
    org_id: UUID,
    project_id: UUID,
    document_id: UUID,
    *,
    permission: str = "read",
    allow_deleted: bool = False,
    lock: bool = False,
) -> PrivateDocument:
    project_access(db, user, org_id, project_id)
    query = select(PrivateDocument).where(
        PrivateDocument.id == document_id,
        PrivateDocument.organization_id == org_id,
        PrivateDocument.project_id == project_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    doc = db.scalar(query)
    if not doc or (doc.is_deleted and not allow_deleted):
        deny(db, user, "document.access", document_id, org_id)
    allowed = (
        can_manage(db, user, doc)
        if permission == "manage"
        else (can_write(db, user, doc) if permission == "write" else can_read(db, user, doc))
    )
    if not allowed:
        deny(db, user, "document." + permission, document_id, org_id)
    return doc


def readable_predicate(user_id: UUID):
    return or_(
        PrivateDocument.access_scope == "project",
        select(DocumentGrant.user_id)
        .where(DocumentGrant.document_id == PrivateDocument.id, DocumentGrant.user_id == user_id)
        .exists(),
    )


def authorized_projects(user: User, org_id: UUID):
    return (
        select(ProjectMember.project_id)
        .join(
            Membership,
            and_(
                Membership.organization_id == ProjectMember.organization_id,
                Membership.user_id == ProjectMember.user_id,
            ),
        )
        .where(
            ProjectMember.organization_id == org_id,
            ProjectMember.user_id == user.id,
            Membership.is_active.is_(True),
        )
    )
