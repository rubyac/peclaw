import base64
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.identity import InputModel

Listing = Literal["listed", "unlisted", "delisted", "unknown"]
Stage = Literal["research", "prototype", "pilot", "commercial", "scaled", "unknown"]
Financing = Literal["seed", "angel", "A", "B", "C", "pre_ipo", "other", "unknown"]
Verification = Literal["unverified", "verified", "conflicting", "rejected"]


def safe_url(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Only HTTP(S) URLs without credentials are allowed")
    return value


class SourceInput(InputModel):
    source_name: str = Field(min_length=1, max_length=200)
    source_type: Literal["official", "announcement", "patent", "licensed_api", "manual"]
    source_url: str | None = Field(default=None, max_length=2000)
    publisher: str | None = Field(default=None, max_length=200)
    license_type: Literal["authorized", "public_licensed", "synthetic_demo"]
    permitted_use: str = Field(min_length=5, max_length=3000)
    reliability_level: Literal["primary", "secondary", "unknown"] = "unknown"
    public_confirmed: Literal[True]
    published_at: AwareDatetime | None = None
    content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    _url = field_validator("source_url")(safe_url)

    @model_validator(mode="after")
    def attribution(self):
        if not self.source_name.strip() or not self.permitted_use.strip():
            raise ValueError("Attribution and permitted use required")
        if self.license_type != "synthetic_demo" and not self.source_url:
            raise ValueError("A public source locator is required")
        return self


class CompanyFields(InputModel):
    canonical_name: str = Field(min_length=1, max_length=200)
    registration_name: str | None = Field(default=None, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    unified_social_credit_code: str | None = Field(
        default=None, pattern=r"^[0-9A-HJ-NPQRTUWXY]{18}$"
    )
    country: str = Field(default="unknown", min_length=1, max_length=80)
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=10000)
    founded_on: date | None = None
    listing_status: Listing = "unknown"
    company_stage: Stage = "unknown"
    financing_stage: Financing = "unknown"
    industry_ids: list[UUID] = Field(default_factory=list, max_length=20)

    _url = field_validator("website")(safe_url)

    @field_validator("canonical_name", "country")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must not be blank")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def alias_lengths(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 200 for value in values):
            raise ValueError("Aliases must be nonempty and at most 200 characters")
        return list(dict.fromkeys(value.strip() for value in values))


class Provenance(InputModel):
    source_id: UUID
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_required(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("Meaningful change reason required")
        return value.strip()


class CompanyCreate(CompanyFields, Provenance):
    pass


class CompanyUpdate(CompanyCreate):
    expected_version: int = Field(ge=1)


class ArchiveInput(Provenance):
    expected_version: int = Field(ge=1)
    archived: bool = True


class TaxonomyInput(InputModel):
    name: str = Field(min_length=1, max_length=100)
    parent_id: UUID | None = None
    description: str = Field(default="", max_length=2000)
    aliases: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Empty taxonomy name")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def short_aliases(cls, values: list[str]) -> list[str]:
        if any(not v.strip() or len(v) > 100 for v in values):
            raise ValueError("Invalid taxonomy alias")
        return values


class EvidenceInput(InputModel):
    source_id: UUID
    claim_text: str = Field(min_length=3, max_length=5000)
    excerpt: str = Field(min_length=3, max_length=10000)
    field_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,79}$")
    field_value: str | None = Field(default=None, max_length=500)
    classification: Literal["fact", "inference", "unverified", "unknown", "conflicting"] = (
        "unverified"
    )
    verification_status: Verification = "unverified"
    page_number: int | None = Field(default=None, ge=1)
    section_name: str | None = Field(default=None, max_length=200)

    @field_validator("claim_text", "excerpt")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        if len(value.strip()) < 3:
            raise ValueError("Meaningful source text required")
        return value.strip()

    @model_validator(mode="after")
    def value_has_field(self):
        if self.field_value is not None and self.field_name is None:
            raise ValueError("A structured value needs a field name")
        if self.classification == "inference" and self.verification_status == "verified":
            raise ValueError("An inference cannot be verified as a source fact")
        return self


class EvidenceReview(InputModel):
    verification_status: Verification
    reason: str = Field(min_length=3, max_length=1000)


class TechnologyLink(InputModel):
    technology_id: UUID
    evidence_id: UUID
    relation_type: Literal[
        "develops", "manufactures", "licenses", "uses", "researches", "announced"
    ]


class ProductInput(InputModel):
    name: str = Field(min_length=1, max_length=200)
    product_category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    technical_route: str = Field(default="", max_length=200)
    commercialization_stage: Stage = "unknown"
    source_id: UUID
    evidence_id: UUID


class SearchFilters(InputModel):
    country: str | None = Field(default=None, max_length=80)
    q: str | None = Field(default=None, max_length=300)
    industry_id: UUID | None = None
    technology_id: UUID | None = None
    province: str | None = Field(default=None, max_length=80)
    city: str | None = Field(default=None, max_length=80)
    listing_status: Listing | None = None
    company_stage: Stage | None = None
    financing_stage: Financing | None = None
    source_id: UUID | None = None
    updated_since: AwareDatetime | None = None
    founded_after: date | None = None
    founded_before: date | None = None
    include_archived: bool = False
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class NaturalSearch(InputModel):
    query: str = Field(min_length=1, max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class MergeInput(Provenance):
    duplicate_id: UUID
    expected_target_version: int = Field(ge=1)
    expected_duplicate_version: int = Field(ge=1)
    confirm: Literal[True]


class UndoMergeInput(Provenance):
    expected_target_version: int = Field(ge=1)
    expected_duplicate_version: int = Field(ge=1)


class ImportInput(Provenance):
    format: Literal["csv", "xlsx"]
    content_base64: str = Field(min_length=1, max_length=1400000)
    idempotency_key: UUID
    public_confirmed: Literal[True]

    @field_validator("content_base64")
    @classmethod
    def bounded_file(cls, value: str) -> str:
        try:
            decoded = base64.b64decode(value, validate=True)
        except (ValueError, base64.binascii.Error):
            raise ValueError("Invalid base64") from None
        if len(decoded) > 1024 * 1024:
            raise ValueError("File exceeds 1 MiB")
        return value


# Public API DTOs intentionally enumerate fields; ORM columns are not an API contract.


class SourceOutput(BaseModel):
    id: UUID
    source_name: str
    source_type: str
    source_url: str | None
    publisher: str | None
    license_type: str
    permitted_use: str
    reliability_level: str
    published_at: datetime | None
    accessed_at: datetime
    content_hash: str | None


class EvidenceOutput(EvidenceInput):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    company_id: UUID
    reviewer_id: UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class ProductOutput(ProductInput):
    model_config = ConfigDict(extra="ignore")
    id: UUID
    company_id: UUID
    verification_status: Verification = "unverified"


class CompanySummaryOutput(BaseModel):
    id: UUID
    canonical_name: str
    province: str | None
    city: str | None
    listing_status: Listing
    company_stage: Stage
    financing_stage: Financing
    source_status: str
    source_id: UUID
    version: int
    description: str | None
    updated_at: datetime
    is_archived: bool


class CompanyOutput(CompanySummaryOutput):
    registration_name: str | None
    unified_social_credit_code: str | None
    country: str
    website: str | None
    founded_on: date | None
    aliases: list[str]
    industry_ids: list[UUID]
    merged_into_id: UUID | None
    created_at: datetime
    industries: list[dict]
    related_records: list[dict]
    sources: list[SourceOutput]
    evidence: list[EvidenceOutput]
    products: list[ProductOutput]
    technologies: list[dict]
    conflicts: list[dict]
    merges: list[dict]


class SearchOutput(BaseModel):
    items: list[CompanySummaryOutput]
    total: int
    limit: int
    offset: int


class NaturalSearchOutput(SearchOutput):
    applied_filters: SearchFilters
    matched_intent: list[str]
    unparsed_criteria: list[str]
    limitations: str


class ImportOutput(BaseModel):
    id: UUID
    source_id: UUID
    state: Literal["queued", "running", "completed", "failed"]
    attempts: int
    result: dict
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
