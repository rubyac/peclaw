import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.identity import ProjectInput
from app.security.passwords import hash_password, verify_password


def config(**overrides):
    return Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused/unused",
        redis_url="redis://localhost:6379",
        s3_endpoint_url="http://localhost:9000",
        s3_access_key_id="test",
        s3_secret_access_key="test-secret",
        **overrides,
    )


def test_password_hash_is_salted_and_checks_actual_password():
    first = hash_password("strong-test-password")
    assert first != hash_password("strong-test-password")
    assert verify_password(first, "strong-test-password")
    assert not verify_password(first, "wrong")
    assert not verify_password("malformed-hash", "strong-test-password")


def test_production_requires_secure_cookie_and_https_origin():
    with pytest.raises(ValidationError):
        config(app_env="production")
    with pytest.raises(ValidationError):
        config(app_env="production", auth_cookie_secure=True)
    assert config(
        app_env="production",
        auth_cookie_secure=True,
        auth_allowed_origins=["https://research.example.com"],
    ).auth_cookie_secure


@pytest.mark.parametrize(
    "origins",
    [
        [],
        ["*"],
        ["https://example.com/"],
        ["https://user:pass@example.com"],
        ["not-an-origin"],
    ],
)
def test_invalid_origin_configuration_rejected(origins):
    with pytest.raises(ValidationError):
        config(auth_allowed_origins=origins)


def test_client_cannot_inject_tenant_or_actor_into_project_payload():
    with pytest.raises(ValidationError):
        ProjectInput(name="Company", organization_id="forged", created_by="forged")
    with pytest.raises(ValidationError):
        ProjectInput(name="   ")
