from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
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


class EvaluationDataset(Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "project_id",
            "created_by",
            "name",
            "version",
            name="uq_eval_dataset_version",
        ),
        UniqueConstraint("created_by", "idempotency_key", name="uq_eval_dataset_key"),
        Index("ix_eval_dataset_scope", "organization_id", "project_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewer_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer)
    data_kind: Mapped[str] = mapped_column(String(20))
    source_description: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    content_hash: Mapped[str] = mapped_column(String(64))
    definition: Mapped[dict] = mapped_column(JSON)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    bindings: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (UniqueConstraint("requested_by", "idempotency_key", name="uq_eval_run_key"),)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), index=True
    )
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records: Mapped[list] = mapped_column(JSON, default=list)
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    result_hash: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(50))
    engine_version: Mapped[str] = mapped_column(String(40), default="evaluation@1.0.0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationFeedback(Base):
    __tablename__ = "evaluation_feedback"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), index=True
    )
    case_id: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    result_hash: Mapped[str] = mapped_column(String(64))
    independent: Mapped[bool] = mapped_column(Boolean)
    usable: Mapped[bool | None] = mapped_column(Boolean)
    numeric_correct: Mapped[bool | None] = mapped_column(Boolean)
    claim_judgments: Mapped[list] = mapped_column(JSON, default=list)
    category: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
