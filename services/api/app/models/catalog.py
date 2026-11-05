from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import now


class DataSource(Base):
    __tablename__ = "data_sources"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_name: Mapped[str] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(30))
    source_url: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(200))
    license_type: Mapped[str] = mapped_column(String(40))
    permitted_use: Mapped[str] = mapped_column(Text)
    reliability_level: Mapped[str] = mapped_column(String(20))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    public_confirmed: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "listing_status IN ('listed','unlisted','delisted','unknown')",
            name="ck_company_listing",
        ),
        Index("ix_company_region_status", "province", "city", "listing_status"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    canonical_name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)
    registration_name: Mapped[str | None] = mapped_column(String(200))
    unified_social_credit_code: Mapped[str | None] = mapped_column(String(18), index=True)
    country: Mapped[str] = mapped_column(String(80), default="unknown")
    province: Mapped[str | None] = mapped_column(String(80))
    city: Mapped[str | None] = mapped_column(String(80))
    website: Mapped[str | None] = mapped_column(Text)
    website_domain: Mapped[str | None] = mapped_column(String(253), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    founded_on: Mapped[date | None] = mapped_column(Date)
    listing_status: Mapped[str] = mapped_column(String(20), default="unknown")
    company_stage: Mapped[str] = mapped_column(String(30), default="unknown")
    financing_stage: Mapped[str] = mapped_column(String(30), default="unknown")
    source_status: Mapped[str] = mapped_column(String(20), default="unverified")
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    merged_into_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompanyAlias(Base):
    __tablename__ = "company_aliases"
    __table_args__ = (UniqueConstraint("company_id", "normalized_name", name="uq_company_alias"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200), index=True)


class IndustryNode(Base):
    __tablename__ = "industry_nodes"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("industry_nodes.id"))
    level: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(Text, default="")


class Technology(Base):
    __tablename__ = "technologies"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey("technologies.id"))
    description: Mapped[str] = mapped_column(Text, default="")
    aliases: Mapped[list] = mapped_column(JSON, default=list)


class CompanyIndustry(Base):
    __tablename__ = "company_industries"
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True
    )
    industry_id: Mapped[UUID] = mapped_column(ForeignKey("industry_nodes.id"), primary_key=True)


class Evidence(Base):
    __tablename__ = "evidence_records"
    __table_args__ = (Index("ix_evidence_company_field", "company_id", "field_name"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"))
    claim_text: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    field_name: Mapped[str | None] = mapped_column(String(80))
    field_value: Mapped[str | None] = mapped_column(String(500))
    classification: Mapped[str] = mapped_column(String(20), default="unverified")
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified")
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(200))
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompanyTechnology(Base):
    __tablename__ = "company_technologies"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "technology_id", "relation_type", name="uq_company_technology_relation"
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    technology_id: Mapped[UUID] = mapped_column(ForeignKey("technologies.id"))
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_records.id"))
    relation_type: Mapped[str] = mapped_column(String(20))


class Product(Base):
    __tablename__ = "products"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    product_category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    technical_route: Mapped[str] = mapped_column(String(200), default="")
    commercialization_stage: Mapped[str] = mapped_column(String(30), default="unknown")
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"))
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey("evidence_records.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompanyChange(Base):
    __tablename__ = "company_changes"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"))
    action: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(1000))
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    import_fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class CompanyMerge(Base):
    __tablename__ = "company_merges"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    target_id: Mapped[UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    duplicate_id: Mapped[UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reason: Mapped[str] = mapped_column(String(1000))
    snapshots: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reverted_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revert_reason: Mapped[str | None] = mapped_column(String(1000))


class CatalogImport(Base):
    __tablename__ = "catalog_imports"
    __table_args__ = (
        UniqueConstraint("requested_by", "idempotency_key", name="uq_catalog_import_key"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("data_sources.id"))
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    input_digest: Mapped[str] = mapped_column(String(64))
    input_payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
