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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import now


class TaskRun(Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("requested_by", "idempotency_key", name="uq_agent_idempotency"),
        Index("ix_agent_task_scope", "organization_id", "project_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    requested_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(40))
    inputs: Mapped[dict] = mapped_column(JSON)
    input_digest: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    prompt_version: Mapped[str] = mapped_column(String(80))
    prompt_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(50))
    evidence_refs: Mapped[list] = mapped_column(JSON, default=list)
    result: Mapped[dict | None] = mapped_column(JSON)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt", name="uq_model_call_attempt"),
        Index("ix_model_usage_org_date", "organization_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("agent_tasks.id", ondelete="CASCADE"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    attempt: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="reserved")
    reserved_tokens: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_micros: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
