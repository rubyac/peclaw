from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_engine
from app.main import create_app
from app.services.dependencies import storage_client

pytestmark = pytest.mark.integration


def test_migrated_database_and_vector_operations():
    with get_engine().connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            "0009_eval_scope"
        )
        assert (
            connection.execute(text("SELECT '[1,2,3]'::vector <-> '[1,2,3]'::vector")).scalar() == 0
        )


def test_redis_roundtrip():
    key = f"peclaw:test:{uuid4()}"
    with Redis.from_url(get_settings().redis_url.get_secret_value()) as client:
        try:
            assert client.set(key, "roundtrip", ex=30)
            assert client.get(key) == b"roundtrip"
        finally:
            client.delete(key)


def test_object_storage_roundtrip():
    client = storage_client()
    bucket = get_settings().s3_bucket
    key = f"tests/{uuid4()}.txt"
    try:
        client.put_object(Bucket=bucket, Key=key, Body=b"peclaw-smoke")
        response = client.get_object(Bucket=bucket, Key=key)
        assert response["Body"].read() == b"peclaw-smoke"
        response["Body"].close()
    finally:
        client.delete_object(Bucket=bucket, Key=key)


def test_readiness_with_real_dependencies():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["checks"] == {
        "database": "ok",
        "redis": "ok",
        "object_storage": "ok",
    }
