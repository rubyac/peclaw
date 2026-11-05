import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import AuditLog, AuthSession, Membership, User, now
from app.security.dependencies import COOKIE_NAME, digest
from app.security.tasks import TaskContext, authorized_task, capture_context

pytestmark = [pytest.mark.integration, pytest.mark.security]


def project(client, org):
    base = f"/api/v1/organizations/{org}/projects"
    response = client.post(base, json={"name": "Confidential project"})
    assert response.status_code == 201
    return base, response.json()["id"]


def test_cross_tenant_routes_deny_reads_writes_members_and_audit(identities):
    owner = identities["login"]()
    outsider = identities["login"](3)
    org = identities["orgs"][0]
    base, pid = project(owner, org)
    for method, path, payload in [
        ("GET", base, None),
        ("GET", f"{base}/{pid}", None),
        ("PATCH", f"{base}/{pid}", {"name": "Hacked"}),
        ("GET", f"{base}/{pid}/members", None),
        (
            "PUT",
            f"{base}/{pid}/members",
            {"user_id": str(identities["users"][3]), "role": "manager"},
        ),
        ("GET", f"/api/v1/organizations/{org}/members", None),
        ("GET", f"/api/v1/organizations/{org}/audit", None),
    ]:
        response = outsider.request(method, path, json=payload)
        assert response.status_code == 404, (method, path, response.text)
        assert "Confidential" not in response.text
    fake_org = identities["orgs"][1]
    assert outsider.get(f"/api/v1/organizations/{fake_org}/projects/{pid}").status_code == 404
    assert owner.get(f"{base}/{pid}").json()["name"] == "Confidential project"


def test_same_tenant_project_isolation_and_explicit_admin_grant(identities):
    owner = identities["login"]()
    colleague = identities["login"](1)
    admin = identities["login"](4)
    org = identities["orgs"][0]
    base, pid = project(owner, org)
    for client in [colleague, admin]:
        assert client.get(base).json() == []
        assert client.get(f"{base}/{pid}").status_code == 404
    # Organization administrator may manage ACLs, but has no implicit data access.
    assert (
        admin.put(
            f"{base}/{pid}/members",
            json={"user_id": str(identities["users"][4]), "role": "viewer"},
        ).status_code
        == 200
    )
    assert admin.get(f"{base}/{pid}").status_code == 200
    assert admin.patch(f"{base}/{pid}", json={"name": "Denied"}).status_code == 403
    assert colleague.get(f"{base}/{pid}").status_code == 404


def test_role_intersection_last_manager_and_cross_org_assignment(identities):
    owner = identities["login"]()
    viewer = identities["login"](2)
    org = identities["orgs"][0]
    base, pid = project(owner, org)
    assert (
        owner.put(
            f"{base}/{pid}/members",
            json={"user_id": str(identities["users"][3]), "role": "viewer"},
        ).status_code
        == 404
    )
    assert (
        owner.put(
            f"{base}/{pid}/members",
            json={"user_id": str(identities["users"][2]), "role": "editor"},
        ).status_code
        == 200
    )
    assert viewer.get(f"{base}/{pid}").status_code == 200
    assert viewer.patch(f"{base}/{pid}", json={"name": "Denied"}).status_code == 403
    assert viewer.post(base, json={"name": "Denied"}).status_code == 403
    assert owner.delete(f"{base}/{pid}/members/{identities['users'][0]}").status_code == 409


def test_membership_revocation_is_immediate_and_only_affects_one_tenant(identities):
    owner = identities["login"]()
    member = identities["login"](1)
    org, other_org = identities["orgs"]
    base, pid = project(member, org)
    route = f"/api/v1/organizations/{org}/members/{identities['users'][1]}"
    assert owner.patch(route, json={"role": "member", "is_active": False}).status_code == 200
    assert member.get(f"{base}/{pid}").status_code == 404
    assert member.get(f"/api/v1/organizations/{other_org}/projects").status_code == 200
    assert len(member.get("/api/v1/auth/me").json()["organizations"]) == 1


def test_owner_and_admin_role_boundaries(identities):
    owner = identities["login"]()
    admin = identities["login"](4)
    member = identities["login"](1)
    org = identities["orgs"][0]
    base = f"/api/v1/organizations/{org}/members"
    assert (
        owner.patch(
            f"{base}/{identities['users'][0]}",
            json={"role": "admin", "is_active": True},
        ).status_code
        == 409
    )
    assert (
        admin.patch(
            f"{base}/{identities['users'][0]}",
            json={"role": "member", "is_active": True},
        ).status_code
        == 403
    )
    assert (
        admin.patch(
            f"{base}/{identities['users'][1]}",
            json={"role": "owner", "is_active": True},
        ).status_code
        == 403
    )
    assert member.get(base).status_code == 403


def test_csrf_origin_and_anonymous_access(identities):
    anonymous = TestClient(identities["app"])
    org = identities["orgs"][0]
    assert anonymous.get(f"/api/v1/organizations/{org}/projects").status_code == 401
    assert (
        anonymous.post(
            "/api/v1/auth/login",
            json={"email": "user0@example.com", "password": "anything"},
        ).status_code
        == 403
    )
    client = identities["login"]()
    for headers in [{"Origin": "https://evil.example"}, {"X-CSRF-Token": "forged"}]:
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 403
    assert (
        client.post(
            "/api/v1/auth/logout", headers=[(b"x-csrf-token", bytes([255]) * 64)]
        ).status_code
        == 403
    )
    assert client.get("/api/v1/auth/me").status_code == 200
    with Session(identities["engine"]) as db:
        denied = db.scalars(select(AuditLog).where(AuditLog.action == "csrf.reject")).all()
        assert len(denied) == 2 and all(row.result == "denied" and row.request_id for row in denied)
        assert "forged" not in str(denied[0].details)


def test_disabled_users_and_revoked_sessions(identities):
    client = identities["login"]()
    with Session(identities["engine"]) as db:
        user = db.get(User, identities["users"][0])
        user.is_active = False
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401
    with Session(identities["engine"]) as db:
        db.get(User, identities["users"][0]).is_active = True
        db.get(AuthSession, digest(client.cookies[COOKIE_NAME])).revoked_at = now()
        db.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_background_context_roundtrip_and_reauthorization(identities):
    member_client = identities["login"](1)
    org, other_org = identities["orgs"]
    _, pid = project(member_client, org)
    from uuid import UUID

    with Session(identities["engine"]) as db:
        actor = db.get(User, identities["users"][1])
        context = capture_context(db, actor, org, UUID(pid))
    restored = TaskContext.model_validate_json(context.model_dump_json())
    from concurrent.futures import ThreadPoolExecutor

    def background_read(serialized: str):
        task = TaskContext.model_validate_json(serialized)
        with authorized_task(task) as (_, stored):
            return stored.id, stored.organization_id

    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(background_read, restored.model_dump_json()).result(timeout=5)
        assert result == (UUID(pid), org)
    forged = restored.model_copy(update={"organization_id": other_org})
    with pytest.raises(HTTPException), authorized_task(forged):
        pytest.fail("Cross-tenant task must never execute")
    with Session(identities["engine"]) as db:
        membership = db.get(Membership, (org, identities["users"][1]))
        membership.is_active = False
        db.commit()
    with pytest.raises(HTTPException), authorized_task(restored):
        pytest.fail("Revoked permissions must be rechecked at execution")


def test_concurrent_owner_demotion_preserves_one_owner(identities):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    owner = identities["login"]()
    colleague = identities["login"](1)
    org = identities["orgs"][0]
    base = f"/api/v1/organizations/{org}/members"
    assert (
        owner.patch(
            f"{base}/{identities['users'][1]}",
            json={"role": "owner", "is_active": True},
        ).status_code
        == 200
    )
    barrier = Barrier(2)

    def demote(client, user_id):
        barrier.wait(timeout=5)
        return client.patch(
            f"{base}/{user_id}", json={"role": "member", "is_active": True}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(demote, client, user_id)
            for client, user_id in [
                (owner, identities["users"][0]),
                (colleague, identities["users"][1]),
            ]
        ]
        assert sorted(future.result() for future in futures) == [200, 409]
    with Session(identities["engine"]) as db:
        remaining = db.scalars(
            select(Membership).where(
                Membership.organization_id == org,
                Membership.role == "owner",
                Membership.is_active.is_(True),
            )
        ).all()
        assert len(remaining) == 1
