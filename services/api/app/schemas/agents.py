from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.schemas.catalog import SearchFilters
from app.schemas.identity import InputModel

Kind = Literal[
    "company_discovery", "company_profile", "project_match", "bp_screening", "due_diligence"
]


class TaskInput(InputModel):
    kind: Kind
    idempotency_key: UUID
    question: str = Field(min_length=3, max_length=2000)
    company_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)
    thesis: str = Field(default="", max_length=3000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    allow_private_to_model: bool = False

    @model_validator(mode="after")
    def relevant_fields(self):
        if not self.question.strip() or chr(0) in self.question or chr(0) in self.thesis:
            raise ValueError("Meaningful question required")
        if self.kind in {"company_profile", "project_match"} and not self.company_id:
            raise ValueError("Company required")
        if self.kind == "project_match" and not self.thesis.strip():
            raise ValueError("Investment thesis required")
        if self.kind == "bp_screening" and not self.document_ids:
            raise ValueError("BP documents required")
        if self.document_ids and not self.allow_private_to_model:
            raise ValueError("Explicit private document consent required")
        if self.kind == "company_discovery" and (self.company_id or self.document_ids):
            raise ValueError("Discovery uses public database filters")
        self.document_ids = list(dict.fromkeys(self.document_ids))
        return self


class Claim(InputModel):
    text: str = Field(min_length=1, max_length=1600)
    classification: Literal["fact", "inference", "unverified", "unknown", "conflicting"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class Section(InputModel):
    key: str = Field(min_length=1, max_length=50)
    claims: list[Claim] = Field(min_length=1, max_length=12)


class DiligenceQuestion(InputModel):
    question: str = Field(min_length=3, max_length=800)
    reason: str = Field(min_length=3, max_length=800)
    risk: str = Field(min_length=1, max_length=800)
    known_information: str = Field(min_length=1, max_length=800)
    missing_evidence: str = Field(min_length=1, max_length=800)
    verification_method: str = Field(min_length=3, max_length=800)
    priority: Literal["high", "medium", "low"]
    evidence_ids: list[str] = Field(default_factory=list, max_length=20)


class AgentResult(InputModel):
    workflow: Kind
    summary: Claim
    candidate_ids: list[UUID] = Field(default_factory=list, max_length=20)
    sections: list[Section] = Field(min_length=1, max_length=15)
    questions: list[DiligenceQuestion] = Field(default_factory=list, max_length=30)
    unknowns: list[str] = Field(min_length=1, max_length=30)
    limitations: list[str] = Field(min_length=1, max_length=15)


class TaskRevision(InputModel):
    expected_attempts: int = Field(ge=0, le=3)
