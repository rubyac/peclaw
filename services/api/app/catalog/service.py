import difflib
import unicodedata
from collections import defaultdict
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.catalog.access import conflict
from app.models.catalog import (
    Company,
    CompanyAlias,
    CompanyChange,
    CompanyIndustry,
    CompanyMerge,
    CompanyTechnology,
    DataSource,
    Evidence,
    IndustryNode,
    Product,
    Technology,
)
from app.models.identity import User, now
from app.schemas.catalog import CompanyCreate, CompanyFields, SearchFilters
from app.services.audit import audit


def normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def domain(value: str | None) -> str | None:
    if not value:
        return None
    return (urlsplit(value).hostname or "").lower().removeprefix("www.") or None


def source(db: Session, source_id: UUID) -> DataSource:
    record = db.get(DataSource, source_id)
    if not record or not record.public_confirmed:
        raise HTTPException(404)
    return record


def company(
    db: Session, company_id: UUID, *, writable: bool = False, lock: bool = False
) -> Company:
    query = select(Company).where(Company.id == company_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = db.scalar(query)
    if not record:
        raise HTTPException(404)
    if writable and (record.is_archived or record.merged_into_id):
        conflict("已归档或已合并档案不可编辑，请先恢复或撤销合并")
    return record


def snapshot(db: Session, record: Company) -> dict:
    columns = [
        column.name
        for column in Company.__table__.columns
        if column.name not in {"normalized_name", "website_domain"}
    ]
    values = {key: getattr(record, key) for key in columns}
    for key, value in values.items():
        if value is not None and not isinstance(value, (str, int, bool, float, dict, list)):
            values[key] = value.isoformat() if hasattr(value, "isoformat") else str(value)
    values["aliases"] = list(
        db.scalars(select(CompanyAlias.name).where(CompanyAlias.company_id == record.id)).all()
    )
    values["industry_ids"] = [
        str(key)
        for key in db.scalars(
            select(CompanyIndustry.industry_id).where(CompanyIndustry.company_id == record.id)
        ).all()
    ]
    return values


def history(
    db: Session,
    user: User,
    record: Company,
    source_id: UUID,
    action: str,
    reason: str,
    before: dict,
    *,
    fingerprint: str | None = None,
) -> None:
    db.flush()
    db.add(
        CompanyChange(
            company_id=record.id,
            actor_id=user.id,
            source_id=source_id,
            action=action,
            reason=reason,
            before=before,
            after=snapshot(db, record),
            import_fingerprint=fingerprint,
        )
    )
    audit(
        db,
        user.id,
        None,
        "catalog." + action,
        record.id,
        details={"source_id": str(source_id), "version": record.version},
    )


def set_fields(db: Session, record: Company, payload: CompanyFields) -> None:
    for node_id in payload.industry_ids:
        if not db.get(IndustryNode, node_id):
            raise HTTPException(
                422, detail={"code": "INDUSTRY_NOT_FOUND", "message": "产业节点不存在"}
            )
    values = payload.model_dump(exclude={"aliases", "industry_ids"})
    for key, value in values.items():
        setattr(record, key, value)
    record.normalized_name = normalize(record.canonical_name)
    record.website_domain = domain(record.website)
    record.source_status = "unverified"
    record.updated_at = now()
    db.flush()
    db.execute(delete(CompanyAlias).where(CompanyAlias.company_id == record.id))
    seen = set()
    for alias in payload.aliases:
        normalized = normalize(alias)
        if normalized not in seen:
            db.add(CompanyAlias(company_id=record.id, name=alias, normalized_name=normalized))
            seen.add(normalized)
    db.execute(delete(CompanyIndustry).where(CompanyIndustry.company_id == record.id))
    for node_id in dict.fromkeys(payload.industry_ids):
        db.add(CompanyIndustry(company_id=record.id, industry_id=node_id))
    db.flush()


def create_company(
    db: Session, user: User, payload: CompanyCreate, fingerprint: str | None = None
) -> Company:
    source(db, payload.source_id)
    record = Company(source_id=payload.source_id)
    for key, value in payload.model_dump(exclude={"aliases", "industry_ids", "reason"}).items():
        setattr(record, key, value)
    record.normalized_name = normalize(payload.canonical_name)
    db.add(record)
    db.flush()
    set_fields(
        db,
        record,
        CompanyFields.model_validate(payload.model_dump(exclude={"source_id", "reason"})),
    )
    history(
        db,
        user,
        record,
        payload.source_id,
        "company.create",
        payload.reason,
        {},
        fingerprint=fingerprint,
    )
    return record


def group_ids(db: Session, record: Company) -> list[UUID]:
    if record.merged_into_id:
        return [record.id]
    return list(
        db.scalars(
            select(Company.id).where(
                or_(
                    Company.id == record.id,
                    and_(Company.merged_into_id == record.id, Company.is_archived.is_(False)),
                )
            )
        )
    )


def source_output(record: DataSource) -> dict:
    return {
        key: getattr(record, key)
        for key in [
            "id",
            "source_name",
            "source_type",
            "source_url",
            "publisher",
            "license_type",
            "permitted_use",
            "reliability_level",
            "published_at",
            "accessed_at",
            "content_hash",
        ]
    }


def detail(db: Session, record: Company) -> dict:
    data = snapshot(db, record)
    ids = group_ids(db, record) or [record.id]
    aliases = list(db.scalars(select(CompanyAlias.name).where(CompanyAlias.company_id.in_(ids))))
    children = db.scalars(select(Company).where(Company.merged_into_id == record.id)).all()
    data["aliases"] = list(dict.fromkeys(aliases + [c.canonical_name for c in children]))
    data["related_records"] = [
        {"id": c.id, "name": c.canonical_name, "version": c.version} for c in children
    ]
    industries = (
        db.execute(
            select(IndustryNode)
            .join(CompanyIndustry, CompanyIndustry.industry_id == IndustryNode.id)
            .where(CompanyIndustry.company_id.in_(ids))
        )
        .scalars()
        .all()
    )
    data["industries"] = [
        {"id": node.id, "name": node.name} for node in {n.id: n for n in industries}.values()
    ]
    evidence = db.scalars(
        select(Evidence).where(Evidence.company_id.in_(ids)).order_by(Evidence.created_at.desc())
    ).all()
    data["evidence"] = [
        {
            key: getattr(item, key)
            for key in [
                "id",
                "company_id",
                "source_id",
                "claim_text",
                "excerpt",
                "field_name",
                "field_value",
                "classification",
                "verification_status",
                "page_number",
                "section_name",
                "reviewer_id",
                "reviewed_at",
                "created_at",
            ]
        }
        for item in evidence
    ]
    claims = defaultdict(list)
    for item in evidence:
        if (
            item.field_name
            and item.field_value is not None
            and item.verification_status != "rejected"
        ):
            claims[item.field_name].append(item)
    data["conflicts"] = [
        {
            "field_name": key,
            "evidence_ids": [str(e.id) for e in rows],
            "values": sorted({e.field_value for e in rows}),
        }
        for key, rows in claims.items()
        if len({e.field_value for e in rows}) > 1
    ]
    for key in [
        "listing_status",
        "company_stage",
        "financing_stage",
        "country",
        "unified_social_credit_code",
    ]:
        rows = [c for c in [record, *children] if getattr(c, key) not in {None, "", "unknown"}]
        values = {getattr(c, key) for c in rows}
        if len(values) > 1:
            data["conflicts"].append(
                {
                    "field_name": key,
                    "values": sorted(values),
                    "evidence_ids": [],
                    "record_ids": [str(c.id) for c in rows],
                }
            )
    products = db.scalars(select(Product).where(Product.company_id.in_(ids))).all()
    data["products"] = [
        {
            "verification_status": next(
                (e.verification_status for e in evidence if e.id == item.evidence_id), "unverified"
            ),
            **{
                key: getattr(item, key)
                for key in [
                    "id",
                    "company_id",
                    "name",
                    "product_category",
                    "description",
                    "technical_route",
                    "commercialization_stage",
                    "source_id",
                    "evidence_id",
                ]
            },
        }
        for item in products
    ]
    links = db.execute(
        select(CompanyTechnology, Technology, Evidence)
        .join(Technology, CompanyTechnology.technology_id == Technology.id)
        .join(Evidence, CompanyTechnology.evidence_id == Evidence.id)
        .where(CompanyTechnology.company_id.in_(ids))
    ).all()
    data["technologies"] = [
        {
            "id": link.id,
            "technology_id": tech.id,
            "name": tech.name,
            "relation_type": link.relation_type,
            "evidence_id": ev.id,
            "verification_status": ev.verification_status,
            "company_id": link.company_id,
        }
        for link, tech, ev in links
    ]
    source_ids = {
        record.source_id,
        *(e.source_id for e in evidence),
        *(p.source_id for p in products),
        *(c.source_id for c in children),
    }
    source_ids.update(
        db.scalars(select(CompanyChange.source_id).where(CompanyChange.company_id.in_(ids)))
    )
    data["sources"] = [
        source_output(s)
        for s in db.scalars(select(DataSource).where(DataSource.id.in_(source_ids))).all()
    ]
    data["merges"] = [
        {
            "id": m.id,
            "target_id": m.target_id,
            "duplicate_id": m.duplicate_id,
            "reason": m.reason,
            "created_at": m.created_at,
            "reverted_at": m.reverted_at,
        }
        for m in db.scalars(
            select(CompanyMerge)
            .where(or_(CompanyMerge.target_id == record.id, CompanyMerge.duplicate_id == record.id))
            .order_by(CompanyMerge.created_at.desc())
        ).all()
    ]
    return data


def literal_like(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search(db: Session, filters: SearchFilters) -> dict:
    raw = aliased(Company)
    query = select(Company).where(Company.merged_into_id.is_(None))
    if not filters.include_archived:
        query = query.where(Company.is_archived.is_(False))
    for key in [
        "country",
        "province",
        "city",
        "listing_status",
        "company_stage",
        "financing_stage",
        "source_id",
    ]:
        value = getattr(filters, key)
        if value is not None:
            query = query.where(getattr(Company, key) == value)
    if filters.updated_since:
        query = query.where(Company.updated_at >= filters.updated_since)
    if filters.founded_after:
        query = query.where(Company.founded_on >= filters.founded_after)
    if filters.founded_before:
        query = query.where(Company.founded_on <= filters.founded_before)
    group_match = or_(raw.id == Company.id, raw.merged_into_id == Company.id)
    if filters.q:
        pattern = literal_like(normalize(filters.q))
        alias_match = (
            select(CompanyAlias.id)
            .where(
                CompanyAlias.company_id == raw.id,
                CompanyAlias.normalized_name.like(pattern, escape="\\"),
            )
            .exists()
        )
        query = query.where(
            select(raw.id)
            .where(
                group_match,
                or_(
                    raw.normalized_name.like(pattern, escape="\\"),
                    func.lower(raw.registration_name).like(pattern, escape="\\"),
                    func.lower(raw.description).like(pattern, escape="\\"),
                    alias_match,
                ),
            )
            .correlate(Company)
            .exists()
        )
    if filters.industry_id:
        descendants = (
            select(IndustryNode.id)
            .where(IndustryNode.id == filters.industry_id)
            .cte(name="industry_descendants", recursive=True)
        )
        descendants = descendants.union_all(
            select(IndustryNode.id).join(descendants, IndustryNode.parent_id == descendants.c.id)
        )
        query = query.where(
            select(raw.id)
            .join(CompanyIndustry, CompanyIndustry.company_id == raw.id)
            .where(group_match, CompanyIndustry.industry_id.in_(select(descendants.c.id)))
            .correlate(Company)
            .exists()
        )
    if filters.technology_id:
        query = query.where(
            select(raw.id)
            .join(CompanyTechnology, CompanyTechnology.company_id == raw.id)
            .where(group_match, CompanyTechnology.technology_id == filters.technology_id)
            .correlate(Company)
            .exists()
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    records = db.scalars(
        query.order_by(Company.updated_at.desc(), Company.id)
        .offset(filters.offset)
        .limit(filters.limit)
    ).all()
    return {
        "items": [summary(db, c) for c in records],
        "total": total,
        "limit": filters.limit,
        "offset": filters.offset,
    }


def summary(db: Session, record: Company) -> dict:
    return {
        "id": record.id,
        "canonical_name": record.canonical_name,
        "province": record.province,
        "city": record.city,
        "listing_status": record.listing_status,
        "company_stage": record.company_stage,
        "financing_stage": record.financing_stage,
        "source_status": record.source_status,
        "source_id": record.source_id,
        "version": record.version,
        "description": record.description,
        "updated_at": record.updated_at,
        "is_archived": record.is_archived,
    }


def duplicates(db: Session, record: Company) -> dict:
    names = {
        record.normalized_name,
        *db.scalars(
            select(CompanyAlias.normalized_name).where(CompanyAlias.company_id == record.id)
        ).all(),
    }
    exact = [
        Company.normalized_name.in_(names),
        Company.id.in_(
            select(CompanyAlias.company_id).where(CompanyAlias.normalized_name.in_(names))
        ),
    ]
    if record.unified_social_credit_code:
        exact.append(Company.unified_social_credit_code == record.unified_social_credit_code)
    if record.website_domain:
        exact.append(Company.website_domain == record.website_domain)
    if record.registration_name:
        exact.append(func.lower(Company.registration_name) == record.registration_name.lower())
    base = select(Company).where(
        Company.id != record.id, Company.is_archived.is_(False), Company.merged_into_id.is_(None)
    )
    strong = db.scalars(base.where(or_(*exact)).limit(1001)).all()
    recent = db.scalars(base.order_by(Company.updated_at.desc()).limit(1001)).all()
    candidates = {c.id: c for c in [*strong[:1000], *recent[:1000]]}
    candidate_aliases = defaultdict(set)
    for alias in db.scalars(select(CompanyAlias).where(CompanyAlias.company_id.in_(candidates))):
        candidate_aliases[alias.company_id].add(alias.normalized_name)
    results = []
    for candidate in candidates.values():
        reasons = []
        if (
            record.unified_social_credit_code
            and record.unified_social_credit_code == candidate.unified_social_credit_code
        ):
            reasons.append("统一社会信用代码相同")
        if (
            record.registration_name
            and candidate.registration_name
            and normalize(record.registration_name) == normalize(candidate.registration_name)
        ):
            reasons.append("登记名称相同")
        if record.website_domain and record.website_domain == candidate.website_domain:
            reasons.append("官网域名相同")
        if record.normalized_name == candidate.normalized_name:
            reasons.append("标准名称相同（不能仅据此合并）")
        elif names & (candidate_aliases[candidate.id] | {candidate.normalized_name}):
            reasons.append("标准名称或历史别名匹配，需核实")
        elif (
            difflib.SequenceMatcher(None, record.normalized_name, candidate.normalized_name).ratio()
            >= 0.72
        ):
            reasons.append("名称相似，仅供人工核实")
        if reasons:
            results.append({**summary(db, candidate), "reasons": reasons})
    return {
        "items": sorted(results, key=lambda item: -len(item["reasons"])),
        "scanned": len(candidates),
        "truncated": len(strong) > 1000 or len(recent) > 1000,
        "automatic_merge": False,
    }


def parse_intent(
    db: Session, query: str, explicit: SearchFilters
) -> tuple[SearchFilters, list[str]]:
    if any(word in query for word in ["排除", "不在", "不包含", "以外", "或者", "或是"]):
        raise HTTPException(
            422,
            detail={
                "code": "UNSUPPORTED_SEARCH_CONDITION",
                "message": "暂不支持自然语言排除或组合条件，请使用结构化筛选",
            },
        )
    values = explicit.model_dump(exclude_unset=True)
    matched = []
    if "中国" in query:
        values.setdefault("country", "中国")
        matched.append("国家：中国")
    for item in db.scalars(select(Technology)).all():
        if any(normalize(term) in normalize(query) for term in [item.name, *item.aliases]):
            values.setdefault("technology_id", item.id)
            matched.append("技术：" + item.name)
            break
    for item in db.scalars(select(IndustryNode).order_by(IndustryNode.level.desc())).all():
        if item.name in query:
            values.setdefault("industry_id", item.id)
            matched.append("产业：" + item.name)
            break
    for word, status in [("未上市", "unlisted"), ("已上市", "listed"), ("退市", "delisted")]:
        if word in query:
            values.setdefault("listing_status", status)
            matched.append("上市状态：" + word)
            break
    for place in ["北京", "上海", "江苏", "浙江", "广东", "安徽", "湖北", "四川"]:
        if place in query:
            values.setdefault("province", place)
            matched.append("地域：" + place)
            break
    for place in ["深圳", "苏州", "合肥", "武汉", "杭州", "成都", "西安", "无锡", "南京"]:
        if place in query:
            values.setdefault("city", place)
            matched.append("城市：" + place)
            break
    for word, stage in [("中试", "pilot"), ("量产", "scaled"), ("商业化", "commercial")]:
        if word in query:
            values.setdefault("company_stage", stage)
            matched.append("档案阶段：" + word)
            break
    if not matched:
        values.setdefault("q", query)
    return SearchFilters.model_validate(values), matched
