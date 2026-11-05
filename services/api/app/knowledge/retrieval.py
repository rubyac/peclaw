import hashlib
from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.agents.gateway import embedding as encode
from app.knowledge.access import authorized_projects, readable_predicate
from app.models.identity import User
from app.models.knowledge import DocumentChunk, DocumentVersion, PrivateDocument
from app.schemas.knowledge import KnowledgeQuery
from app.services.audit import audit


def citation(
    chunk: DocumentChunk,
    version: DocumentVersion,
    doc: PrivateDocument,
    matched_by: list[str] | None = None,
) -> dict:
    return {
        "chunk_id": chunk.id,
        "document_id": doc.id,
        "version_id": version.id,
        "version_number": version.number,
        "document_title": doc.title,
        "project_id": doc.project_id,
        "excerpt": chunk.text,
        "content_hash": chunk.content_hash,
        "file_hash": version.content_hash,
        "page_number": chunk.page_number,
        "section_name": chunk.section_name,
        "locator": chunk.locator,
        "start_offset": chunk.start_offset,
        "end_offset": chunk.end_offset,
        "matched_by": matched_by or [],
    }


def search_private(db: Session, user: User, org_id: UUID, payload: KnowledgeQuery) -> dict:
    if not user.is_active:
        raise HTTPException(401)
    vector, tokens = encode(payload.query)
    # Every candidate query is scoped BEFORE ranking/limiting, including document-level grants.
    base = (
        select(DocumentChunk, DocumentVersion, PrivateDocument)
        .join(DocumentVersion, DocumentChunk.version_id == DocumentVersion.id)
        .join(PrivateDocument, DocumentChunk.document_id == PrivateDocument.id)
        .where(
            DocumentChunk.organization_id == org_id,
            DocumentChunk.project_id.in_(authorized_projects(user, org_id)),
            PrivateDocument.is_deleted.is_(False),
            readable_predicate(user.id),
            DocumentVersion.status == "indexed",
            DocumentVersion.number == PrivateDocument.current_version,
        )
    )
    if payload.project_id:
        base = base.where(DocumentChunk.project_id == payload.project_id)
    rankings = []
    if payload.mode in {"keyword", "hybrid"}:
        tsquery = func.plainto_tsquery("simple", tokens)
        literal = (
            "%" + payload.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        )
        keyword = (
            base.where(
                or_(
                    DocumentChunk.search_vector.op("@@")(tsquery),
                    DocumentChunk.text.ilike(literal, escape="\\"),
                )
            )
            .order_by(
                func.ts_rank_cd(DocumentChunk.search_vector, tsquery).desc(), DocumentChunk.id
            )
            .limit(100)
        )
        rankings.append(("keyword", db.execute(keyword).all()))
    if payload.mode in {"semantic", "hybrid"} and vector is not None:
        distance = DocumentChunk.embedding.cosine_distance(vector)
        semantic = (
            base.where(DocumentChunk.embedding.is_not(None), distance <= 0.75)
            .order_by(distance, DocumentChunk.id)
            .limit(100)
        )
        rankings.append(("semantic", db.execute(semantic).all()))
    scores = defaultdict(float)
    records = {}
    reasons = defaultdict(list)
    for name, rows in rankings:
        for rank, row in enumerate(rows, 1):
            chunk, version, doc = row
            scores[chunk.id] += 1 / (60 + rank)
            records[chunk.id] = (chunk, version, doc)
            reasons[chunk.id].append(name)
    keys = sorted(scores, key=lambda key: (-scores[key], str(key)))[: payload.limit]
    items = [citation(*records[key], reasons[key]) for key in keys]
    audit(
        db,
        user.id,
        org_id,
        "knowledge.search",
        payload.project_id,
        details={
            "query_hash": hashlib.sha256(payload.query.encode()).hexdigest(),
            "mode": payload.mode,
            "results": len(items),
        },
    )
    db.commit()
    return {
        "items": items,
        "mode": payload.mode,
        "semantic_available": vector is not None,
        "limitations": (
            "本地中文词向量与关键词融合检索；相似原文不代表事实已核验，"
            "无可用词向量时不产生语义候选。"
        ),
    }
