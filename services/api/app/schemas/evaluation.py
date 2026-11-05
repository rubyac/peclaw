from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.catalog import SearchFilters
from app.schemas.identity import InputModel


class CompanyJudgment(InputModel):
    company_id: UUID
    grade: int = Field(ge=0, le=3)


class DocumentJudgment(InputModel):
    document_id: UUID
    grade: int = Field(ge=0, le=3)


class SearchCase(InputModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["company_search"]
    filters: SearchFilters = Field(default_factory=SearchFilters)
    k: int = Field(default=10, ge=1, le=20)
    relevance: list[CompanyJudgment] = Field(min_length=1, max_length=100)


class RetrievalCase(InputModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["knowledge_retrieval"]
    query: str = Field(min_length=1, max_length=500)
    mode: Literal["keyword", "semantic", "hybrid"] = "hybrid"
    k: int = Field(default=10, ge=1, le=20)
    relevance: list[DocumentJudgment] = Field(min_length=1, max_length=100)


class ExpectedClaim(InputModel):
    text: str = Field(min_length=1, max_length=1600)
    classification: Literal["fact", "inference", "unverified", "unknown", "conflicting"]


class TaskCase(InputModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["fact_extraction", "bp_screening"]
    task_id: UUID | None = None
    expected_claims: list[ExpectedClaim] = Field(min_length=1, max_length=100)


class ReportCase(InputModel):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    kind: Literal["report_quality"]
    report_id: UUID
    expected_gate_passed: bool


Case = Annotated[SearchCase | RetrievalCase | TaskCase | ReportCase, Field(discriminator="kind")]


class DatasetInput(InputModel):
    name: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1, le=100000)
    data_kind: Literal["synthetic", "authorized"]
    source_description: str = Field(min_length=5, max_length=3000)
    authorized_for_evaluation: Literal[True]
    reviewer_id: UUID | None = None
    idempotency_key: UUID
    cases: list[Case] = Field(min_length=1, max_length=20)

    @field_validator("name", "source_description")
    @classmethod
    def meaningful(cls, value):
        if not value.strip() or chr(0) in value:
            raise ValueError("Meaningful text required")
        return value.strip()

    @model_validator(mode="after")
    def unique_labels(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case IDs")
        for case in self.cases:
            if isinstance(case, (SearchCase, RetrievalCase)):
                ids = [
                    str(item.company_id if isinstance(item, CompanyJudgment) else item.document_id)
                    for item in case.relevance
                ]
                if len(ids) != len(set(ids)):
                    raise ValueError("Duplicate relevance judgments")
        if len(self.model_dump_json().encode()) > 1024 * 1024:
            raise ValueError("Dataset exceeds one MiB")
        return self


class RunInput(InputModel):
    idempotency_key: UUID


class ClaimJudgment(InputModel):
    index: int = Field(ge=0, le=199)
    correct: bool


class FeedbackInput(InputModel):
    case_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    result_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    usable: bool | None = None
    numeric_correct: bool | None = None
    claim_judgments: list[ClaimJudgment] = Field(default_factory=list, max_length=200)
    category: Literal[
        "relevance",
        "citation",
        "fact",
        "number",
        "unknown",
        "conflict",
        "usability",
        "access",
        "latency",
        "other",
    ]
    severity: Literal["low", "medium", "high"]
    notes: str = Field(min_length=5, max_length=3000)

    @model_validator(mode="after")
    def unique_claims(self):
        if len({c.index for c in self.claim_judgments}) != len(self.claim_judgments):
            raise ValueError("Duplicate claim ratings")
        if not self.notes.strip() or chr(0) in self.notes:
            raise ValueError("Feedback required")
        return self
