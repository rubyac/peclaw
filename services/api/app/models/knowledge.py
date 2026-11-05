from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
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
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.identity import now


class PrivateDocument(Base):
    __tablename__ = "private_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "organization_id"],
            ["projects.id", "projects.organization_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "organization_id", "project_id", name="uq_private_document_scope"),
        Index("ix_private_document_scope", "organization_id", "project_id"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    access_scope: Mapped[str] = mapped_column(String(20), default="project")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class DocumentGrant(Base):
    __tablename__ = "private_document_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id", "project_id"],
            [
                "private_documents.id",
                "private_documents.organization_id",
                "private_documents.project_id",
            ],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["project_memberships.project_id", "project_memberships.user_id"],
            ondelete="CASCADE",
        ),
    )
    document_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(20))


class DocumentVersion(Base):
    __tablename__ = "private_document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id", "project_id"],
            [
                "private_documents.id",
                "private_documents.organization_id",
                "private_documents.project_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("document_id", "number", name="uq_private_document_version"),
        UniqueConstraint("uploaded_by", "idempotency_key", name="uq_private_upload_key"),
        UniqueConstraint(
            "id", "document_id", "organization_id", "project_id", name="uq_private_version_scope"
        ),
        Index("ix_private_version_work", "status", "lease_until"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    document_id: Mapped[UUID] = mapped_column(Uuid)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    number: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(180))
    file_format: Mapped[str] = mapped_column(String(10))
    byte_size: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str | None] = mapped_column(String(250))
    uploaded_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[UUID] = mapped_column(Uuid)
    input_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="uploading")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    delete_attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    claim_token: Mapped[UUID | None] = mapped_column(Uuid)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(Base):
    __tablename__ = "private_document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "document_id", "organization_id", "project_id"],
            [
                "private_document_versions.id",
                "private_document_versions.document_id",
                "private_document_versions.organization_id",
                "private_document_versions.project_id",
            ],
            ondelete="CASCADE",
        ),
        UniqueConstraint("version_id", "chunk_index", name="uq_private_chunk_index"),
        Index("ix_private_chunk_scope", "organization_id", "project_id", "document_id"),
        Index("ix_private_chunk_fts", "search_vector", postgresql_using="gin"),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    version_id: Mapped[UUID] = mapped_column(Uuid)
    document_id: Mapped[UUID] = mapped_column(Uuid)
    organization_id: Mapped[UUID] = mapped_column(Uuid)
    project_id: Mapped[UUID] = mapped_column(Uuid)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(200))
    locator: Mapped[dict] = mapped_column(JSON)
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(300))
    embedding_model: Mapped[str] = mapped_column(String(80))
    search_vector: Mapped[str] = mapped_column(TSVECTOR)
