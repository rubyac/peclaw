import json

from pydantic import ValidationError

from app.agents.gateway import ModelError
from app.agents.prompts import SECTION_KEYS
from app.schemas.agents import AgentResult


def validate_result(content: str, context: dict) -> dict:
    try:
        value = AgentResult.model_validate_json(content)
    except (ValidationError, ValueError):
        raise ModelError("OUTPUT_SCHEMA_INVALID") from None
    kind = context["workflow"]
    if value.workflow != kind or sorted(s.key for s in value.sections) != sorted(
        SECTION_KEYS[kind]
    ):
        raise ModelError("OUTPUT_SCHEMA_INVALID")
    candidates = {str(x) for x in value.candidate_ids}
    if not candidates.issubset(set(context["candidate_company_ids"])):
        raise ModelError("OUTPUT_REFERENCE_INVALID")
    if kind == "company_discovery" and context["candidate_company_ids"] and not candidates:
        raise ModelError("OUTPUT_REFERENCE_INVALID")
    if kind == "due_diligence" and not value.questions:
        raise ModelError("OUTPUT_SCHEMA_INVALID")
    evidence = {e["id"]: e for e in context["evidence"]}
    claims = [value.summary, *[c for section in value.sections for c in section.claims]]
    for claim in claims:
        if not set(claim.evidence_ids).issubset(evidence):
            raise ModelError("OUTPUT_REFERENCE_INVALID")
        if claim.classification != "unknown" and not claim.evidence_ids:
            raise ModelError("OUTPUT_REFERENCE_MISSING")
        if claim.classification == "fact" and any(
            (
                evidence[key]["verification"] != "verified"
                or evidence[key].get("classification") != "fact"
            )
            for key in claim.evidence_ids
        ):
            raise ModelError("OUTPUT_FACT_UNVERIFIED")
    for question in value.questions:
        if not set(question.evidence_ids).issubset(evidence):
            raise ModelError("OUTPUT_REFERENCE_INVALID")
    # This validates attribution, never proves a claim's semantic or numeric truth.
    return json.loads(value.model_dump_json())
