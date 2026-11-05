from fastapi import HTTPException
from sqlalchemy import select

from app.models.identity import Membership, User
from app.security.dependencies import Db, deny


def require_reader(db: Db, user: User) -> None:
    if user.is_data_curator:
        return
    member = db.scalar(
        select(Membership)
        .where(Membership.user_id == user.id, Membership.is_active.is_(True))
        .limit(1)
    )
    if not member:
        deny(db, user, "catalog.access", status=403)


def require_curator(db: Db, user: User) -> None:
    if not user.is_active or not user.is_data_curator:
        deny(db, user, "catalog.curate", status=403)


def conflict(message: str = "档案已变化，请重新加载后操作") -> None:
    raise HTTPException(409, detail={"code": "CATALOG_CONFLICT", "message": message})
