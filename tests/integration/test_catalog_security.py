import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.integration, pytest.mark.security]


def test_institution_admin_cannot_publish_global_data(identities):
    owner = identities["login"]()
    assert owner.get("/api/v1/companies").status_code == 200
    assert (
        owner.post(
            "/api/v1/catalog/sources",
            json={
                "source_name": "No permission",
                "source_type": "manual",
                "license_type": "synthetic_demo",
                "permitted_use": "Public demonstration only",
                "public_confirmed": True,
            },
        ).status_code
        == 403
    )
    assert (
        owner.post(
            "/api/v1/companies",
            json={
                "canonical_name": "Private institution project",
                "source_id": str(identities["orgs"][0]),
                "reason": "Should not become public",
            },
        ).status_code
        == 403
    )
    assert owner.get("/api/v1/catalog/imports").status_code == 403
    assert owner.get("/api/v1/catalog/audit").status_code == 403


def test_unauthenticated_and_inactive_members_cannot_read(catalog):
    anon = TestClient(catalog["app"])
    assert anon.get("/api/v1/companies").status_code == 401
    owner = catalog["client"]
    viewer = catalog["login"](2)
    org = catalog["orgs"][0]
    assert (
        owner.patch(
            f"/api/v1/organizations/{org}/members/{catalog['users'][2]}",
            json={"role": "viewer", "is_active": False},
        ).status_code
        == 200
    )
    assert viewer.get("/api/v1/companies").status_code == 403


def test_private_projects_are_not_public_catalog_input(catalog):
    owner = catalog["client"]
    org = catalog["orgs"][0]
    result = owner.post(
        f"/api/v1/organizations/{org}/projects",
        json={"name": "PRIVATE SECRET RESEARCH"},
    )
    assert result.status_code == 201
    assert owner.get("/api/v1/companies", params={"q": "PRIVATE SECRET"}).json()["total"] == 0
    assert (
        owner.post(
            "/api/v1/companies",
            json={
                "canonical_name": "Injected organization data",
                "organization_id": str(org),
                "source_id": catalog["source_id"],
                "reason": "Invalid public input",
            },
        ).status_code
        == 422
    )
    assert (
        catalog["login"](3)
        .get(f"/api/v1/organizations/{org}/projects/{result.json()['id']}")
        .status_code
        == 404
    )


def test_public_audit_excludes_private_operations(catalog):
    owner = catalog["client"]
    org = catalog["orgs"][0]
    owner.post(
        f"/api/v1/organizations/{org}/projects",
        json={"name": "PRIVATE SECRET RESEARCH"},
    )
    catalog["create"]()
    result = owner.get("/api/v1/catalog/audit")
    assert result.status_code == 200 and result.json()
    assert all(row["action"].startswith("catalog.") for row in result.json())
    assert "PRIVATE SECRET" not in result.text


def test_global_curator_flag_cannot_be_granted_by_organization_api(identities):
    owner = identities["login"]()
    org = identities["orgs"][0]
    response = owner.patch(
        f"/api/v1/organizations/{org}/members/{identities['users'][0]}",
        json={"role": "owner", "is_active": True, "is_data_curator": True},
    )
    assert response.status_code == 422
    assert owner.get("/api/v1/auth/me").json()["can_curate_public_data"] is False


def test_operator_can_grant_and_revoke_curator_without_password_changes(identities, monkeypatch):
    from app import provision

    monkeypatch.setattr(provision, "get_engine", lambda: identities["engine"])
    client = identities["login"]()
    for operation, expected in [("grant", True), ("revoke", False)]:
        monkeypatch.setattr(
            "sys.argv",
            ["provision", "--email", "user0@example.com", "--data-curator", operation],
        )
        provision.main()
        assert client.get("/api/v1/auth/me").json()["can_curate_public_data"] is expected
