from uuid import UUID

from sqlalchemy.orm import Session

from app.models.identity import AuditLog


def audit(
    db: Session,
    actor_id: UUID | None,
    organization_id: UUID | None,
    action: str,
    resource_id: str | UUID | None = None,
    *,
    result: str = "success",
    request_id: str | None = None,
    details: dict | None = None,
) -> None:
    # Callers supply only controlled metadata: never passwords, tokens or request bodies.
    db.add(
        AuditLog(
            actor_id=actor_id,
            organization_id=organization_id,
            action=action,
            resource_id=str(resource_id) if resource_id else None,
            result=result,
            request_id=request_id or db.info.get("request_id"),
            details=details or {},
        )
    )
