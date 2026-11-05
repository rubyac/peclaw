from datetime import timedelta

import pytest
from conftest import ORIGIN, PASSWORD
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import AuditLog, AuthSession, User, now
from app.security.dependencies import COOKIE_NAME, digest

pytestmark = pytest.mark.integration


def test_login_cookie_session_storage_and_logout(identities):
    client = identities["login"]()
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert len(response.json()["organizations"]) == 1
    assert response.headers["cache-control"] == "no-store"
    token = client.cookies[COOKIE_NAME]
    with Session(identities["engine"]) as db:
        session = db.get(AuthSession, digest(token))
        assert session is not None and session.token_digest != token
        user = db.get(User, session.user_id)
        assert user.password_hash.startswith("$argon2id$")
        assert PASSWORD not in user.password_hash
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_invalid_login_generic_and_audited(identities):
    client = TestClient(identities["app"])
    for email in ["user0@example.com", "missing@example.com"]:
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": email, "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert "wrong-password" not in response.text
        assert COOKIE_NAME not in response.cookies
    with Session(identities["engine"]) as db:
        logs = db.scalars(select(AuditLog)).all()
        assert len(logs) == 2 and all(row.result == "denied" for row in logs)


def test_cookie_flags_and_expiration(identities):
    client = TestClient(identities["app"])
    response = client.post(
        "/api/v1/auth/login",
        headers={"Origin": ORIGIN},
        json={"email": "user0@example.com", "password": PASSWORD},
    )
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=28800" in cookie
    with Session(identities["engine"]) as db:
        row = db.get(AuthSession, digest(client.cookies[COOKIE_NAME]))
        row.expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_change_revokes_all_sessions(identities):
    client = identities["login"]()
    other = identities["login"]()
    response = client.post(
        "/api/v1/auth/password",
        json={"current_password": PASSWORD, "new_password": "new-test-password-55!"},
    )
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401
    assert other.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "user0@example.com", "password": "new-test-password-55!"},
        ).status_code
        == 200
    )


def test_project_create_update_and_audit(identities):
    client = identities["login"]()
    org = identities["orgs"][0]
    base = f"/api/v1/organizations/{org}/projects"
    response = client.post(base, json={"name": "Test project", "description": "Private research"})
    assert response.status_code == 201
    project = response.json()["id"]
    assert client.patch(f"{base}/{project}", json={"name": "Revised"}).status_code == 200
    assert client.get(base).json()[0]["name"] == "Revised"
    logs = client.get(f"/api/v1/organizations/{org}/audit").json()
    assert {row["action"] for row in logs} >= {"project.create", "project.update"}
    assert all(row["request_id"] for row in logs)
    assert "Private research" not in str(logs)


def test_login_rate_limit_uses_real_redis_and_fails_closed(identities):
    from uuid import uuid4

    from redis import Redis

    from app.core.config import get_settings
    from app.security.rate_limit import check_login_rate

    peer = "rate-test-" + uuid4().hex
    client = TestClient(identities["app"], client=(peer, 50000))
    account_key = "peclaw:login-rate:account:" + digest("user0@example.com")
    peer_key = "peclaw:login-rate:peer:" + digest(peer)
    redis = Redis.from_url(get_settings().redis_url.get_secret_value())
    identities["app"].dependency_overrides.pop(check_login_rate)
    try:
        redis.set(account_key, get_settings().auth_login_attempts, ex=30)
        response = client.post(
            "/api/v1/auth/login",
            headers={"Origin": ORIGIN},
            json={"email": "user0@example.com", "password": PASSWORD},
        )
        assert response.status_code == 429
        assert not client.cookies
        assert redis.ttl(peer_key) > 0
    finally:
        redis.delete(account_key, peer_key)
        redis.close()
        identities["app"].dependency_overrides[check_login_rate] = lambda: None


def test_operator_provision_disable_and_enable(identities, monkeypatch, capsys):
    from app import provision

    monkeypatch.setattr(provision, "get_engine", lambda: identities["engine"])
    monkeypatch.setattr(provision.getpass, "getpass", lambda prompt: "operator-test-password")
    monkeypatch.setattr(
        "sys.argv",
        [
            "provision",
            "--email",
            "operator-test@example.com",
            "--name",
            "Operator User",
            "--organization",
            "New Organization",
        ],
    )
    provision.main()
    with Session(identities["engine"]) as db:
        created = db.scalar(select(User).where(User.email == "operator-test@example.com"))
        assert created and created.is_active and created.password_hash.startswith("$argon2id$")
    for state in ["--disable", "--enable"]:
        monkeypatch.setattr(
            "sys.argv", ["provision", "--email", "operator-test@example.com", state]
        )
        provision.main()
        with Session(identities["engine"]) as db:
            assert db.get(User, created.id).is_active == (state == "--enable")
    assert "operator-test-password" not in capsys.readouterr().out
