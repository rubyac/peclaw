import base64
import hashlib
import json
from datetime import timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.knowledge.access import can_manage, can_read, can_write, document_access
from app.knowledge.parsing import ParseFailure, validate_file
from app.models.identity import Membership, ProjectMember, User, now
from app.models.knowledge import DocumentGrant, DocumentVersion, PrivateDocument
from app.schemas.knowledge import DocumentInput, FileInput, VersionInput
from app.services.audit import audit
from app.services.dependencies import storage_client

PROCESSING = {"validating", "parsing", "chunking", "embedding"}


def object_key(version: DocumentVersion) -> str:
    expected = (
        f"private/{version.organization_id}/{version.project_id}/{version.document_id}/{version.id}"
    )
    if version.object_key != expected:
        raise ParseFailure("INVALID_OBJECT_REFERENCE")
    return expected


def version_output(version: DocumentVersion) -> dict:
    return {
        key: getattr(version, key)
        for key in [
            "id",
            "number",
            "filename",
            "file_format",
            "byte_size",
            "content_hash",
            "status",
            "attempts",
            "error_code",
            "chunk_count",
            "created_at",
            "finished_at",
        ]
    }


def document_output(db: Session, user: User, doc: PrivateDocument, detailed: bool = False) -> dict:
    readable = can_read(db, user, doc)
    manageable = can_manage(db, user, doc)
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc.id, DocumentVersion.number == doc.current_version
        )
    )
    output = {
        key: getattr(doc, key)
        for key in [
            "id",
            "organization_id",
            "project_id",
            "current_version",
            "revision",
            "access_scope",
            "is_deleted",
            "created_at",
            "updated_at",
        ]
    }
    output.update(
        title=doc.title if readable else "受限文档",
        can_read=readable and not doc.is_deleted,
        can_write=can_write(db, user, doc) and not doc.is_deleted,
        can_manage=manageable,
        current=version_output(version) if version and readable else None,
    )
    if detailed:
        output["versions"] = (
            [
                version_output(v)
                for v in db.scalars(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == doc.id)
                    .order_by(DocumentVersion.number.desc())
                )
            ]
            if readable
            else []
        )
    return output


def validate_grantee(db: Session, org_id: UUID, project_id: UUID, user_id: UUID) -> User:
    user = db.get(User, user_id)
    member = db.get(Membership, (org_id, user_id))
    project_member = db.get(ProjectMember, (project_id, user_id))
    if not user or not user.is_active or not member or not member.is_active or not project_member:
        raise HTTPException(
            422,
            detail={"code": "INVALID_DOCUMENT_GRANTEE", "message": "仅可授权当前项目的有效成员"},
        )
    return user


def receive_upload(
    db: Session,
    user: User,
    org_id: UUID,
    project_id: UUID,
    payload: FileInput,
    document_id: UUID | None = None,
) -> PrivateDocument:
    raw = base64.b64decode(payload.content_base64, validate=True)
    if len(raw) > get_settings().knowledge_max_file_bytes:
        raise HTTPException(413)
    kind = payload.filename.rsplit(".", 1)[-1].lower()
    try:
        validate_file(raw, kind)
    except ParseFailure:
        raise HTTPException(
            422,
            detail={"code": "INVALID_DOCUMENT_FILE", "message": "文件类型、编码或安全校验未通过"},
        ) from None
    checksum = hashlib.sha256(raw).hexdigest()
    values = payload.model_dump(mode="json", exclude={"content_base64"})
    digest = hashlib.sha256(
        json.dumps(
            {
                "fields": values,
                "org": str(org_id),
                "project": str(project_id),
                "document": str(document_id),
                "hash": checksum,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    existing = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.uploaded_by == user.id,
            DocumentVersion.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if existing.input_digest != digest:
            raise HTTPException(409)
        doc = document_access(
            db, user, org_id, project_id, existing.document_id, permission="write"
        )
        if existing.status not in {"uploading", "failed"} or (
            existing.status == "failed"
            and existing.error_code not in {"UPLOAD_FAILED", "UPLOAD_INTERRUPTED"}
        ):
            return doc
        version = existing
        version.status, version.error_code = "uploading", None
        version.lease_until = now() + timedelta(seconds=120)
        db.commit()
    else:
        if document_id:
            doc = document_access(
                db, user, org_id, project_id, document_id, permission="write", lock=True
            )
            assert isinstance(payload, VersionInput)
            if doc.revision != payload.expected_revision:
                raise HTTPException(409)
            doc.current_version += 1
            doc.revision += 1
            doc.updated_at = now()
        else:
            assert isinstance(payload, DocumentInput)
            for reader_id in payload.reader_ids:
                validate_grantee(db, org_id, project_id, reader_id)
            doc = PrivateDocument(
                organization_id=org_id,
                project_id=project_id,
                title=payload.title,
                created_by=user.id,
                access_scope=payload.access_scope,
            )
            db.add(doc)
            db.flush()
            if payload.access_scope == "restricted":
                for reader_id in set([user.id, *payload.reader_ids]):
                    db.add(
                        DocumentGrant(
                            document_id=doc.id,
                            organization_id=org_id,
                            project_id=project_id,
                            user_id=reader_id,
                            role="editor" if reader_id == user.id else "reader",
                        )
                    )
        version_id = uuid4()
        version = DocumentVersion(
            id=version_id,
            document_id=doc.id,
            organization_id=org_id,
            project_id=project_id,
            number=doc.current_version,
            filename=payload.filename,
            file_format=kind,
            byte_size=len(raw),
            content_hash=checksum,
            uploaded_by=user.id,
            requested_by=user.id,
            idempotency_key=payload.idempotency_key,
            input_digest=digest,
            object_key=f"private/{org_id}/{project_id}/{doc.id}/{version_id}",
            status="uploading",
            lease_until=now() + timedelta(seconds=120),
        )
        db.add(version)
        db.flush()
        audit(
            db,
            user.id,
            org_id,
            "document.upload.reserve",
            doc.id,
            details={"version": version.number, "format": kind},
        )
        db.commit()
    version_id, doc_id = version.id, doc.id
    upload_error = False
    try:
        storage_client().put_object(
            Bucket=get_settings().s3_bucket,
            Key=object_key(version),
            Body=raw,
            ContentType="application/octet-stream",
            Metadata={"sha256": checksum},
        )
    except Exception:
        upload_error = True
    # A durable uploading record allows recovery if the request is interrupted after S3 upload.
    db.expire_all()
    doc = db.scalar(select(PrivateDocument).where(PrivateDocument.id == doc_id).with_for_update())
    version = db.scalar(
        select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
    )
    if doc.is_deleted:
        # A late PUT must re-arm cleanup even if an earlier delete already completed.
        version.status, version.delete_attempts = "deleting", 0
        version.object_key = f"private/{org_id}/{project_id}/{doc.id}/{version.id}"
        version.lease_until = None
        db.commit()
        raise HTTPException(404)
    version.status = "failed" if upload_error else "uploaded"
    version.error_code = "UPLOAD_FAILED" if upload_error else None
    version.lease_until = None
    audit(
        db,
        user.id,
        org_id,
        "document.upload.failed" if upload_error else "document.upload",
        doc.id,
        result="failed" if upload_error else "success",
        details={"version": version.number},
    )
    db.commit()
    return doc
