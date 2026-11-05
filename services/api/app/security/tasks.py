from collections.abc import Iterator
from contextlib import contextmanager
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.models.identity import Project, User
from app.security.dependencies import project_access


class TaskContext(BaseModel):
    """Serialize only trusted identifiers; never tokens, credentials or document content."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    actor_id: UUID
    organization_id: UUID
    project_id: UUID


def capture_context(
    db: Session, actor: User, organization_id: UUID, project_id: UUID
) -> TaskContext:
    project_access(db, actor, organization_id, project_id)
    return TaskContext(actor_id=actor.id, organization_id=organization_id, project_id=project_id)


@contextmanager
def authorized_task(context: TaskContext) -> Iterator[tuple[Session, Project]]:
    # An internal worker must load context from its server-owned task record, never caller JSON.
    # Recheck current permissions: removal after enqueue must take effect before execution.
    with Session(get_engine()) as db:
        actor = db.get(User, context.actor_id)
        if not actor or not actor.is_active:
            raise HTTPException(401)
        project = project_access(db, actor, context.organization_id, context.project_id)
        yield db, project
