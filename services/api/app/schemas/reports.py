from decimal import Decimal, InvalidOperation
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.schemas.agents import AgentResult, Kind
from app.schemas.identity import InputModel

MetricType = Literal[
    "revenue",
    "gross_margin",
    "shipment_volume",
    "capacity",
    "market_size",
    "financing_amount",
    "valuation",
    "customer_count",
    "market_share",
    "other",
]


class ReportInput(InputModel):
    @model_validator(mode="after")
    def safe_text(self):
        def inspect(value):
            if isinstance(value, str) and any(ord(c) < 32 and c not in "\n\r\t" for c in value):
                raise ValueError("Invalid control character")
            if isinstance(value, dict):
                for item in value.values():
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)

        inspect(self.model_dump())
        return self


class CreateReport(ReportInput):
    title: str = Field(min_length=1, max_length=200)
    template: Kind = "bp_screening"
    company_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)
    source_task_id: UUID | None = None
    idempotency_key: UUID

    @field_validator("title")
    @classmethod
    def valid_title(cls, value):
        if not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError("Meaningful plain title required")
        return value.strip()

    @model_validator(mode="after")
    def source_mode(self):
        if self.source_task_id and (self.company_id or self.document_ids):
            raise ValueError("Choose task or manual sources")
        return self


class RevisionInput(ReportInput):
    expected_revision: int = Field(ge=1)


class UpdateReport(RevisionInput):
    title: str = Field(min_length=1, max_length=200)
    content: AgentResult
    _title = field_validator("title")(CreateReport.valid_title.__func__)

    @model_validator(mode="after")
    def size(self):
        if len(self.content.model_dump_json()) > 200000:
            raise ValueError("Report content too large")
        if chr(0) in self.content.model_dump_json():
            raise ValueError("Invalid content")
        return self


class AssignReviewer(RevisionInput):
    reviewer_id: UUID


class MetricInput(RevisionInput):
    metric_name: str = Field(min_length=1, max_length=200)
    metric_type: MetricType
    metric_value: str | None = Field(default=None, max_length=100)
    unit: str = Field(min_length=1, max_length=40)
    currency: Literal["CNY", "USD", "EUR", "HKD", "JPY", "other"] | None = None
    period: str = Field(min_length=1, max_length=100)
    evidence_id: str | None = Field(default=None, max_length=80)
    source_quote: str = Field(default="", max_length=2000)
    notes: str = Field(default="", max_length=2000)

    @field_validator("metric_value")
    @classmethod
    def precise_decimal(cls, value):
        if value is None:
            return value
        try:
            number = Decimal(value)
            if (
                not number.is_finite()
                or abs(number) >= Decimal("1e24")
                or (number.as_tuple().exponent < -8 or number.as_tuple().exponent > 24)
            ):
                raise ValueError("Finite bounded decimal required")
        except InvalidOperation:
            raise ValueError("Decimal required") from None
        return format(number, "f")

    @model_validator(mode="after")
    def source_fields(self):
        if any(not getattr(self, key).strip() for key in ["metric_name", "unit", "period"]):
            raise ValueError("Explicit name/unit/period required")
        if self.metric_value is not None and (
            not self.evidence_id or not self.source_quote.strip()
        ):
            raise ValueError("Numeric metric needs an exact evidence quote")
        if (
            self.metric_type in {"revenue", "market_size", "financing_amount", "valuation"}
            and self.metric_value is not None
            and not self.currency
        ):
            raise ValueError("Monetary metrics require currency")
        return self


class MetricReview(RevisionInput):
    status: Literal["verified", "conflicting", "rejected", "not_applicable"]
    notes: str = Field(min_length=5, max_length=2000)


class ReviewInput(RevisionInput):
    decision: Literal["approve", "request_changes"]
    notes: str = Field(min_length=5, max_length=4000)
    citations_checked: bool = False
    facts_checked: bool = False
    numeric_registry_complete: bool = False
    conflicts_checked: bool = False
    no_invented_data: bool = False

    @model_validator(mode="after")
    def affirmative_approval(self):
        if self.decision == "approve" and not all(
            [
                self.citations_checked,
                self.facts_checked,
                self.numeric_registry_complete,
                self.conflicts_checked,
                self.no_invented_data,
            ]
        ):
            raise ValueError("All manual checks must be confirmed")
        return self


class ExportInput(RevisionInput):
    mode: Literal["draft", "formal"]
    format: Literal["md", "docx"]
    idempotency_key: UUID
