from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.catalog.access import conflict, require_curator, require_reader
from app.catalog.imports import import_output, input_digest
from app.catalog.service import (
    company,
    create_company,
    detail,
    duplicates,
    history,
    parse_intent,
    search,
    set_fields,
    snapshot,
    source,
    source_output,
)
from app.models.catalog import (
    CatalogImport,
    Company,
    CompanyChange,
    CompanyMerge,
    CompanyTechnology,
    DataSource,
    Evidence,
    IndustryNode,
    Product,
    Technology,
)
from app.models.identity import AuditLog, User, now
from app.schemas.catalog import (
    ArchiveInput,
    CompanyCreate,
    CompanyFields,
    CompanyOutput,
    CompanyUpdate,
    EvidenceInput,
    EvidenceReview,
    ImportInput,
    ImportOutput,
    MergeInput,
    NaturalSearch,
    NaturalSearchOutput,
    ProductInput,
    SearchFilters,
    SearchOutput,
    SourceInput,
    SourceOutput,
    TaxonomyInput,
    TechnologyLink,
    UndoMergeInput,
)
from app.security.dependencies import CurrentUser, Db
from app.services.audit import audit

router = APIRouter(prefix="/api/v1", tags=["public catalog"])


@router.get("/catalog/sources", response_model=list[SourceOutput])
def sources(user: CurrentUser, db: Db):
    require_reader(db, user)
    return [
        source_output(s)
        for s in db.scalars(select(DataSource).order_by(DataSource.created_at.desc()))
    ]


@router.post("/catalog/sources", status_code=201, response_model=SourceOutput)
def create_source(payload: SourceInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    record = DataSource(**payload.model_dump(), created_by=user.id)
    db.add(record)
    db.flush()
    audit(db, user.id, None, "catalog.source.create", record.id)
    db.commit()
    return source_output(record)


@router.get("/catalog/taxonomy")
def taxonomy(user: CurrentUser, db: Db):
    require_reader(db, user)
    return {
        "industries": [
            {
                "id": n.id,
                "name": n.name,
                "parent_id": n.parent_id,
                "level": n.level,
                "description": n.description,
            }
            for n in db.scalars(
                select(IndustryNode).order_by(IndustryNode.level, IndustryNode.name)
            )
        ],
        "technologies": [
            {
                "id": n.id,
                "name": n.name,
                "parent_id": n.parent_id,
                "aliases": n.aliases,
                "description": n.description,
            }
            for n in db.scalars(select(Technology).order_by(Technology.name))
        ],
    }


@router.post("/catalog/taxonomy/{kind}", status_code=201)
def create_taxonomy(kind: str, payload: TaxonomyInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    model = IndustryNode if kind == "industries" else Technology if kind == "technologies" else None
    if not model:
        raise HTTPException(404)
    parent = db.get(model, payload.parent_id) if payload.parent_id else None
    if payload.parent_id and not parent:
        raise HTTPException(404)
    if model is IndustryNode:
        if parent and parent.level >= 6:
            raise HTTPException(422)
        record = IndustryNode(
            name=payload.name,
            parent_id=payload.parent_id,
            description=payload.description,
            level=parent.level + 1 if parent else 1,
        )
    else:
        record = Technology(**payload.model_dump())
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        conflict("该分类名称已存在")
    audit(db, user.id, None, "catalog.taxonomy.create", record.id, details={"kind": kind})
    db.commit()
    return {"id": record.id, "name": record.name}


@router.get("/catalog/audit")
def catalog_audit(user: CurrentUser, db: Db, limit: int = Query(50, ge=1, le=100)):
    require_curator(db, user)
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.organization_id.is_(None), AuditLog.action.startswith("catalog."))
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": log.id,
            "actor_id": log.actor_id,
            "action": log.action,
            "resource_id": log.resource_id,
            "result": log.result,
            "request_id": log.request_id,
            "created_at": log.created_at,
            "details": log.details,
        }
        for log in logs
    ]


@router.get("/companies", response_model=SearchOutput)
def companies(user: CurrentUser, db: Db, filters: SearchFilters = Depends()):
    require_reader(db, user)
    return search(db, filters)


@router.post("/companies/search", response_model=NaturalSearchOutput)
def natural_search(payload: NaturalSearch, user: CurrentUser, db: Db):
    require_reader(db, user)
    filters, matched = parse_intent(db, payload.query, payload.filters)
    result = search(db, filters)
    return {
        **result,
        "applied_filters": filters.model_dump(mode="json"),
        "matched_intent": matched,
        "unparsed_criteria": [
            word
            for word in [
                "收入",
                "营收",
                "客户",
                "估值",
                "融资金额",
                "市场份额",
                "成立",
                "利润",
                "毛利",
            ]
            if word in payload.query
        ],
        "limitations": (
            "规则匹配，仅应用已显示条件；其他描述未自动执行。不推断未知字段，不代表完整市场覆盖。"
        ),
    }


@router.post("/companies", status_code=201, response_model=CompanyOutput)
def add_company(payload: CompanyCreate, user: CurrentUser, db: Db):
    require_curator(db, user)
    record = create_company(db, user, payload)
    db.commit()
    return detail(db, record)


@router.get("/companies/{company_id}", response_model=CompanyOutput)
def company_detail(company_id: UUID, user: CurrentUser, db: Db):
    require_reader(db, user)
    return detail(db, company(db, company_id))


@router.patch("/companies/{company_id}", response_model=CompanyOutput)
def update_company(company_id: UUID, payload: CompanyUpdate, user: CurrentUser, db: Db):
    require_curator(db, user)
    source(db, payload.source_id)
    record = company(db, company_id, writable=True, lock=True)
    if record.version != payload.expected_version:
        conflict()
    before = snapshot(db, record)
    fields = {key: before[key] for key in CompanyFields.model_fields}
    fields.update(
        payload.model_dump(exclude_unset=True, exclude={"source_id", "reason", "expected_version"})
    )
    set_fields(db, record, CompanyFields.model_validate(fields))
    record.source_id = payload.source_id
    record.version += 1
    history(db, user, record, payload.source_id, "company.update", payload.reason, before)
    db.commit()
    return detail(db, record)


@router.post("/companies/{company_id}/archive", response_model=CompanyOutput)
def archive(company_id: UUID, payload: ArchiveInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    source(db, payload.source_id)
    record = company(db, company_id, lock=True)
    if record.version != payload.expected_version or record.merged_into_id:
        conflict()
    before = snapshot(db, record)
    record.is_archived = payload.archived
    record.version += 1
    record.updated_at = now()
    history(db, user, record, payload.source_id, "company.archive", payload.reason, before)
    db.commit()
    return detail(db, record)


@router.get("/companies/{company_id}/history")
def changes(company_id: UUID, user: CurrentUser, db: Db):
    require_reader(db, user)
    company(db, company_id)
    return [
        {
            key: getattr(change, key)
            for key in [
                "id",
                "actor_id",
                "source_id",
                "action",
                "reason",
                "before",
                "after",
                "created_at",
            ]
        }
        for change in db.scalars(
            select(CompanyChange)
            .where(CompanyChange.company_id == company_id)
            .order_by(CompanyChange.created_at.desc())
        )
    ]


@router.get("/companies/{company_id}/duplicates")
def possible_duplicates(company_id: UUID, user: CurrentUser, db: Db):
    require_curator(db, user)
    return duplicates(db, company(db, company_id))


@router.post("/companies/{company_id}/evidence", status_code=201)
def add_evidence(company_id: UUID, payload: EvidenceInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    record = company(db, company_id, writable=True, lock=True)
    source(db, payload.source_id)
    evidence = Evidence(**payload.model_dump(), company_id=record.id)
    if payload.verification_status == "verified":
        evidence.reviewer_id, evidence.reviewed_at = user.id, now()
    db.add(evidence)
    record.updated_at = now()
    audit(
        db,
        user.id,
        None,
        "catalog.evidence.create",
        record.id,
        details={
            "classification": payload.classification,
            "verification_status": payload.verification_status,
        },
    )
    db.commit()
    return {"id": evidence.id}


@router.patch("/companies/{company_id}/evidence/{evidence_id}")
def review_evidence(
    company_id: UUID, evidence_id: UUID, payload: EvidenceReview, user: CurrentUser, db: Db
):
    require_curator(db, user)
    company(db, company_id, writable=True, lock=True)
    evidence = db.get(Evidence, evidence_id)
    if not evidence or evidence.company_id != company_id:
        raise HTTPException(404)
    if evidence.classification == "inference" and payload.verification_status == "verified":
        raise HTTPException(422)
    previous = evidence.verification_status
    evidence.verification_status = payload.verification_status
    evidence.reviewer_id, evidence.reviewed_at = user.id, now()
    audit(
        db,
        user.id,
        None,
        "catalog.evidence.review",
        evidence.id,
        details={
            "before": previous,
            "after": payload.verification_status,
            "reason": payload.reason,
        },
    )
    db.commit()
    return {"id": evidence.id, "verification_status": evidence.verification_status}


def company_evidence(db: Db, company_id: UUID, evidence_id: UUID) -> Evidence:
    evidence = db.get(Evidence, evidence_id)
    if (
        not evidence
        or evidence.company_id != company_id
        or evidence.verification_status == "rejected"
    ):
        raise HTTPException(
            422, detail={"code": "EVIDENCE_MISMATCH", "message": "证据必须属于当前企业且未被拒绝"}
        )
    return evidence


@router.post("/companies/{company_id}/technologies", status_code=201)
def add_technology(company_id: UUID, payload: TechnologyLink, user: CurrentUser, db: Db):
    require_curator(db, user)
    record = company(db, company_id, writable=True, lock=True)
    company_evidence(db, record.id, payload.evidence_id)
    if not db.get(Technology, payload.technology_id):
        raise HTTPException(404)
    existing = db.scalar(
        select(CompanyTechnology).where(
            CompanyTechnology.company_id == record.id,
            CompanyTechnology.technology_id == payload.technology_id,
            CompanyTechnology.relation_type == payload.relation_type,
        )
    )
    if existing:
        conflict("该技术关联已存在")
    link = CompanyTechnology(company_id=record.id, **payload.model_dump())
    db.add(link)
    record.updated_at = now()
    audit(db, user.id, None, "catalog.technology.link", record.id)
    db.commit()
    return {"id": link.id}


@router.post("/companies/{company_id}/products", status_code=201)
def add_product(company_id: UUID, payload: ProductInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    record = company(db, company_id, writable=True, lock=True)
    evidence = company_evidence(db, record.id, payload.evidence_id)
    source(db, payload.source_id)
    if evidence.source_id != payload.source_id:
        raise HTTPException(422)
    product = Product(company_id=record.id, **payload.model_dump())
    db.add(product)
    record.updated_at = now()
    audit(db, user.id, None, "catalog.product.create", record.id)
    db.commit()
    return {"id": product.id}


@router.post("/companies/{company_id}/merge")
def merge(company_id: UUID, payload: MergeInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    source(db, payload.source_id)
    if company_id == payload.duplicate_id:
        raise HTTPException(422)
    for identifier in sorted([company_id, payload.duplicate_id], key=str):
        company(db, identifier, lock=True)
    target = company(db, company_id, writable=True)
    duplicate = company(db, payload.duplicate_id, writable=True)
    if (
        target.version != payload.expected_target_version
        or duplicate.version != payload.expected_duplicate_version
    ):
        conflict()
    if db.scalar(select(Company.id).where(Company.merged_into_id == duplicate.id).limit(1)):
        conflict("请先撤销候选档案已有的合并关系，再执行此合并")
    before_target, before_duplicate = snapshot(db, target), snapshot(db, duplicate)
    record = CompanyMerge(
        target_id=target.id,
        duplicate_id=duplicate.id,
        source_id=payload.source_id,
        actor_id=user.id,
        reason=payload.reason,
        snapshots={"target": before_target, "duplicate": before_duplicate},
    )
    db.add(record)
    duplicate.merged_into_id = target.id
    for item, before in [(target, before_target), (duplicate, before_duplicate)]:
        item.version += 1
        item.updated_at = now()
        history(db, user, item, payload.source_id, "company.merge", payload.reason, before)
    db.commit()
    return {"merge_id": record.id, "company": detail(db, target)}


@router.post("/catalog/merges/{merge_id}/undo")
def undo_merge(merge_id: UUID, payload: UndoMergeInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    source(db, payload.source_id)
    record = db.get(CompanyMerge, merge_id)
    if not record:
        raise HTTPException(404)
    for identifier in sorted([record.target_id, record.duplicate_id], key=str):
        company(db, identifier, lock=True)
    db.refresh(record)
    target, duplicate = company(db, record.target_id), company(db, record.duplicate_id)
    if (
        record.reverted_at
        or duplicate.merged_into_id != target.id
        or target.version != payload.expected_target_version
        or duplicate.version != payload.expected_duplicate_version
    ):
        conflict()
    before_target, before_duplicate = snapshot(db, target), snapshot(db, duplicate)
    duplicate.merged_into_id = None
    record.reverted_at, record.reverted_by, record.revert_reason = now(), user.id, payload.reason
    for item, before in [(target, before_target), (duplicate, before_duplicate)]:
        item.version += 1
        item.updated_at = now()
        history(db, user, item, payload.source_id, "company.unmerge", payload.reason, before)
    db.commit()
    return detail(db, target)


@router.post("/catalog/imports", status_code=202, response_model=ImportOutput)
def queue_import(payload: ImportInput, user: CurrentUser, db: Db):
    require_curator(db, user)
    source(db, payload.source_id)
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    previous = db.scalar(
        select(CatalogImport).where(
            CatalogImport.requested_by == user.id,
            CatalogImport.idempotency_key == payload.idempotency_key,
        )
    )
    checksum = input_digest(payload)
    if previous:
        if previous.input_digest != checksum:
            conflict("同一幂等键不能用于不同导入内容")
        return import_output(previous)
    job = CatalogImport(
        requested_by=user.id,
        source_id=payload.source_id,
        idempotency_key=payload.idempotency_key,
        input_digest=checksum,
        input_payload=payload.model_dump(mode="json"),
    )
    db.add(job)
    db.flush()
    audit(db, user.id, None, "catalog.import.queued", job.id)
    db.commit()
    return import_output(job)


@router.get("/catalog/imports", response_model=list[ImportOutput])
def list_imports(user: CurrentUser, db: Db):
    require_curator(db, user)
    return [
        import_output(job)
        for job in db.scalars(
            select(CatalogImport)
            .where(CatalogImport.requested_by == user.id)
            .order_by(CatalogImport.created_at.desc())
            .limit(50)
        )
    ]


@router.get("/catalog/imports/{job_id}", response_model=ImportOutput)
def get_import(job_id: UUID, user: CurrentUser, db: Db):
    require_curator(db, user)
    job = db.get(CatalogImport, job_id)
    if not job or job.requested_by != user.id:
        raise HTTPException(404)
    return import_output(job)


@router.post("/catalog/imports/{job_id}/retry", response_model=ImportOutput)
def retry_import(job_id: UUID, user: CurrentUser, db: Db):
    require_curator(db, user)
    job = db.scalar(select(CatalogImport).where(CatalogImport.id == job_id).with_for_update())
    if not job or job.requested_by != user.id:
        raise HTTPException(404)
    if job.state != "failed" or job.attempts >= 3:
        conflict("仅可重试失败任务，最多执行三次")
    job.state, job.error_code, job.started_at, job.finished_at = "queued", None, None, None
    audit(db, user.id, None, "catalog.import.retry", job.id)
    db.commit()
    return import_output(job)
