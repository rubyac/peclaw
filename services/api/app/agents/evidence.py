"""Read-only, bounded retrieval; the model never selects its own access scope."""

import hashlib
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.gateway import ModelError
from app.catalog.service import search
from app.knowledge.access import document_access
from app.knowledge.retrieval import citation
from app.models.catalog import Company, Evidence
from app.models.knowledge import DocumentChunk, DocumentVersion
from app.schemas.agents import TaskInput
from app.security.dependencies import project_access


def public_company(db, company_id):
    record = db.get(Company, company_id)
    if not record or record.is_archived or record.merged_into_id:
        raise ModelError("COMPANY_UNAVAILABLE")
    return record


def company_excerpt(record):
    # Explicit public fields. No raw ORM serialization or related private data.
    fields = {
        key: getattr(record, key)
        for key in [
            "canonical_name",
            "country",
            "province",
            "city",
            "description",
            "listing_status",
            "company_stage",
            "financing_stage",
        ]
    }
    import json

    fields["updated_at"] = record.updated_at.isoformat()
    fields["version"] = record.version
    return json.dumps(fields, ensure_ascii=False)


def public_evidence_hash(item):
    import json

    values = [
        item.excerpt,
        item.claim_text,
        item.classification,
        item.verification_status,
        str(item.source_id),
        item.page_number,
        item.section_name,
    ]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def document_versions(db, user, org_id, project_id, payload):
    versions = []
    for doc_id in payload.document_ids:
        doc = document_access(db, user, org_id, project_id, doc_id)
        version = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == doc.id, DocumentVersion.number == doc.current_version
            )
        )
        if not version or version.status != "indexed":
            raise ModelError("DOCUMENT_NOT_INDEXED")
        versions.append(version)
    return versions


def collect(db: Session, user, org_id, project_id, payload: TaskInput):
    project_access(db, user, org_id, project_id, "write")
    evidence, refs, candidate_ids = [], [], []
    if payload.kind == "company_discovery":
        filters = payload.filters.model_copy(
            update={"limit": min(payload.filters.limit, 20), "offset": 0, "include_archived": False}
        )
        result = search(db, filters)
        companies = [public_company(db, UUID(str(item["id"]))) for item in result["items"]]
    else:
        companies = [public_company(db, payload.company_id)] if payload.company_id else []
    for company in companies:
        candidate_ids.append(str(company.id))
        excerpt = company_excerpt(company)
        ref = {
            "id": "company:" + str(company.id),
            "kind": "company",
            "resource_id": str(company.id),
            "hash": hashlib.sha256(excerpt.encode()).hexdigest(),
        }
        refs.append(ref)
        evidence.append(
            {
                **ref,
                "excerpt": excerpt,
                "verification": "unverified",
                "updated_at": company.updated_at.isoformat(),
            }
        )
        for item in db.scalars(
            select(Evidence).where(Evidence.company_id == company.id).order_by(Evidence.id).limit(6)
        ):
            ref = {
                "id": "evidence:" + str(item.id),
                "kind": "public_evidence",
                "resource_id": str(item.id),
                "hash": public_evidence_hash(item),
            }
            refs.append(ref)
            evidence.append(
                {
                    **ref,
                    "excerpt": item.excerpt[:2500],
                    "claim": item.claim_text,
                    "verification": item.verification_status,
                    "classification": item.classification,
                    "page_number": item.page_number,
                    "section_name": item.section_name,
                }
            )
    versions = document_versions(db, user, org_id, project_id, payload)
    # Cover every explicitly selected document; deterministic leading chunks are labelled partial.
    for version in versions:
        chunks = db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.version_id == version.id,
                DocumentChunk.organization_id == org_id,
                DocumentChunk.project_id == project_id,
            )
            .order_by(DocumentChunk.chunk_index)
            .limit(8)
        ).all()
        if not chunks:
            raise ModelError("DOCUMENT_NOT_INDEXED")
        for chunk in chunks:
            ref = {
                "id": "chunk:" + str(chunk.id),
                "kind": "private_chunk",
                "resource_id": str(chunk.id),
                "document_id": str(version.document_id),
                "version_id": str(version.id),
                "hash": chunk.content_hash,
            }
            refs.append(ref)
            evidence.append(
                {
                    **ref,
                    "excerpt": chunk.text,
                    "verification": "unverified",
                    "version": version.number,
                    "locator": chunk.locator,
                    "page_number": chunk.page_number,
                    "section_name": chunk.section_name,
                }
            )
    context = {
        "workflow": payload.kind,
        "question": payload.question,
        "investment_thesis": payload.thesis,
        "applied_filters": filters.model_dump(mode="json")
        if payload.kind == "company_discovery"
        else None,
        "candidate_company_ids": candidate_ids,
        "evidence": evidence,
        "retrieval_limitations": [
            "公共候选最多20家，每家最多6条证据；每份明确选择的私有文件最多前8片段。",
            "仅当前项目明确选择的文档，不自动读取其他项目历史；没有互联网补全。",
            "上下文是不完整的授权材料；未覆盖部分必须列为数据缺口，所有数字待人工核验。",
        ],
    }
    import json

    if len(json.dumps(context, ensure_ascii=False)) > 38000:
        raise ModelError("CONTEXT_LIMIT")
    return context, refs


def resolve(db, user, org_id, project_id, refs):
    """Recheck live ACL and source hashes before calls, commits and every result read."""
    project_access(db, user, org_id, project_id)
    output = []
    for ref in refs:
        identity = UUID(ref["resource_id"])
        if ref["kind"] == "private_chunk":
            doc = document_access(db, user, org_id, project_id, UUID(ref["document_id"]))
            chunk = db.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.id == identity,
                    DocumentChunk.organization_id == org_id,
                    DocumentChunk.project_id == project_id,
                    DocumentChunk.document_id == doc.id,
                    DocumentChunk.version_id == UUID(ref["version_id"]),
                )
            )
            if not chunk or chunk.content_hash != ref["hash"]:
                raise ModelError("EVIDENCE_CHANGED")
            version = db.get(DocumentVersion, chunk.version_id)
            if not version or version.status != "indexed":
                raise ModelError("EVIDENCE_CHANGED")
            output.append({"id": ref["id"], "kind": ref["kind"], **citation(chunk, version, doc)})
        elif ref["kind"] == "company":
            record = public_company(db, identity)
            excerpt = company_excerpt(record)
            if hashlib.sha256(excerpt.encode()).hexdigest() != ref["hash"]:
                raise ModelError("EVIDENCE_CHANGED")
            output.append(
                {
                    "id": ref["id"],
                    "kind": ref["kind"],
                    "company_id": str(record.id),
                    "excerpt": excerpt,
                    "updated_at": record.updated_at.isoformat(),
                }
            )
        else:
            item = db.get(Evidence, identity)
            if not item or public_evidence_hash(item) != ref["hash"]:
                raise ModelError("EVIDENCE_CHANGED")
            public_company(db, item.company_id)
            output.append(
                {
                    "id": ref["id"],
                    "kind": ref["kind"],
                    "company_id": str(item.company_id),
                    "excerpt": item.excerpt,
                    "verification_status": item.verification_status,
                    "classification": item.classification,
                    "page_number": item.page_number,
                    "section_name": item.section_name,
                }
            )
    return output
