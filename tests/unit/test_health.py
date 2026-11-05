from fastapi.testclient import TestClient

from app.main import create_app


def test_liveness_does_not_require_infrastructure():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["x-request-id"]


def test_readiness_success(monkeypatch):
    monkeypatch.setattr(
        "app.api.health.dependency_checks",
        lambda: {"database": "ok", "redis": "ok", "object_storage": "ok"},
    )
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_failure(monkeypatch):
    monkeypatch.setattr("app.api.health.dependency_checks", lambda: {"database": "error"})
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_all_dependency_checks_run_and_hide_errors(monkeypatch):
    from app.services.dependencies import dependency_checks

    def broken():
        raise RuntimeError("password=do-not-leak")

    monkeypatch.setattr("app.services.dependencies.check_database", broken)
    monkeypatch.setattr("app.services.dependencies.check_redis", lambda: None)
    monkeypatch.setattr("app.services.dependencies.check_storage", lambda: None)
    result = dependency_checks()
    assert result == {"database": "error", "redis": "ok", "object_storage": "ok"}
    assert "do-not-leak" not in str(result)


def test_explicit_s3_config_does_not_use_or_mutate_ambient_profile(monkeypatch):
    import os

    from app.core.config import Settings
    from app.services.dependencies import storage_client

    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused/unused",
        redis_url="redis://localhost:6379/0",
        s3_endpoint_url="http://localhost:9000",
        s3_access_key_id="test-key",
        s3_secret_access_key="test-secret",
    )
    monkeypatch.setattr("app.services.dependencies.get_settings", lambda: settings)
    monkeypatch.setenv("AWS_PROFILE", "unavailable-ambient-profile")
    client = storage_client()
    assert client.meta.endpoint_url == "http://localhost:9000"
    assert os.environ["AWS_PROFILE"] == "unavailable-ambient-profile"
    client.close()
