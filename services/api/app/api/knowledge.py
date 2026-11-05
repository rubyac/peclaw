from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import delete, select, update

from app.knowledge.access import (
    acl_manager,
    document_access,
    project_writer,
    readable_predicate,
)
from app.knowledge.retrieval import citation, search_private
from app.knowledge.service import document_output, receive_upload, validate_grantee
from app.knowledge.workflow import read_original
from app.models.identity import Membership, ProjectMember, User, now
from app.models.knowledge import DocumentChunk, DocumentGrant, DocumentVersion, PrivateDocument
from app.schemas.knowledge import (
    CitationOutput,
    DocumentDetail,
    DocumentInput,
    DocumentOutput,
    KnowledgeQuery,
    KnowledgeResults,
    PermissionInput,
    RevisionInput,
    VersionInput,
)
from app.security.dependencies import CurrentUser, Db, organization_access, project_access
from app.services.audit import audit

router = APIRouter(prefix="/api/v1/organizations/{organization_id}", tags=["private knowledge"])


def version_for(db: Db, doc: PrivateDocument, number: int | None = None) -> DocumentVersion:
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc.id,
            DocumentVersion.organization_id == doc.organization_id,
            DocumentVersion.project_id == doc.project_id,
            DocumentVersion.number == (number or doc.current_version),
        )
    )
    if not version:
        raise HTTPException(404)
    return version


@router.get("/projects/{project_id}/documents", response_model=list[DocumentOutput])
def documents(
    organization_id: UUID,
    project_id: UUID,
    user: CurrentUser,
    db: Db,
    include_deleted: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=100),
):
    project_access(db, user, organization_id, project_id)
    if include_deleted:
        project_access(db, user, organization_id, project_id, "write")
    query = select(PrivateDocument).where(
        PrivateDocument.organization_id == organization_id, PrivateDocument.project_id == project_id
    )
    if not include_deleted:
        query = query.where(PrivateDocument.is_deleted.is_(False))
    if not acl_manager(db, user, organization_id, project_id):
        query = query.where(readable_predicate(user.id))
    return [
        document_output(db, user, doc)
        for doc in db.scalars(
            query.order_by(PrivateDocument.updated_at.desc(), PrivateDocument.id)
            .offset(offset)
            .limit(limit)
        )
    ]


@router.post("/projects/{project_id}/documents", status_code=202, response_model=DocumentDetail)
def upload_document(
    organization_id: UUID, project_id: UUID, payload: DocumentInput, user: CurrentUser, db: Db
):
    project_access(db, user, organization_id, project_id, "write")
    doc = receive_upload(db, user, organization_id, project_id, payload)
    return document_output(db, user, doc, True)


@router.get("/projects/{project_id}/knowledge-members")
def eligible_members(organization_id: UUID, project_id: UUID, user: CurrentUser, db: Db):
    project_access(db, user, organization_id, project_id, "write")
    rows = db.execute(
        select(User, ProjectMember)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .join(
            Membership,
            (Membership.user_id == User.id) & (Membership.organization_id == organization_id),
        )
        .where(
            ProjectMember.project_id == project_id,
            Membership.is_active.is_(True),
            User.is_active.is_(True),
        )
    ).all()
    return [
        {
            "user_id": u.id,
            "full_name": u.full_name,
            "email": u.email,
            "can_edit": project_writer(db, u, organization_id, project_id),
        }
        for u, _ in rows
    ]


@router.get("/projects/{project_id}/documents/{document_id}", response_model=DocumentDetail)
def get_document(
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    user: CurrentUser,
    db: Db,
    include_deleted: bool = False,
):
    doc = document_access(
        db,
        user,
        organization_id,
        project_id,
        document_id,
        permission="manage" if include_deleted else "read",
        allow_deleted=include_deleted,
    )
    return document_output(db, user, doc, True)


@router.post(
    "/projects/{project_id}/documents/{document_id}/versions",
    status_code=202,
    response_model=DocumentDetail,
)
def upload_version(
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    payload: VersionInput,
    user: CurrentUser,
    db: Db,
):
    document_access(db, user, organization_id, project_id, document_id, permission="write")
    doc = receive_upload(db, user, organization_id, project_id, payload, document_id)
    return document_output(db, user, doc, True)


@router.get("/projects/{project_id}/documents/{document_id}/download")
def download(
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    user: CurrentUser,
    db: Db,
    version: int | None = Query(None, ge=1),
):
    doc = document_access(db, user, organization_id, project_id, document_id)
    item = version_for(db, doc, version)
    if item.status in {"uploading", "deleting", "deleted"}:
        raise HTTPException(409)
    try:
        raw = read_original(item)
    except Exception:
        raise HTTPException(
            503, detail={"code": "DOCUMENT_UNAVAILABLE", "message": "原始文件暂时不可用"}
        ) from None
    audit(
        db, user.id, organization_id, "document.download", doc.id, details={"version": item.number}
    )
    db.commit()
    return Response(
        raw,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename*=UTF-8''" + quote(item.filename, safe=""),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/projects/{project_id}/documents/{document_id}/chunks", response_model=list[CitationOutput]
)
def chunks(
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    user: CurrentUser,
    db: Db,
    version: int | None = Query(None, ge=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    doc = document_access(db, user, organization_id, project_id, document_id)
    item = version_for(db, doc, version)
    if item.status != "indexed":
        raise HTTPException(
            409, detail={"code": "DOCUMENT_NOT_INDEXED", "message": "该版本尚未完成索引"}
        )
    rows = db.scalars(
        select(DocumentChunk)
        .where(
            DocumentChunk.version_id == item.id,
            DocumentChunk.organization_id == organization_id,
            DocumentChunk.project_id == project_id,
        )
        .order_by(DocumentChunk.chunk_index)
        .offset(offset)
        .limit(limit)
    ).all()
    audit(
        db, user.id, organization_id, "document.preview", doc.id, details={"version": item.number}
    )
    db.commit()
    return [citation(row, item, doc) for row in rows]


@router.post("/knowledge/search", response_model=KnowledgeResults)
def query(organization_id: UUID, payload: KnowledgeQuery, user: CurrentUser, db: Db):
    organization_access(db, user, organization_id)
    if payload.project_id:
        project_access(db, user, organization_id, payload.project_id)
    return search_private(db, user, organization_id, payload)


@router.get("/projects/{project_id}/documents/{document_id}/permissions")
def get_permissions(
    organization_id: UUID, project_id: UUID, document_id: UUID, user: CurrentUser, db: Db
):
    doc = document_access(db, user, organization_id, project_id, document_id, permission="manage")
    return {
        "revision": doc.revision,
        "access_scope": doc.access_scope,
        "grants": [
            {"user_id": g.user_id, "role": g.role}
            for g in db.scalars(select(DocumentGrant).where(DocumentGrant.document_id == doc.id))
        ],
    }


@router.put("/projects/{project_id}/documents/{document_id}/permissions")
def set_permissions(
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    payload: PermissionInput,
    user: CurrentUser,
    db: Db,
):
    doc = document_access(
        db, user, organization_id, project_id, document_id, permission="manage", lock=True
    )
    if doc.revision != payload.expected_revision:
        raise HTTPException(409)
    if len({g.user_id for g in payload.grants}) != len(payload.grants):
        raise HTTPException(422)
    editors = []
    for grant in payload.grants:
        target = validate_grantee(db, organization_id, project_id, grant.user_id)
        if grant.role == "editor" and project_writer(db, target, organization_id, project_id):
            editors.append(target.id)
    if payload.access_scope == "restricted" and not editors:
        raise HTTPException(
            409,
            detail={"code": "LAST_DOCUMENT_EDITOR", "message": "受限文档必须保留一名有效编辑者"},
        )
    db.execute(delete(DocumentGrant).where(DocumentGrant.document_id == doc.id))
    for grant in payload.grants if payload.access_scope == "restricted" else []:
        db.add(
            DocumentGrant(
                document_id=doc.id,
                organization_id=organization_id,
                project_id=project_id,
                user_id=grant.user_id,
                role=grant.role,
            )
        )
    previous = doc.access_scope
    doc.access_scope, doc.revision, doc.updated_at = payload.access_scope, doc.revision + 1, now()
    audit(
        db,
        user.id,
        organization_id,
        "document.permissions",
        doc.id,
        details={
            "before": previous,
            "after": doc.access_scope,
            "grants": [{"user_id": str(g.user_id), "role": g.role} for g in payload.grants],
        },
    )
    db.commit()
    return {"revision": doc.revision}


@router.delete("/projects/{project_id}/documents/{document_id}", status_code=202)
def delete_document(
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    payload: RevisionInput,
    user: CurrentUser,
    db: Db,
):
    doc = document_access(
        db, user, organization_id, project_id, document_id, permission="write", lock=True
    )
    if doc.revision != payload.expected_revision:
        raise HTTPException(409)
    doc.is_deleted, doc.revision, doc.updated_at = True, doc.revision + 1, now()
    db.execute(
        delete(DocumentChunk).where(
            DocumentChunk.document_id == doc.id, DocumentChunk.organization_id == organization_id
        )
    )
    db.execute(
        update(DocumentVersion)
        .where(DocumentVersion.document_id == doc.id)
        .values(
            status="deleting", claim_token=None, lease_until=None, delete_attempts=0, chunk_count=0
        )
    )
    audit(db, user.id, organization_id, "document.delete", doc.id)
    db.commit()
    return {"id": doc.id, "status": "deleting", "revision": doc.revision}


@router.post("/projects/{project_id}/documents/{document_id}/retry", status_code=202)
def retry(
    organization_id: UUID,
    project_id: UUID,
    document_id: UUID,
    payload: RevisionInput,
    user: CurrentUser,
    db: Db,
):
    doc = document_access(
        db,
        user,
        organization_id,
        project_id,
        document_id,
        permission="manage",
        allow_deleted=True,
        lock=True,
    )
    if doc.revision != payload.expected_revision:
        raise HTTPException(409)
    if doc.is_deleted:
        db.execute(
            update(DocumentVersion)
            .where(DocumentVersion.document_id == doc.id, DocumentVersion.status == "deleting")
            .values(delete_attempts=0, lease_until=None)
        )
    else:
        if not project_writer(db, user, organization_id, project_id):
            raise HTTPException(403)
        document_access(db, user, organization_id, project_id, document_id, permission="write")
        item = version_for(db, doc)
        if item.status != "failed" or item.attempts >= 3:
            raise HTTPException(409)
        item.status, item.error_code, item.lease_until, item.claim_token = (
            "uploaded",
            None,
            None,
            None,
        )
        item.requested_by = user.id
    audit(db, user.id, organization_id, "document.retry", doc.id)
    db.commit()
    return {"id": doc.id, "status": "deleting" if doc.is_deleted else "uploaded"}
