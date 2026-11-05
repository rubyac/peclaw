from pathlib import Path

import boto3
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from botocore.config import Config
from botocore.session import Session
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_engine


def storage_client():
    settings = get_settings()
    # This client uses explicit S3-compatible endpoint credentials, not ambient AWS identity.
    # Keep process-level platform authentication and profile guard variables unchanged.
    session = Session()
    session.get_component("config_store").set_config_variable("profile", None)
    return boto3.Session(botocore_session=session).client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        region_name=settings.s3_region,
        config=Config(
            connect_timeout=2,
            read_timeout=2,
            retries={"max_attempts": 0},
            s3={"addressing_style": "path"},
        ),
    )


def check_database() -> None:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))
        # Compare against the actual migration head, not a hardcoded historical revision.
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        migration_config = AlembicConfig()
        migration_config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[2] / "alembic")
        )
        if revision != ScriptDirectory.from_config(migration_config).get_current_head():
            raise RuntimeError("Database migration is not current")
        if not connection.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        ).scalar():
            raise RuntimeError("pgvector extension missing")


def check_redis() -> None:
    with Redis.from_url(
        get_settings().redis_url.get_secret_value(), socket_connect_timeout=2, socket_timeout=2
    ) as client:
        if not client.ping():
            raise RuntimeError("Redis unavailable")


def check_storage() -> None:
    storage_client().head_bucket(Bucket=get_settings().s3_bucket)


def dependency_checks() -> dict[str, str]:
    checks = {}
    for name, check in (
        ("database", check_database),
        ("redis", check_redis),
        ("object_storage", check_storage),
    ):
        try:
            check()
            checks[name] = "ok"
        except Exception:
            # Never expose endpoints, passwords, bucket names or driver error messages.
            checks[name] = "error"
    return checks
