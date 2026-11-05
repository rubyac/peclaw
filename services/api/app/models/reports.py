from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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


class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_report_scope"),
        UniqueConstraint("created_by", "idempotency_key", name="uq_report_idempotency"),
        Index("ix_report_scope", "organization_id", "project_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source_task_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("agent_tasks.id", ondelete="SET NULL")
    )
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    input_digest: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    template_version: Mapped[str] = mapped_column(String(80))
    content: Mapped[dict] = mapped_column(JSON)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    approved_revision: Mapped[int | None] = mapped_column(Integer)
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class KeyMetric(Base):
    __tablename__ = "key_metrics"
    __table_args__ = (
        ForeignKeyConstraint(
            ["report_id", "organization_id", "project_id"],
            ["reports.id", "reports.organization_id", "reports.project_id"],
            ondelete="CASCADE",
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    metric_name: Mapped[str] = mapped_column(String(200))
    metric_type: Mapped[str] = mapped_column(String(40))
    metric_value: Mapped[str | None] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(12))
    period: Mapped[str] = mapped_column(String(100))
    evidence_id: Mapped[str | None] = mapped_column(String(80))
    source_quote: Mapped[str] = mapped_column(Text, default="")
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified")
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str] = mapped_column(Text, default="")
    review_notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReportReview(Base):
    __tablename__ = "report_reviews"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision: Mapped[str] = mapped_column(String(40))
    content_hash: Mapped[str] = mapped_column(String(64))
    notes: Mapped[str] = mapped_column(Text)
    confirmations: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ReportExport(Base):
    __tablename__ = "report_exports"
    __table_args__ = (
        UniqueConstraint("requested_by", "idempotency_key", name="uq_report_export_idempotency"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("reports.id", ondelete="CASCADE"), index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    project_id: Mapped[UUID] = mapped_column(Uuid)
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    input_digest: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(12))
    format: Mapped[str] = mapped_column(String(12))
    content_hash: Mapped[str] = mapped_column(String(64))
    file_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
