import hashlib
import json
import os
import subprocess
import sys
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.agents.gateway import embedding as encode
from app.core.config import get_settings
from app.knowledge.access import document_access
from app.knowledge.embedding import MODEL_ID
from app.knowledge.parsing import ParseFailure, TextUnit, chunk_units
from app.knowledge.service import PROCESSING, object_key
from app.models.identity import User, now
from app.models.knowledge import DocumentChunk, DocumentVersion, PrivateDocument
from app.services.audit import audit
from app.services.dependencies import storage_client


class Cancelled(Exception):
    pass


def read_original(version: DocumentVersion) -> bytes:
    response = storage_client().get_object(Bucket=get_settings().s3_bucket, Key=object_key(version))
    try:
        raw = response["Body"].read(get_settings().knowledge_max_file_bytes + 1)
    finally:
        response["Body"].close()
    if len(raw) != version.byte_size or hashlib.sha256(raw).hexdigest() != version.content_hash:
        raise ParseFailure("RAW_FILE_HASH_MISMATCH")
    return raw


def advance(engine, version_id, token, status) -> bool:
    with Session(engine) as db:
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
        )
        if version.claim_token != token or version.status not in PROCESSING:
            return False
        version.status, version.lease_until = status, now() + timedelta(seconds=120)
        db.commit()
        return True


def parse_local(raw: bytes, kind: str) -> list[TextUnit]:
    try:
        process = subprocess.run(
            [sys.executable, "-m", "app.knowledge.parse_child", kind],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=40,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"},
        )
        if process.returncode != 0:
            raise ParseFailure("PARSER_RESOURCE_LIMIT")
        data = json.loads(process.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        raise ParseFailure("PARSER_RESOURCE_LIMIT") from None
    if "error" in data:
        raise ParseFailure(data["error"])
    return [TextUnit(**unit) for unit in data["units"]]


def authorized_actor(db: Session, version: DocumentVersion) -> User:
    user = db.get(User, version.requested_by)
    if not user or not user.is_active:
        raise ParseFailure("ACCESS_REVOKED")
    document_access(
        db,
        user,
        version.organization_id,
        version.project_id,
        version.document_id,
        permission="write",
    )
    return user


def cleanup_one(engine) -> bool:
    with Session(engine) as db:
        version = db.scalar(
            select(DocumentVersion)
            .where(
                DocumentVersion.status == "deleting",
                DocumentVersion.delete_attempts < 3,
                or_(DocumentVersion.lease_until.is_(None), DocumentVersion.lease_until < now()),
            )
            .order_by(DocumentVersion.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not version:
            return False
        doc = db.get(PrivateDocument, version.document_id)
        if not doc.is_deleted:
            raise ParseFailure("INVALID_DELETE_STATE")
        token = uuid4()
        version.claim_token, version.lease_until = token, now() + timedelta(seconds=120)
        version.delete_attempts += 1
        version_id = version.id
        key = object_key(version)
        db.commit()
    failed = False
    try:
        storage_client().delete_object(Bucket=get_settings().s3_bucket, Key=key)
    except Exception:
        failed = True
    with Session(engine) as db:
        version = db.scalar(
            select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
        )
        if version.claim_token != token or version.status != "deleting":
            return True
        if failed:
            version.error_code = "OBJECT_DELETE_FAILED"
            version.lease_until = now() + timedelta(seconds=15)
        else:
            version.status, version.object_key, version.chunk_count = "deleted", None, 0
            version.error_code, version.finished_at, version.lease_until = None, now(), None
        audit(
            db,
            version.requested_by,
            version.organization_id,
            "document.purge.failed" if failed else "document.purge",
            version.document_id,
            result="failed" if failed else "success",
            details={"version": version.number},
        )
        db.commit()
    return True


def execute_ingestion(engine) -> bool:
    if cleanup_one(engine):
        return True
    with Session(engine) as db:
        expired = db.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.status.in_(PROCESSING),
                DocumentVersion.lease_until < now(),
                DocumentVersion.attempts >= 3,
            )
            .with_for_update(skip_locked=True)
        ).all()
        for item in expired:
            item.status, item.error_code, item.finished_at = "failed", "ATTEMPTS_EXHAUSTED", now()
        db.commit()
        version = db.scalar(
            select(DocumentVersion)
            .where(
                or_(
                    DocumentVersion.status == "uploaded",
                    (DocumentVersion.status.in_([*PROCESSING, "uploading"]))
                    & (DocumentVersion.lease_until < now()),
                ),
                DocumentVersion.attempts < 3,
            )
            .order_by(DocumentVersion.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not version:
            return False
        token, version_id = uuid4(), version.id
        was_uploading = version.status == "uploading"
        version.claim_token, version.status = token, "validating"
        version.attempts += 1
        version.started_at, version.lease_until, version.error_code = (
            now(),
            now() + timedelta(seconds=120),
            None,
        )
        db.commit()
    try:
        with Session(engine) as db:
            version = db.get(DocumentVersion, version_id)
            authorized_actor(db, version)
            raw, kind = read_original(version), version.file_format
        if not advance(engine, version_id, token, "parsing"):
            raise Cancelled()
        units = parse_local(raw, kind)
        if not advance(engine, version_id, token, "chunking"):
            raise Cancelled()
        chunks = chunk_units(units)
        if not advance(engine, version_id, token, "embedding"):
            raise Cancelled()
        for number, chunk in enumerate(chunks):
            chunk["embedding"], chunk["tokens"] = encode(chunk["text"])
            if number % 50 == 0 and not advance(engine, version_id, token, "embedding"):
                raise Cancelled()
        with Session(engine) as db:
            # Same lock order as API writes: document, then version. Parsing holds neither lock.
            version_reference = db.get(DocumentVersion, version_id)
            doc = db.scalar(
                select(PrivateDocument)
                .where(PrivateDocument.id == version_reference.document_id)
                .with_for_update()
            )
            version = db.scalar(
                select(DocumentVersion)
                .where(DocumentVersion.id == version_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if doc.is_deleted or version.claim_token != token or version.status not in PROCESSING:
                raise Cancelled()
            authorized_actor(db, version)
            db.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version.id))
            for chunk in chunks:
                tokens = chunk.pop("tokens")
                db.add(
                    DocumentChunk(
                        version_id=version.id,
                        document_id=doc.id,
                        organization_id=doc.organization_id,
                        project_id=doc.project_id,
                        embedding_model=MODEL_ID,
                        search_vector=func.to_tsvector("simple", tokens),
                        **chunk,
                    )
                )
            version.status, version.chunk_count = "indexed", len(chunks)
            version.finished_at, version.lease_until, version.error_code = now(), None, None
            audit(
                db,
                version.requested_by,
                doc.organization_id,
                "document.indexed",
                doc.id,
                details={"version": version.number, "chunks": len(chunks)},
            )
            db.commit()
    except Cancelled:
        pass
    except Exception as error:
        with Session(engine) as db:
            version = db.scalar(
                select(DocumentVersion).where(DocumentVersion.id == version_id).with_for_update()
            )
            if version.claim_token == token and version.status in PROCESSING:
                code = (
                    str(error)
                    if isinstance(error, ParseFailure)
                    else (
                        "ACCESS_REVOKED"
                        if isinstance(error, HTTPException)
                        else ("UPLOAD_INTERRUPTED" if was_uploading else "INGESTION_FAILED")
                    )
                )
                version.status, version.error_code = "failed", code[:80]
                version.finished_at, version.lease_until = now(), None
                db.execute(delete(DocumentChunk).where(DocumentChunk.version_id == version.id))
                audit(
                    db,
                    version.requested_by,
                    version.organization_id,
                    "document.index.failed",
                    version.document_id,
                    result="failed",
                    details={"version": version.number, "code": code[:80]},
                )
                db.commit()
    return True
