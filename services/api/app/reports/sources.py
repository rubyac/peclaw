from sqlalchemy import select

from app.agents.evidence import resolve as resolve_agent_sources
from app.agents.gateway import ModelError
from app.models.knowledge import PrivateDocument


def resolve(db, user, org_id, project_id, refs):
    evidence = resolve_agent_sources(db, user, org_id, project_id, refs)
    # Reports bind approval to current source versions, not just still-readable history.
    for source in evidence:
        if source["kind"] == "private_chunk":
            version = db.scalar(
                select(PrivateDocument.current_version).where(
                    PrivateDocument.id == source["document_id"],
                    PrivateDocument.organization_id == org_id,
                    PrivateDocument.project_id == project_id,
                )
            )
            if version != source["version_number"]:
                raise ModelError("EVIDENCE_CHANGED")
    return evidence
