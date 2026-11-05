from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url.get_secret_value(),
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000"},
    )
