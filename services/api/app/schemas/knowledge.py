import base64
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.identity import InputModel


class FileInput(InputModel):
    filename: str = Field(min_length=1, max_length=180)
    content_base64: str = Field(min_length=1, max_length=14000000)
    idempotency_key: UUID

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if (
            "/" in value
            or "\\" in value
            or any(ord(c) < 32 for c in value)
            or value.startswith(".")
            or not re.search(r"\.(pdf|docx|xlsx|pptx|txt|md)$", value, re.I)
        ):
            raise ValueError("Unsupported or unsafe filename")
        return value

    @field_validator("content_base64")
    @classmethod
    def valid_base64(cls, value: str) -> str:
        try:
            raw = base64.b64decode(value, validate=True)
        except (ValueError, base64.binascii.Error):
            raise ValueError("Invalid file encoding") from None
        if not raw or len(raw) > 10 * 1024 * 1024:
            raise ValueError("File must be 1 byte to 10 MiB")
        return value


class DocumentInput(FileInput):
    title: str = Field(min_length=1, max_length=200)
    access_scope: Literal["project", "restricted"] = "project"
    reader_ids: list[UUID] = Field(default_factory=list, max_length=100)

    @field_validator("title")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if not value.strip() or chr(0) in value:
            raise ValueError("Invalid title")
        return value.strip()


class VersionInput(FileInput):
    expected_revision: int = Field(ge=1)


class RevisionInput(InputModel):
    expected_revision: int = Field(ge=1)


class GrantInput(InputModel):
    user_id: UUID
    role: Literal["reader", "editor"]


class PermissionInput(RevisionInput):
    access_scope: Literal["project", "restricted"]
    grants: list[GrantInput] = Field(default_factory=list, max_length=100)


class KnowledgeQuery(InputModel):
    query: str = Field(min_length=1, max_length=500)
    project_id: UUID | None = None
    mode: Literal["hybrid", "keyword", "semantic"] = "hybrid"
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip() or chr(0) in value:
            raise ValueError("Invalid search text")
        return value.strip()


class VersionOutput(BaseModel):
    id: UUID
    number: int
    filename: str
    file_format: str
    byte_size: int
    content_hash: str
    status: str
    attempts: int
    error_code: str | None
    chunk_count: int
    created_at: datetime
    finished_at: datetime | None


class DocumentOutput(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    title: str
    current_version: int
    revision: int
    access_scope: str
    is_deleted: bool
    can_read: bool
    can_write: bool
    can_manage: bool
    current: VersionOutput | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOutput):
    versions: list[VersionOutput]


class CitationOutput(BaseModel):
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    version_number: int
    document_title: str
    project_id: UUID
    excerpt: str
    content_hash: str
    file_hash: str
    page_number: int | None
    section_name: str | None
    locator: dict
    start_offset: int
    end_offset: int
    matched_by: list[str] = Field(default_factory=list)


class KnowledgeResults(BaseModel):
    items: list[CitationOutput]
    mode: str
    semantic_available: bool
    limitations: str
